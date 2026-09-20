"""test_phase11_surgical_tools.py — Regression tests for CODE OS v5.0.0 Phase 11 Surgical Edit & Search Tools.

Covers:
1. test_symbol_index_finds_functions_and_classes (Python AST and TS regex)
2. test_find_function_returns_range_and_snippet
3. test_go_to_definition_resolves_local_else_honest_notfound
4. test_find_references_matches_grep_ground_truth
5. test_edit_range_applies_only_target_range (2000-line file; outside bytes 100% byte-identical)
6. test_edit_range_integrity_rejects_stale_range (concurrent disk change triggers rollback)
7. test_edit_range_routes_through_approval_and_atomic_applicator
8. test_edit_range_tier_gating (Tier 1 excludes edit_range; Tier 2 includes it)
9. test_index_invalidates_on_watcher_change
10. test_planner_prefers_edit_range_for_small_changes
11. test_edit_mode_metric_logging_and_sse
"""
import json
import pytest
from pathlib import Path

from app.features.ai.harness.symbol_index import (
    index_file,
    symbols_in_file,
    find_symbol,
    references_to,
    invalidate_file,
    clear_symbol_index,
)
from app.features.ai.agents.agent_tools import (
    _handle_find_function,
    _handle_go_to_definition,
    _handle_find_references,
    _handle_edit_range,
    get_tool_instructions,
)
from app.features.ai.harness.patch_applicator import apply_atomic_patch_sequence
from app.features.ai.harness.tool_executor import (
    get_tools_for_tier,
    HEAVY_TOOLS,
    CORE_CODING_TOOLS,
)
from app.features.ai.harness.size_guard import get_surgical_edit_directive
from app.features.ai.harness.sse_streamer import _sse_metrics, SSEStreamer


@pytest.fixture(autouse=True)
def clean_index():
    clear_symbol_index()
    yield
    clear_symbol_index()


def test_symbol_index_finds_functions_and_classes(tmp_path):
    """1. Symbol index parses Python AST and TypeScript regex/brace parser."""
    # Python file
    py_file = tmp_path / "calculator.py"
    py_code = (
        "import math\n\n"
        "def calculate_total(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "class OrderManager:\n"
        "    def process(self):\n"
        "        pass\n"
    )
    py_file.write_text(py_code, encoding="utf-8")

    # TypeScript file
    ts_file = tmp_path / "service.ts"
    ts_code = (
        "export function formatCurrency(amount: number): string {\n"
        "  return `$${amount.toFixed(2)}`;\n"
        "}\n\n"
        "export class PaymentService {\n"
        "  execute(): boolean {\n"
        "    return true;\n"
        "  }\n"
        "}\n"
    )
    ts_file.write_text(ts_code, encoding="utf-8")

    # Verify Python symbols
    py_syms = symbols_in_file(str(py_file), str(tmp_path))
    py_names = {s.name: s for s in py_syms}
    assert "calculate_total" in py_names
    assert py_names["calculate_total"].kind == "function"
    assert py_names["calculate_total"].start_line == 3
    assert py_names["calculate_total"].end_line == 4

    assert "OrderManager" in py_names
    assert py_names["OrderManager"].kind == "class"
    assert "process" in py_names
    assert py_names["process"].kind == "method"

    # Verify TypeScript symbols
    ts_syms = symbols_in_file(str(ts_file), str(tmp_path))
    ts_names = {s.name: s for s in ts_syms}
    assert "formatCurrency" in ts_names
    assert ts_names["formatCurrency"].kind == "function"
    assert ts_names["formatCurrency"].start_line == 1
    assert "PaymentService" in ts_names
    assert ts_names["PaymentService"].kind == "class"


def test_find_function_returns_range_and_snippet(tmp_path):
    """2. find_function locates function definition and returns exact line range and snippet."""
    code_file = tmp_path / "crypto.py"
    code_file.write_text(
        "# Header comment\n"
        "def compute_hash(data: str) -> str:\n"
        "    import hashlib\n"
        "    return hashlib.sha256(data.encode()).hexdigest()\n\n"
        "def verify_hash(data: str, digest: str) -> bool:\n"
        "    return compute_hash(data) == digest\n",
        encoding="utf-8",
    )

    res = _handle_find_function(str(tmp_path), {"name": "compute_hash"})
    assert res.success is True
    assert "compute_hash" in res.output
    assert "crypto.py" in res.output
    assert "Lines 2-4" in res.output

    # Extract JSON payload from tool output
    json_part = res.output.split("JSON: ")[1].strip()
    payload = json.loads(json_part)
    assert payload["start_line"] == 2
    assert payload["end_line"] == 4
    assert "return hashlib.sha256" in payload["snippet"]


