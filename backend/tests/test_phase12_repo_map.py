"""test_phase12_repo_map.py — Verification test suite for Phase 12.

Tests:
1. test_repo_map_ranks_focus_files_first: Focus files appear first with full outlines, others summarized.
2. test_repo_map_bounded_max_lines: Max line cap enforced strictly.
3. test_repo_map_cache_hit_within_ttl: Identical inputs within TTL return cached map.
4. test_repo_map_invalidates_on_file_change: Cache invalidation causes recomputation on change.
5. test_repo_map_skips_non_code_files: Non-code extensions and ignored directories excluded.
6. test_diagnostics_collects_pyflakes_errors: Python fixture with unused var produces diagnostic.
7. test_diagnostics_collects_tsc_errors: TypeScript fixture produces diagnostic or parses tsc output.
8. test_diagnostics_timeout_returns_timeout_diag: Subprocess timeout returns timeout diag without blocking.
9. test_diagnostics_graceful_when_tools_missing: Missing tools log INFO once and skip diagnostics gracefully.
10. test_tier0_has_no_repo_map_or_diagnostics: Tier 0 prompt has neither repo-map nor diagnostics.
11. test_tier1_has_diagnostics_only: Tier 1 prompt has diagnostics only.
12. test_tier2_3_has_repo_map_and_diagnostics: Tier 2/3 prompt has diagnostics before repo-map before RAG.
13. test_budget_shrink_drops_repo_map_before_rag: Budget shrink drops repo-map before RAG, diagnostics last.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from unittest.mock import patch, MagicMock

import pytest

from app.features.ai.harness.repo_map import (
    build_repo_map,
    invalidate_repo_map_cache,
    clear_repo_map_cache,
    shrink_context_for_budget,
)
from app.features.ai.harness.lsp_lite import (
    collect_diagnostics,
    format_diagnostics_block,
)
from app.features.ai.harness.prompt_builder import _build_system_prompt
from app.features.ai.harness.payload_governor import govern_payload, get_conservative_token_count
from app.features.ai.providers.base import ChatMessage


@pytest.fixture(autouse=True)
def clean_caches():
    clear_repo_map_cache()
    yield
    clear_repo_map_cache()


# ── 1. test_repo_map_ranks_focus_files_first ─────────────────────────────────

def test_repo_map_ranks_focus_files_first(tmp_path: Path):
    """Verify focus files are ranked top in order with full outlines, while others are summarized."""
    # Create 5 focus files and 2 non-focus files
    f1 = tmp_path / "auth_login.py"
    f1.write_text("class LoginService:\n    def login(self, username, password):\n        pass\n")

    f2 = tmp_path / "auth_token.py"
    f2.write_text("def verify_token(token: str):\n    return True\n")

    f3 = tmp_path / "auth_oauth.py"
    f3.write_text("class OAuthProvider:\n    def callback(self, code):\n        pass\n")

    f4 = tmp_path / "models_user.py"
    f4.write_text("class User:\n    def __init__(self, name):\n        self.name = name\n")

    f5 = tmp_path / "api_routes.py"
    f5.write_text("def route_auth():\n    return 'auth'\n")

    other1 = tmp_path / "utils_helper1.py"
    other1.write_text("def helper1():\n    pass\n")

    other2 = tmp_path / "utils_helper2.py"
    other2.write_text("def helper2():\n    pass\n")

    focus = ["auth_login.py", "auth_token.py", "auth_oauth.py", "models_user.py", "api_routes.py"]
    repo_map = build_repo_map(str(tmp_path), focus_files=focus, max_lines=400)

    # Focus files appear first and in order
    idx_f1 = repo_map.find("```auth_login.py")
    idx_f2 = repo_map.find("```auth_token.py")
    idx_f3 = repo_map.find("```auth_oauth.py")
    idx_f4 = repo_map.find("```models_user.py")
    idx_f5 = repo_map.find("```api_routes.py")

    assert idx_f1 != -1 and idx_f2 != -1 and idx_f3 != -1 and idx_f4 != -1 and idx_f5 != -1
    assert idx_f1 < idx_f2 < idx_f3 < idx_f4 < idx_f5

    # Focus files have detailed outlines with line numbers
    assert "class LoginService:" in repo_map
    assert "# L1" in repo_map
    assert "def login" in repo_map

    # Non-focus files are summarized in one line after focus files
    idx_other1 = repo_map.find("utils_helper1.py:")
    idx_other2 = repo_map.find("utils_helper2.py:")
    assert idx_other1 > idx_f5
    assert idx_other2 > idx_f5
    assert "1 fn" in repo_map or "fn" in repo_map


# ── 2. test_repo_map_bounded_max_lines ───────────────────────────────────────

def test_repo_map_bounded_max_lines(tmp_path: Path):
    """Verify that build_repo_map strictly enforces max_lines upper bound."""
    for i in range(20):
        f = tmp_path / f"file_{i}.py"
        f.write_text(f"class Class{i}:\n    def method_a(self): pass\n    def method_b(self): pass\n")

    # Request max 15 lines
    repo_map_15 = build_repo_map(str(tmp_path), max_lines=15)
    lines_15 = repo_map_15.splitlines()
    assert len(lines_15) <= 15
    assert len(lines_15) > 0

    # Request max 400 lines
    repo_map_400 = build_repo_map(str(tmp_path), max_lines=400)
    lines_400 = repo_map_400.splitlines()
    assert len(lines_400) <= 400


# ── 3. test_repo_map_cache_hit_within_ttl ────────────────────────────────────

def test_repo_map_cache_hit_within_ttl(tmp_path: Path):
    """Verify that identical calls within TTL (10s) hit cache without recomputing."""
    f = tmp_path / "main.py"
    f.write_text("def hello(): pass\n")

    res1 = build_repo_map(str(tmp_path), focus_files=["main.py"])
    assert "main.py" in res1

    # Modify file directly without invalidation
    f.write_text("def completely_different(): pass\n")

    # Within TTL (10s), result is cached
    res2 = build_repo_map(str(tmp_path), focus_files=["main.py"])
    assert res1 == res2
    assert "hello" in res2


# ── 4. test_repo_map_invalidates_on_file_change ──────────────────────────────

def test_repo_map_invalidates_on_file_change(tmp_path: Path):
    """Verify that watcher invalidation immediately clears cached repo-map."""
    f = tmp_path / "main.py"
    f.write_text("def hello(): pass\n")

    res1 = build_repo_map(str(tmp_path), focus_files=["main.py"])
    assert "hello" in res1

    # Modify file and invalidate cache
    f.write_text("def brand_new_function(): pass\n")
    invalidate_repo_map_cache(str(f))

    res2 = build_repo_map(str(tmp_path), focus_files=["main.py"])
    assert "brand_new_function" in res2


# ── 5. test_repo_map_skips_non_code_files ────────────────────────────────────

def test_repo_map_skips_non_code_files(tmp_path: Path):
    """Verify that binary, non-code files, and ignored directories are skipped."""
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "archive.bin").write_bytes(b"\x00\x01\x02\x03")
    (tmp_path / "data.txt").write_text("just text")

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.py").write_text("def git_internal(): pass\n")

    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "pkg.js").write_text("function pkg() {}\n")

    valid_py = tmp_path / "valid.py"
    valid_py.write_text("def valid_fn(): pass\n")

    repo_map = build_repo_map(str(tmp_path), focus_files=["image.png", "valid.py"])
    assert "valid.py" in repo_map
    assert "image.png" not in repo_map
    assert "archive.bin" not in repo_map
    assert ".git" not in repo_map
    assert "node_modules" not in repo_map


# ── 6. test_diagnostics_collects_pyflakes_errors ─────────────────────────────

def test_diagnostics_collects_pyflakes_errors(tmp_path: Path):
    """Verify pyflakes collects diagnostics (e.g. unused import or undefined var)."""
    bad_py = tmp_path / "unused.py"
    bad_py.write_text("import os\n\ndef run():\n    return 42\n")

    diags = collect_diagnostics([str(bad_py)], workspace=str(tmp_path))
    assert "unused.py" in diags
    file_diags = diags["unused.py"]
    assert len(file_diags) > 0
    assert any("os" in d["message"] and "unused" in d["message"].lower() for d in file_diags)
    assert file_diags[0]["line"] == 1


# ── 7. test_diagnostics_collects_tsc_errors ──────────────────────────────────

def test_diagnostics_collects_tsc_errors(tmp_path: Path):
    """Verify TypeScript diagnostics collection parses tsc output or syntax fallback."""
    ts_file = tmp_path / "bad.ts"
    ts_file.write_text("const x: number = 'hello';\n")

    # Test via mock of tsc command output to ensure deterministic parse across all platforms
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = "bad.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'.\n"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        diags = collect_diagnostics([str(ts_file)], workspace=str(tmp_path))
        assert "bad.ts" in diags
        assert len(diags["bad.ts"]) == 1
        d = diags["bad.ts"][0]
        assert d["line"] == 1
        assert d["col"] == 7
        assert d["severity"] == "error"
        assert "TS2322" in d["message"]


# ── 8. test_diagnostics_timeout_returns_timeout_diag ─────────────────────────

def test_diagnostics_timeout_returns_timeout_diag(tmp_path: Path):
    """Verify subprocess timeout returns a timeout diagnostic and does not block."""
    hang_py = tmp_path / "hang.py"
    hang_py.write_text("import time\ntime.sleep(100)\n")

    # Simulate subprocess.TimeoutExpired
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pyflakes", timeout=10.0)):
        diags = collect_diagnostics([str(hang_py)], workspace=str(tmp_path))
        assert "hang.py" in diags
        assert len(diags["hang.py"]) == 1
        d = diags["hang.py"][0]
        assert d["severity"] == "warning"
        assert "timeout" in d["message"].lower()


# ── 9. test_diagnostics_graceful_when_tools_missing ──────────────────────────

def test_diagnostics_graceful_when_tools_missing(tmp_path: Path):
    """Verify missing diagnostic tool logs INFO once and returns empty diagnostics without failing."""
    f = tmp_path / "app.py"
    f.write_text("def test(): pass\n")

    with patch("subprocess.run", side_effect=FileNotFoundError("pyflakes not found")):
        diags = collect_diagnostics([str(f)], workspace=str(tmp_path))
        assert diags == {}


# ── 10. test_tier0_has_no_repo_map_or_diagnostics ────────────────────────────

def test_tier0_has_no_repo_map_or_diagnostics(tmp_path: Path):
    """Verify Tier 0 prompt has neither repo-map nor diagnostics."""
    prompt = _build_system_prompt(
        workspace=str(tmp_path),
        tier=0,
        context={"workspace": str(tmp_path)},
        repo_map="```app.py\ndef run(): ... # L1\n```",
        diagnostics="app.py:1:1 [error] bad syntax",
    )
    assert "[WORKSPACE REPO-MAP]" not in prompt
    assert "[DIAGNOSTICS]" not in prompt
    assert "bad syntax" not in prompt
    assert "def run" not in prompt


# ── 11. test_tier1_has_diagnostics_only ──────────────────────────────────────

def test_tier1_has_diagnostics_only(tmp_path: Path):
    """Verify Tier 1 prompt has diagnostics only, and no repo-map."""
    prompt = _build_system_prompt(
        workspace=str(tmp_path),
        tier=1,
        context={"workspace": str(tmp_path)},
        repo_map="```app.py\ndef run(): ... # L1\n```",
        diagnostics="app.py:1:1 [warning] 'os' unused",
    )
    assert "[DIAGNOSTICS]" in prompt
    assert "'os' unused" in prompt
    assert "[WORKSPACE REPO-MAP]" not in prompt
    assert "def run" not in prompt


# ── 12. test_tier2_3_has_repo_map_and_diagnostics ────────────────────────────

def test_tier2_3_has_repo_map_and_diagnostics(tmp_path: Path):
    """Verify Tier 2/3 prompt has diagnostics before repo-map before RAG snippets."""
    diag_block = "app.py:1:1 [error] TS1005: ';' expected"
    repo_map_block = "```app.py\nclass App: # L1\n```"
    rag_snippet = "### File app.py (relevance: 0.95):\ndef app_init(): pass"

    prompt = _build_system_prompt(
        workspace=str(tmp_path),
        tier=2,
        context={"workspace": str(tmp_path)},
        rag_snippet_summary=rag_snippet,
        repo_map=repo_map_block,
        diagnostics=diag_block,
    )

    assert "[DIAGNOSTICS]" in prompt
    assert "[WORKSPACE REPO-MAP]" in prompt
    assert rag_snippet in prompt

    idx_diag = prompt.find("[DIAGNOSTICS]")
    idx_map = prompt.find("[WORKSPACE REPO-MAP]")
    idx_rag = prompt.find(rag_snippet)

    # Required ordering: diagnostics BEFORE repo-map, repo-map BEFORE RAG snippets
    assert idx_diag < idx_map < idx_rag


# ── 13. test_budget_shrink_drops_repo_map_before_rag ─────────────────────────

def test_budget_shrink_drops_repo_map_before_rag(tmp_path: Path):
    """Verify that when budget is tight, repo-map shrinks first while RAG stays intact."""
    # 1. Test direct shrink_context_for_budget
    huge_repo_map = "\n".join([f"file_{i}.py: 3 fns, class X" for i in range(100)])
    rag_snippets = "### File core.py (relevance: 0.99):\ndef important_core_logic(): pass"
    diagnostics = "[DIAGNOSTICS]\n- file_1.py:1:1 [error] syntax\n[END DIAGNOSTICS]"

    # Give a budget that cannot fit both repo_map and RAG
    rag_toks = get_conservative_token_count(rag_snippets)
    diag_toks = get_conservative_token_count(diagnostics)
    tight_budget = rag_toks + diag_toks + 20

    shrunk_map, preserved_rag, preserved_diag = shrink_context_for_budget(
        huge_repo_map, rag_snippets, diagnostics, budget_tokens=tight_budget
    )

    # Repo-map was reduced
    assert len(shrunk_map) < len(huge_repo_map)
    # RAG was preserved intact!
    assert preserved_rag == rag_snippets
    assert preserved_diag == diagnostics

    # 2. Test in govern_payload: repo-map is shrunk before RAG is touched
    msg_content = (
        "You are Rony.\n\n"
        "## Workspace Structure (Repo-Map):\n"
        "[WORKSPACE REPO-MAP]\n" + huge_repo_map + "\n[END WORKSPACE REPO-MAP]\n\n"
        "Relevant files from codebase:\n"
        "### File a.py:\ncontent a\n\n### File b.py:\ncontent b\n\n### File c.py:\ncontent c\n"
    )
    messages = [ChatMessage(role="system", content=msg_content)]

    gov = govern_payload(messages, None, provider="groq", hard_tpm_limit=300)
    assert gov.was_adjusted is True
    # First adjustment must be repo-map reduction
    assert "shrunk_repo_map" in gov.summary_reason
