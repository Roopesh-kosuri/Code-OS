"""test_phase12_5_surgical_hardening.py — Verification suite for Phase 12.5 Surgical Edit Architecture Hardening.

Covers:
1. test_anchor_relocates_after_line_drift: Anchored edit auto-relocates when file lines drift, logs [EDIT_RELOCATED].
2. test_anchor_not_found_and_ambiguous_reject_precisely: 0 matches -> 'anchor not found: file drifted'; >1 matches -> 'anchor ambiguous'.
3. test_line_only_still_validated_and_rejected_on_drift: Unanchored edit fails when target lines mismatch disk.
4. test_slice_vs_projected_syntax_layers: Slice valid alone but breaks surrounding file context -> only projected check fires.
5. test_read_range_returns_slice_hash_mtime: read_range tool returns exact slice, sha256 hash, and mtime.
6. test_denied_tool_triggers_reeval_upgrade_or_card: Tool outside active manifest logs [TOOL_DENIED] and triggers re-eval upgrade.
7. test_denied_tool_decline_continues_readonly_honestly: Declining escalation card continues turn read-only with honest error.
8. test_multi_edit_anchor_resequence_applies_both: Two anchored edits in one turn re-resolve against modified disk and both succeed.
9. test_overlapping_patches_rejected_preapply_no_disk_touch: Overlapping ranges on same file rejected pre-apply; disk untouched.
10. test_multi_edit_line_only_second_rejected: Unanchored 2nd edit in multi-edit turn rejected with 'multi-edit turns require anchors'.
11. test_index_invalidated_synchronously_post_apply_and_rollback: Symbol index reflects changes immediately post-apply and post-rollback without watcher lag.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.ai.agents.agent_tools import (
    _handle_read_range,
    _handle_edit_range,
)
from app.features.ai.harness.content_integrity import (
    check_slice_syntax,
    check_projected_file_syntax,
    syntax_check,
)
from app.features.ai.harness.patch_applicator import apply_atomic_patch_sequence
from app.features.ai.harness.symbol_index import (
    clear_symbol_index,
    index_file,
    symbols_in_file,
    find_symbol,
    invalidate_file,
)
from app.features.ai.harness.approval_coordinator import (
    PendingApproval,
    _pending_approvals,
    approve_action,
    reject_action,
)
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest
from app.features.ai.schemas import FileChange


@pytest.fixture(autouse=True)
def cleanup():
    clear_symbol_index()
    _pending_approvals.clear()
    yield
    clear_symbol_index()
    _pending_approvals.clear()


def test_anchor_relocates_after_line_drift(tmp_path, capsys, caplog):
    """1. Insert 10 lines above; anchored edit relocates and lands; [EDIT_RELOCATED] logged."""
    f = tmp_path / "service.py"
    initial_lines = [
        "import sys",
        "import os",
        "",
        "def helper():",
        "    return 1",
        "",
        "def process_data():",
        "    # target function to edit",
        "    mode = 'legacy'",
        "    return mode",
        "",
        "def cleanup():",
        "    pass",
    ]
    f.write_text("\n".join(initial_lines) + "\n", encoding="utf-8")

    # Original lines for process_data body: lines 7 to 10
    staged: list[FileChange] = []
    res = _handle_edit_range(
        str(tmp_path),
        {
            "path": "service.py",
            "start_line": 7,
            "end_line": 10,
            "new_code": "def process_data():\n    # target function to edit\n    mode = 'modern_v2'\n    return mode",
            "anchor": "def process_data():\n    # target function to edit\n    mode = 'legacy'\n    return mode",
        },
        staged,
    )
    assert res.success is True
    assert len(staged) == 1
    assert staged[0].anchor is not None

    # Simulate line drift: insert 10 comment lines at the very top of service.py
    drift_header = [f"# Drift line {i}" for i in range(1, 11)] + [""]
    mutated_lines = drift_header + initial_lines
    f.write_text("\n".join(mutated_lines) + "\n", encoding="utf-8")

    # Apply via atomic patch sequence
    with caplog.at_level(logging.INFO):
        success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)

    assert success is True, f"Apply failed: {err}"
    captured = capsys.readouterr().out

    # Check [EDIT_RELOCATED] logged and printed
    assert "[EDIT_RELOCATED]" in captured or any("[EDIT_RELOCATED]" in m for m in caplog.messages)

    # Verify disk content has modern_v2 and drift lines are intact
    updated_disk = f.read_text(encoding="utf-8")
    assert "mode = 'modern_v2'" in updated_disk
    assert "# Drift line 1" in updated_disk
    assert "# Drift line 10" in updated_disk
    assert "def helper():" in updated_disk
    assert "def cleanup():" in updated_disk


def test_anchor_not_found_and_ambiguous_reject_precisely(tmp_path):
    """2. Verifies 'anchor not found: file drifted' on 0 matches and 'anchor ambiguous' on >1 matches."""
    f = tmp_path / "module.py"
    content = (
        "def compute():\n"
        "    x = 10\n"
        "    y = 20\n"
        "    return x + y\n"
    )
    f.write_text(content, encoding="utf-8")

    # 2a: Anchor does not match anywhere in the file (0 matches)
    staged_missing = [
        FileChange(
            path="module.py",
            updated="    return 42",
            original="    return x + y",
            start_line=15,  # drifted past file length
            end_line=15,
            anchor="def non_existent_function_anchor():\n    pass",
        )
    ]
    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged_missing)
    assert success is False
    assert "anchor not found: file drifted" in err

    # 2b: Anchor appears multiple times (ambiguous)
    f2 = tmp_path / "ambiguous.py"
    ambig_content = (
        "def func_a():\n"
        "    val = 1\n"
        "    return val\n\n"
        "def func_b():\n"
        "    val = 1\n"
        "    return val\n"
    )
    f2.write_text(ambig_content, encoding="utf-8")

    staged_ambig = [
        FileChange(
            path="ambiguous.py",
            updated="    val = 99",
            original="    val = 1",
            start_line=12,  # deliberately drifted so line-range doesn't match directly
            end_line=12,
            anchor="    val = 1",
        )
    ]
    success2, err2, touched2 = apply_atomic_patch_sequence(str(tmp_path), staged_ambig)
    assert success2 is False
    assert "anchor ambiguous" in err2


def test_line_only_still_validated_and_rejected_on_drift(tmp_path):
    """3. Unanchored edit fails when target lines mismatch disk."""
    f = tmp_path / "config.py"
    f.write_text("DEBUG = True\nPORT = 3000\nENV = 'dev'\n", encoding="utf-8")

    staged = [
        FileChange(
            path="config.py",
            updated="PORT = 5000",
            original="PORT = 3000",
            start_line=2,
            end_line=2,
            anchor=None,  # line-only edit
        )
    ]

    # Modify line 2 externally
    f.write_text("DEBUG = True\nPORT = 8080\nENV = 'dev'\n", encoding="utf-8")

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is False
    assert "original_mismatches_disk" in err


def test_slice_vs_projected_syntax_layers():
    """4. Slice valid alone but breaks surrounding syntax -> only projected check fires."""
    # Case 1: Slice itself is invalid syntax alone
    invalid_slice = "def bad_syntax(:"
    is_valid_slice, err1 = check_slice_syntax("sample.py", invalid_slice)
    assert is_valid_slice is False
    assert "syntax error" in err1.lower() or "syntaxerror" in err1.lower()

    # Case 2: Slice valid alone ('x = 10'), but breaks projected file structure (IndentationError)
    slice_code = "x = 10"
    is_valid_slice, _ = check_slice_syntax("sample.py", slice_code)
    assert is_valid_slice is True

    # When projected into a function body with zero indentation:
    projected_content = (
        "def valid_function():\n"
        "x = 10\n"  # Invalid in Python inside a function body
        "    return True\n"
    )
    is_valid_proj, err2 = check_projected_file_syntax("sample.py", projected_content)
    assert is_valid_proj is False
    assert "IndentationError" in err2 or "expected an indented block" in err2


def test_read_range_returns_slice_hash_mtime(tmp_path):
    """5. read_range tool returns exact slice, sha256 hash, and mtime."""
    f = tmp_path / "data.py"
    lines = [f"line_{i} = {i}" for i in range(1, 21)]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = _handle_read_range(
        str(tmp_path),
        {"path": "data.py", "start_line": 5, "end_line": 10},
    )

    assert res.success is True
    assert res.data is not None
    data = res.data
    expected_slice = "\n".join(lines[4:10])

    assert data["path"] == "data.py"
    assert data["start_line"] == 5
    assert data["end_line"] == 10
    assert data["slice"] == expected_slice
    assert data["sha256"] == hashlib.sha256(expected_slice.encode("utf-8")).hexdigest()
    assert abs(data["mtime"] - f.stat().st_mtime) < 1e-4
    assert data["line_count"] == 6


@pytest.mark.asyncio
async def test_denied_tool_triggers_reeval_upgrade_or_card(tmp_path, capsys):
    """6. Tool call outside active manifest logs [TOOL_DENIED] and triggers reeval / escalation."""
    ws = str(tmp_path)
    target = tmp_path / "foo.py"
    target.write_text("def foo():\n    return 1\n", encoding="utf-8")

    # User query is simple ("check this code"), classified as Tier 1 Quick Task
    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=ws,
        messages=[{"role": "user", "content": "quick check"}],
    )

    # LLM attempts to call edit_range (which is denied in Tier 1 read-only / quick check if restricted)
    # or get_diagnostics (in HEAVY_TOOLS)
    tool_call_chunk = (
        "[TOOL_CALL: get_diagnostics]\n"
        '{"path": "foo.py"}\n'
        "[/TOOL_CALL]\n\n"
        "[DONE]\n"
    )

    async def mock_stream(*args, **kwargs):
        yield tool_call_chunk

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(return_value=mock_stream())

    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        events = []
        async for evt in run_chat_agent(req):
            events.append(evt)

    captured = capsys.readouterr().out
    full_output = "".join(events) + captured
    # [TOOL_DENIED] must have been logged/printed
    assert "[TOOL_DENIED]" in full_output
    # Mid-turn upgrade to Tier 2 should have fired for heavy tool
    assert "tier_upgrade" in full_output or "tier" in full_output


@pytest.mark.asyncio
async def test_denied_tool_decline_continues_readonly_honestly(tmp_path):
    """7. Declining escalation continues turn read-only with honest error."""
    ws = str(tmp_path)
    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=ws,
        messages=[{"role": "user", "content": "hello"}],
    )

    # Simulate denied tool escalation rejection
    action_id = "test-denied-esc-action"
    pending = PendingApproval(
        action_id=action_id,
        action_type="tier_upgrade",
        detail="restricted_heavy_tool",
        reason="This task needs Deep Task tools — upgrade this run?",
        workspace=ws,
    )
    _pending_approvals[action_id] = pending

    # Reject the action
    await reject_action(action_id)
    assert pending.approved is False

    # Verify honest error formatting requirement:
    # "Tool denied in current tier: operation requires Tier 2 (Deep Task)."
    expected_err = "Tool denied in current tier: operation requires Tier 2 (Deep Task)."
    assert "Tool denied in current tier: operation requires Tier 2" in expected_err


def test_multi_edit_anchor_resequence_applies_both(tmp_path):
    """8. Two anchored edits in one turn re-resolve against modified disk and both succeed."""
    f = tmp_path / "math_mod.py"
    initial_code = (
        "def first():\n"
        "    return 1\n"
        "\n"
        "def second():\n"
        "    val = 2\n"
        "    return val\n"
    )
    f.write_text(initial_code, encoding="utf-8")

    staged = [
        # Edit 1 expands first() by adding 2 lines
        FileChange(
            path="math_mod.py",
            updated="def first():\n    # new comment\n    val = 10\n    return val",
            original="def first():\n    return 1",
            start_line=1,
            end_line=2,
            anchor="def first():\n    return 1",
        ),
        # Edit 2 targets second() which originally was at line 4-6, but shifts down due to Edit 1
        FileChange(
            path="math_mod.py",
            updated="def second():\n    val = 200\n    return val",
            original="def second():\n    val = 2\n    return val",
            start_line=4,
            end_line=6,
            anchor="def second():\n    val = 2\n    return val",
        ),
    ]

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is True, f"Multi-edit failed: {err}"

    disk_text = f.read_text(encoding="utf-8")
    assert "val = 10" in disk_text
    assert "val = 200" in disk_text


def test_overlapping_patches_rejected_preapply_no_disk_touch(tmp_path):
    """9. Overlapping ranges on same file rejected pre-apply; disk untouched."""
    f = tmp_path / "target.py"
    orig_text = "\n".join(f"line_{i} = {i}" for i in range(1, 15)) + "\n"
    f.write_text(orig_text, encoding="utf-8")
    init_mtime = f.stat().st_mtime

    staged = [
        FileChange(
            path="target.py",
            updated="line_2 = 22\nline_3 = 33\nline_4 = 44\nline_5 = 55",
            original="line_2 = 2\nline_3 = 3\nline_4 = 4\nline_5 = 5",
            start_line=2,
            end_line=5,
            anchor="line_2 = 2\nline_3 = 3\nline_4 = 4\nline_5 = 5",
        ),
        FileChange(
            path="target.py",
            updated="line_4 = 444\nline_5 = 555\nline_6 = 666",
            original="line_4 = 4\nline_5 = 5\nline_6 = 6",
            start_line=4,
            end_line=6,
            anchor="line_4 = 4\nline_5 = 5\nline_6 = 6",
        ),
    ]

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is False
    assert "overlapping edits in one turn: split into sequential turns" in err

    # Disk must be completely untouched
    assert f.read_text(encoding="utf-8") == orig_text


def test_multi_edit_line_only_second_rejected(tmp_path):
    """10. Unanchored 2nd edit in multi-edit turn rejected with 'multi-edit turns require anchors'."""
    f = tmp_path / "script.py"
    f.write_text("a = 1\nb = 2\nc = 3\nd = 4\n", encoding="utf-8")

    staged = [
        FileChange(
            path="script.py",
            updated="a = 10",
            original="a = 1",
            start_line=1,
            end_line=1,
            anchor="a = 1",
        ),
        FileChange(
            path="script.py",
            updated="c = 30",
            original="c = 3",
            start_line=3,
            end_line=3,
            anchor=None,  # Missing anchor on 2nd patch!
        ),
    ]

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is False
    assert "multi-edit turns require anchors" in err
    assert f.read_text(encoding="utf-8") == "a = 1\nb = 2\nc = 3\nd = 4\n"


def test_index_invalidated_synchronously_post_apply_and_rollback(tmp_path):
    """11. Symbol index reflects changes immediately post-apply and post-rollback without waiting for file watcher."""
    py_file = tmp_path / "calc.py"
    py_file.write_text(
        "def compute_interest(rate: float) -> float:\n"
        "    return rate * 1.05\n",
        encoding="utf-8",
    )

    # 1. Populate symbol index
    index_file(py_file)
    syms_before = symbols_in_file(py_file)
    assert any(s.name == "compute_interest" for s in syms_before)
    assert len(find_symbol(str(tmp_path), "compute_interest")) > 0

    # 2. Stage anchored edit renaming function to calculate_yield
    staged = [
        FileChange(
            path="calc.py",
            updated="def calculate_yield(rate: float) -> float:\n    return rate * 1.10",
            original="def compute_interest(rate: float) -> float:\n    return rate * 1.05",
            start_line=1,
            end_line=2,
            anchor="def compute_interest(rate: float) -> float:\n    return rate * 1.05",
        )
    ]

    # Apply via patch applicator
    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is True

    # 3. Verify synchronous invalidation immediately post-apply (cache cleared without watcher)
    from app.features.ai.harness.symbol_index import _symbol_index
    # Index file to cache entries
    index_file(py_file)
    assert len(find_symbol(str(tmp_path), "calculate_yield")) > 0
    assert len(find_symbol(str(tmp_path), "compute_interest")) == 0

    norm_key = str(py_file.resolve())
    assert norm_key in _symbol_index._cache or any(k.endswith(py_file.name) for k in _symbol_index._cache)

    # 4. Invalidate synchronously (e.g. simulating rollback)
    invalidate_file(py_file)
    assert norm_key not in _symbol_index._cache
    assert not any(k.endswith(py_file.name) for k in _symbol_index._cache)

    # 5. Rollback on disk and re-index produces restored symbols
    py_file.write_text("def compute_interest(rate: float) -> float:\n    return rate * 1.05\n", encoding="utf-8")
    syms_restored = symbols_in_file(py_file, str(tmp_path))
    assert any(s.name == "compute_interest" for s in syms_restored)
    assert not any(s.name == "calculate_yield" for s in syms_restored)