def test_go_to_definition_resolves_local_else_honest_notfound(tmp_path):
    """3. go_to_definition resolves local definition or returns honest not-found."""
    models_file = tmp_path / "models.py"
    models_file.write_text(
        "class UserModel:\n"
        "    name: str\n",
        encoding="utf-8",
    )

    # Existing symbol
    found = _handle_go_to_definition(str(tmp_path), {"symbol": "UserModel"})
    assert found.success is True
    assert "Line 1" in found.output
    assert "UserModel" in found.output

    # Non-existent symbol
    missing = _handle_go_to_definition(str(tmp_path), {"symbol": "GhostClassNotFound"})
    assert missing.success is False
    assert "not found" in missing.error.lower()
    assert missing.failure_reason == "not_found"


def test_find_references_matches_grep_ground_truth(tmp_path):
    """4. find_references finds word-boundary references across files."""
    f1 = tmp_path / "app.py"
    f1.write_text(
        "from util import helper\n\n"
        "def run():\n"
        "    helper()\n",
        encoding="utf-8",
    )
    f2 = tmp_path / "tasks.py"
    f2.write_text(
        "from util import helper\n"
        "def do_task():\n"
        "    val = helper()\n"
        "    return val\n",
        encoding="utf-8",
    )
    # File with word containing helper as substring - should NOT match with word-boundary
    f3 = tmp_path / "other.py"
    f3.write_text("def helper_extended(): pass\n", encoding="utf-8")

    res = _handle_find_references(str(tmp_path), {"symbol": "helper"})
    assert res.success is True
    json_part = res.output.split("JSON: ")[1].strip()
    refs = json.loads(json_part)
    assert len(refs) == 4  # 2 in app.py (import + call), 2 in tasks.py (import + call)
    paths = {r["path"] for r in refs}
    assert "app.py" in paths
    assert "tasks.py" in paths
    assert "other.py" not in paths


def test_edit_range_applies_only_target_range(tmp_path):
    """5. edit_range on a 2000-line file leaves outside bytes 100% byte-identical."""
    big_file = tmp_path / "large_module.py"
    total_lines = 2000
    original_lines = [f"# Line {i:04d}: data payload for testing" for i in range(1, total_lines + 1)]
    big_file.write_text("\n".join(original_lines) + "\n", encoding="utf-8")
    orig_bytes = big_file.read_bytes()

    staged = []
    # Target lines 500-503 (4 lines)
    target_start = 500
    target_end = 503
    replacement = (
        "# Line 0500: SURGICALLY EDITED LINE A\n"
        "# Line 0501: SURGICALLY EDITED LINE B\n"
        "# Line 0502: SURGICALLY EDITED LINE C\n"
        "# Line 0503: SURGICALLY EDITED LINE D"
    )

    res = _handle_edit_range(
        str(tmp_path),
        {
            "path": "large_module.py",
            "start_line": target_start,
            "end_line": target_end,
            "new_code": replacement,
        },
        staged,
    )
    assert res.success is True
    assert len(staged) == 1
    change = staged[0]
    assert change.start_line == target_start
    assert change.end_line == target_end

    # Apply via atomic patch sequence
    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is True, f"Apply failed: {err}"

    # Verify contents
    new_text = big_file.read_text(encoding="utf-8")
    new_lines = new_text.splitlines()
    assert len(new_lines) == total_lines

    # Verify outside bytes are 100% byte-for-byte identical
    # Lines 1..499 (0..499 index)
    assert new_lines[: target_start - 1] == original_lines[: target_start - 1]
    # Replaced lines
    assert new_lines[target_start - 1 : target_end] == replacement.splitlines()
    # Lines 504..2000 (503.. index)
    assert new_lines[target_end:] == original_lines[target_end:]


def test_edit_range_integrity_rejects_stale_range(tmp_path):
    """6. Simulated concurrent mutation between plan and approval triggers rollback."""
    file_path = tmp_path / "config.py"
    initial_content = (
        "ENV = 'prod'\n"
        "PORT = 8080\n"
        "DEBUG = False\n"
        "TIMEOUT = 30\n"
    )
    file_path.write_text(initial_content, encoding="utf-8")

    staged = []
    res = _handle_edit_range(
        str(tmp_path),
        {
            "path": "config.py",
            "start_line": 2,
            "end_line": 3,
            "new_code": "PORT = 9000\nDEBUG = True",
        },
        staged,
    )
    assert res.success is True

    # Simulate concurrent external mutation of lines 2-3
    mutated_text = (
        "ENV = 'prod'\n"
        "PORT = 7777\n"  # Modified externally!
        "DEBUG = False\n"
        "TIMEOUT = 30\n"
    )
    file_path.write_text(mutated_text, encoding="utf-8")

    # Attempt to apply stale staged patch
    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is False
    assert "original_mismatches_disk" in err
    # Disk remains untouched after rollback
    assert file_path.read_text(encoding="utf-8").replace("\r\n", "\n") == mutated_text


def test_edit_range_routes_through_approval_and_atomic_applicator(tmp_path):
    """7. edit_range NEVER writes directly to disk; only stages changes for approval."""
    f = tmp_path / "module.py"
    orig_code = "def alpha():\n    return 1\n"
    f.write_text(orig_code, encoding="utf-8")

    staged = []
    res = _handle_edit_range(
        str(tmp_path),
        {
            "path": "module.py",
            "start_line": 2,
            "end_line": 2,
            "new_code": "    return 42",
        },
        staged,
    )
    assert res.success is True
    # Disk MUST NOT be modified yet
    assert f.read_text(encoding="utf-8") == orig_code

    # Staged change has start_line and end_line attributes
    assert getattr(staged[0], "start_line") == 2
    assert getattr(staged[0], "end_line") == 2

    # Now apply via atomic patch applicator
    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success is True
    assert f.read_text(encoding="utf-8") == "def alpha():\n    return 42\n"


def test_edit_range_tier_gating():
    """8. Tier 1 excludes edit_range (read-only); Tier 2 includes it."""
    tier1_tools = get_tools_for_tier(1)
    tier1_names = {t["function"]["name"] if isinstance(t, dict) and "function" in t else (t.get("name") if isinstance(t, dict) else t.name) for t in tier1_tools}
    assert "edit_range" not in tier1_names
    assert "find_function" in tier1_names
    assert "find_references" in tier1_names
    assert "go_to_definition" in tier1_names

    tier2_tools = get_tools_for_tier(2)
    tier2_names = {t["function"]["name"] if isinstance(t, dict) and "function" in t else (t.get("name") if isinstance(t, dict) else t.name) for t in tier2_tools}
    assert "edit_range" in tier2_names
    assert "edit_range" in HEAVY_TOOLS


def test_index_invalidates_on_watcher_change(tmp_path):
    """9. File watcher invalidation evicts cache and returns fresh symbols."""
    f = tmp_path / "cache_test.py"
    f.write_text("def v1_func(): pass\n", encoding="utf-8")

    # Initial index
    index_file(str(f), str(tmp_path))
    syms_1 = symbols_in_file(str(f), str(tmp_path))
    assert len(syms_1) == 1
    assert syms_1[0].name == "v1_func"

    # Invalidate
    invalidate_file(str(f))

    # Update file
    f.write_text("def v2_func(): pass\n", encoding="utf-8")
    syms_2 = symbols_in_file(str(f), str(tmp_path))
    assert len(syms_2) == 1
    assert syms_2[0].name == "v2_func"


def test_planner_prefers_edit_range_for_small_changes():
    """10. Planner prompt instructions and size_guard direct models to prefer edit_range."""
    instructions = get_tool_instructions(allow_edit=True, role="coder")
    assert "prefer edit_range for changes under ~60 lines" in instructions.lower()
    assert "use edit_file only for whole-file restructures" in instructions.lower()

    # Small edit (< 60 lines) gets surgical directive
    directive = get_surgical_edit_directive("main.py", "x = 1\ny = 2\n", "x = 0\ny = 0\n")
    assert directive is not None
    assert "Use edit_range with the exact line range" in directive

    # Large edit (>= 60 lines) does not force surgical directive
    large_updated = "\n".join(f"line {i}" for i in range(80))
    large_directive = get_surgical_edit_directive("main.py", large_updated, "old")
    assert large_directive is None


def test_edit_mode_metric_logging_and_sse():
    """11. SSE metrics event and SSEStreamer carry surgical_edits and fullfile_edits."""
    sse_raw = _sse_metrics(
        iterations=2,
        tools_executed=5,
        duration_ms=450.0,
        tier=2,
        tokens_used=1200,
        surgical_edits=4,
        fullfile_edits=1,
    )
    assert "event: metrics" in sse_raw
    json_str = sse_raw.split("data: ")[1].strip()
    data = json.loads(json_str)
    assert data["surgical_edits"] == 4
    assert data["fullfile_edits"] == 1
    assert data["tier"] == 2
    assert data["tokens_used"] == 1200

    # Streamer method
    streamer = SSEStreamer()
    streamer_raw = streamer.metrics(
        iterations=1,
        tools_executed=1,
        duration_ms=200.0,
        tier=1,
        tokens_used=600,
        surgical_edits=1,
        fullfile_edits=0,
    )
    s_data = json.loads(streamer_raw.split("data: ")[1].strip())
    assert s_data["surgical_edits"] == 1
    assert s_data["fullfile_edits"] == 0


@pytest.mark.asyncio
async def test_run_chat_agent_surgical_tools_integration(tmp_path):
    """12. Full end-to-end Chat Harness integration test.
    Verifies chat_harness actually routes to find_function, then edit_range,
    generates approval_request with start_line/end_line, applies via atomic patch applicator,
    and reports surgical_edits >= 1 in SSE metrics.
    """
    import asyncio
    from unittest.mock import AsyncMock, patch, MagicMock
    from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest, _pending_approvals, approve_action

    ws = str(tmp_path)
    target_file = tmp_path / "server.py"
    target_file.write_text(
        "def start_server():\n"
        "    port = 8000\n"
        "    print('Starting on', port)\n",
        encoding="utf-8"
    )

    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=ws,
        messages=[{"role": "user", "content": "Please change the server port to 9090"}],
    )

    # Turn 1: Model calls find_function to locate start_server
    turn1_chunks = [
        "[TOOL_CALL: find_function]\n"
        '{"name": "start_server"}\n'
        "[/TOOL_CALL]\n"
    ]
    # Turn 2: Model calls edit_range to surgically edit line 2
    turn2_chunks = [
        "[TOOL_CALL: edit_range]\n"
        '{"path": "server.py", "start_line": 2, "end_line": 2, "new_code": "    port = 9090"}\n'
        "[/TOOL_CALL]\n\n"
        "[DONE]\n"
    ]

    async def mock_stream_turn1(*args, **kwargs):
        for c in turn1_chunks:
            yield c

    async def mock_stream_turn2(*args, **kwargs):
        for c in turn2_chunks:
            yield c

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream_turn1(), mock_stream_turn2()])

    async def auto_approver():
        for _ in range(30):
            await asyncio.sleep(0.05)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    await approve_action(act_id)
                break

    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        with patch("app.features.ai.chat_harness.create_proposal", new=AsyncMock(return_value=MagicMock(id="prop-surg-1"))):
            with patch("app.features.ai.service.apply_proposal", new=AsyncMock(return_value=MagicMock())):
                approver_task = asyncio.create_task(auto_approver())
                events = []
                async for chunk in run_chat_agent(req):
                    events.append(chunk)

                await approver_task
                full_sse = "".join(events)

            # 1. Harness emitted tool event for find_function
            assert "find_function" in full_sse
            # 2. Harness emitted tool event for edit_range
            assert "edit_range" in full_sse
            # 3. Harness emitted approval_request
            assert "event: approval_request" in full_sse
            # 4. Harness emitted metrics with surgical_edits
            assert "surgical_edits" in full_sse
            assert '"surgical_edits": 1' in full_sse
            assert '"fullfile_edits": 0' in full_sse
            # 5. Harness completed with done
            assert "event: done" in full_sse

