"""
test_phase12_5_1_followups.py - Phase 12.5.1 Surgical Edit Hardening Follow-up Gaps Tests

Validates the 5 follow-up gaps:
G1 - Minimum Anchor Size on Relocation (<40 chars AND <3 lines rejected; exact match allowed)
G2 - Relocation Surfaced in Approval Card & Re-read/Restage Flow
G3 - Context-Driven H4 Re-Eval Contract (denied tool does not earn upgrade)
G4 - Mid-Sequence Anchor Invalidation (seq_anchor_destroyed, seq_anchor_ambiguous)
G5 - Explicit 5-Branch Syntax Check Fail-Mode Contract
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.features.ai.schemas import FileChange
from app.features.ai.harness.patch_applicator import (
    apply_atomic_patch_sequence,
    MIN_ANCHOR_CHARS,
    MIN_ANCHOR_LINES,
    _is_anchor_size_ok,
)
from app.features.ai.harness.approval_coordinator import (
    PendingApproval,
    _pending_approvals,
    reread_and_restage_approval,
)
from app.features.ai.harness.content_integrity import (
    syntax_check,
    check_slice_syntax,
    check_projected_file_syntax,
    validate_language_syntax,
)


# ═══════════════════════════════════════════════════════════════════════════
# G1: Minimum Anchor Size on Relocation
# ═══════════════════════════════════════════════════════════════════════════

def test_g1_anchor_size_ok_helper():
    """Verify _is_anchor_size_ok correctly validates length or line count."""
    # Too short: 4 chars, 1 line
    ok, chars, lines = _is_anchor_size_ok("pass")
    assert not ok
    assert chars == 4
    assert lines == 1

    # >= 40 chars on 1 line: OK
    long_line = "x = compute_some_very_important_long_expression_here()"
    ok, chars, lines = _is_anchor_size_ok(long_line)
    assert ok
    assert chars >= MIN_ANCHOR_CHARS

    # >= 3 lines even if short: OK
    three_lines = "a = 1\nb = 2\nc = 3"
    ok, chars, lines = _is_anchor_size_ok(three_lines)
    assert ok
    assert lines >= MIN_ANCHOR_LINES


def test_g1_short_anchor_relocation_rejected(tmp_path: Path):
    """Short anchor ('pass', <40 chars and 1 line) rejects when lines drift."""
    target = tmp_path / "drifted.py"
    # Target file has extra lines inserted at top so lines drifted
    target.write_text("# header\n# extra 1\n# extra 2\ndef worker():\n    pass\n", encoding="utf-8")

    # Caller expects worker at line 2-3 (before extra lines were inserted)
    staged = [
        FileChange(
            path="drifted.py",
            original="    pass",
            updated="    return 42",
            start_line=2,
            end_line=3,
            anchor="    pass",
        )
    ]

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert not success
    assert "anchor_too_short" in err
    assert "anchor too short for safe relocation" in err
    assert "read_range" in err
    # Disk remains untouched
    assert "pass" in target.read_text(encoding="utf-8")


def test_g1_short_anchor_exact_match_allowed(tmp_path: Path):
    """Short anchor ('pass') succeeds if disk lines match exact range (no drift)."""
    target = tmp_path / "nodrift.py"
    target.write_text("def worker():\n    pass\n", encoding="utf-8")

    staged = [
        FileChange(
            path="nodrift.py",
            original="    pass",
            updated="    return 42",
            start_line=2,
            end_line=2,
            anchor="    pass",
        )
    ]

    success, msg, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success
    assert "return 42" in target.read_text(encoding="utf-8")


def test_g1_long_single_line_anchor_relocated(tmp_path: Path):
    """Anchor >= 40 chars on 1 line relocates successfully upon file drift."""
    target = tmp_path / "long_anchor.py"
    target.write_text("# shifted line 1\n# shifted line 2\nvalue = calculate_extremely_complex_transformation(a, b, c)\n", encoding="utf-8")

    anchor_str = "value = calculate_extremely_complex_transformation(a, b, c)"
    assert len(anchor_str) >= MIN_ANCHOR_CHARS

    staged = [
        FileChange(
            path="long_anchor.py",
            original=anchor_str,
            updated="value = calculate_optimized_transformation(a, b, c)",
            start_line=1,
            end_line=1,
            anchor=anchor_str,
        )
    ]

    success, msg, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success
    assert "calculate_optimized_transformation" in target.read_text(encoding="utf-8")


def test_g1_three_line_short_anchor_relocated(tmp_path: Path):
    """Anchor with 3 lines (even if each is short) relocates successfully upon drift."""
    target = tmp_path / "multi_line.py"
    target.write_text("# header\n# drift\na = 1\nb = 2\nc = 3\n", encoding="utf-8")

    anchor_str = "a = 1\nb = 2\nc = 3"
    staged = [
        FileChange(
            path="multi_line.py",
            original=anchor_str,
            updated="a = 10\nb = 20\nc = 30",
            start_line=1,
            end_line=3,
            anchor=anchor_str,
        )
    ]

    success, msg, touched = apply_atomic_patch_sequence(str(tmp_path), staged)
    assert success
    content = target.read_text(encoding="utf-8")
    assert "a = 10" in content
    assert "c = 30" in content


# ═══════════════════════════════════════════════════════════════════════════
# G2: Relocation Surfaced in Approval Card & Re-read Flow
# ═══════════════════════════════════════════════════════════════════════════

def test_g2_relocation_event_recorded_on_file_change(tmp_path: Path):
    """Relocation records structured relocation_event on FileChange."""
    target = tmp_path / "reloc.py"
    target.write_text("# line 1\n# line 2\n# line 3\n# line 4\nresult = execute_heavy_computation_on_dataset(d)\n", encoding="utf-8")

    anchor_str = "result = execute_heavy_computation_on_dataset(d)"
    staged = [
        FileChange(
            path="reloc.py",
            original=anchor_str,
            updated="result = fast_computation(d)",
            start_line=1,
            end_line=1,
            anchor=anchor_str,
        )
    ]

    success, msg, touched = apply_atomic_patch_sequence(str(tmp_path), staged, staged_changes=staged)
    assert success
    assert staged[0].relocation_event is not None
    assert staged[0].relocation_event["relocated"] is True
    assert staged[0].relocation_event["old_range"] == [1, 1]
    assert staged[0].relocation_event["new_range"] == [5, 5]
    assert "File drifted" in staged[0].relocation_event["reason_text"]


@pytest.mark.asyncio
async def test_g2_reread_and_restage_approval(tmp_path: Path):
    """reread_and_restage_approval invalidates old card and returns fresh non-auto-approving card."""
    target = tmp_path / "service.py"
    target.write_text("def run():\n    # step 1\n    # step 2\n    return 'done'\n", encoding="utf-8")

    action_id = "act-test-old-123"
    old_pending = PendingApproval(
        action_id=action_id,
        action_type="edit",
        detail="lines 1-2 of service.py",
        reason="Rony Agent wants to edit service.py",
        workspace=str(tmp_path),
        path="service.py",
        metadata={
            "start_line": 1,
            "end_line": 2,
            "relocation_event": {
                "relocated": True,
                "old_range": [1, 2],
                "new_range": [3, 4],
            },
        },
    )
    _pending_approvals[action_id] = old_pending

    res = await reread_and_restage_approval(action_id)
    assert res is not None
    assert res["status"] == "restaged"
    assert res["old_action_id"] == action_id
    new_action_id = res["new_action_id"]
    assert new_action_id != action_id

    # Old card invalidated and popped
    assert action_id not in _pending_approvals
    assert old_pending.replaced_by == new_action_id
    assert old_pending.event.is_set()

    # New card registered with approved=False (requires fresh user confirmation)
    assert new_action_id in _pending_approvals
    new_pending = _pending_approvals[new_action_id]
    assert not new_pending.approved
    assert new_pending.relocation_event["relocated"] is False
    assert new_pending.metadata["start_line"] == 3
    assert new_pending.metadata["end_line"] == 4
    assert new_pending.metadata["anchor_state"] == "anchored"

    # Cleanup
    _pending_approvals.pop(new_action_id, None)


# ═══════════════════════════════════════════════════════════════════════════
# G3: Context-Driven H4 Re-Eval Contract
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_g3_denied_tool_request_does_not_earn_upgrade():
    """Trivial prompt calling denied tool does NOT get auto-upgraded to Tier 2."""
    from app.features.ai.harness.plan_parser import _classify_task_effort

    # Requesting a tool does NOT earn it: user prompt is a simple greeting
    user_query = "hi there, what time is it?"
    re_tier, label, _ = _classify_task_effort(user_query=user_query, attached_paths=[])
    assert re_tier == 0 or re_tier == 1
    assert re_tier < 2


@pytest.mark.asyncio
async def test_g3_denied_tool_context_driven_upgrade():
    """Complex multi-file architectural query naturally earns Tier 2+ based on context."""
    from app.features.ai.harness.plan_parser import _classify_task_effort

    complex_query = "Refactor the database migrations across auth, billing, and storage modules and migrate to async engine."
    re_tier, label, _ = _classify_task_effort(
        user_query=complex_query,
        attached_paths=["auth.py", "billing.py", "storage.py"],
    )
    assert re_tier >= 2


# ═══════════════════════════════════════════════════════════════════════════
# G4: Mid-Sequence Anchor Invalidation Pre-Scan
# ═══════════════════════════════════════════════════════════════════════════

def test_g4_seq_anchor_destroyed_pre_apply_rejected(tmp_path: Path):
    """Patch 1 overwrites Patch 2's anchor (matches change 1 -> 0); rejected with seq_anchor_destroyed."""
    target = tmp_path / "seq_dest.py"
    target.write_text("line 1\ntarget_anchor_b = 'important block'\nline 3\n", encoding="utf-8")

    anchor_b = "target_anchor_b = 'important block'"

    # Turn with 2 patches:
    # Patch 1 replaces lines 1-3 with new code that completely erases anchor_b
    # Patch 2 targets anchor_b
    patches = [
        {
            "path": "seq_dest.py",
            "start_line": 1,
            "end_line": 3,
            "original": target.read_text(encoding="utf-8"),
            "updated": "line 1_modified\ncompletely_new_content\n",
            "anchor": target.read_text(encoding="utf-8"),
        },
        {
            "path": "seq_dest.py",
            "start_line": 2,
            "end_line": 2,
            "original": anchor_b,
            "updated": "target_anchor_b = 'updated'",
            "anchor": anchor_b,
        },
    ]

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), patches)
    assert not success
    assert "seq_anchor_destroyed" in err
    assert "subsequent patch anchor would be destroyed" in err
    # Zero disk writes
    assert "target_anchor_b = 'important block'" in target.read_text(encoding="utf-8")


def test_g4_seq_anchor_ambiguous_pre_apply_rejected(tmp_path: Path):
    """Patch 1 duplicates text matching Patch 2's anchor (matches 1 -> 2); rejected with seq_anchor_ambiguous."""
    target = tmp_path / "seq_ambig.py"
    target.write_text("alpha = 1\nbeta_unique_anchor = 2\ngamma = 3\n", encoding="utf-8")

    anchor_b = "beta_unique_anchor = 2"

    # Patch 1 inserts a second copy of anchor_b into the file
    patches = [
        {
            "path": "seq_ambig.py",
            "start_line": 1,
            "end_line": 1,
            "original": "alpha = 1",
            "updated": "alpha = 1\nbeta_unique_anchor = 2",
            "anchor": "alpha = 1",
        },
        {
            "path": "seq_ambig.py",
            "start_line": 2,
            "end_line": 2,
            "original": anchor_b,
            "updated": "beta_unique_anchor = 42",
            "anchor": anchor_b,
        },
    ]

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), patches)
    assert not success
    assert "seq_anchor_ambiguous" in err
    assert "subsequent patch would become ambiguous" in err
    # Zero disk writes
    assert target.read_text(encoding="utf-8") == "alpha = 1\nbeta_unique_anchor = 2\ngamma = 3\n"


def test_g4_safe_multi_edit_sequence_applies(tmp_path: Path):
    """Multi-edit turn where Patch 1 leaves Patch 2's anchor intact applies successfully."""
    target = tmp_path / "seq_safe.py"
    target.write_text("first_block = 1\nmiddle = 2\nsecond_block = 3\n", encoding="utf-8")

    patches = [
        {
            "path": "seq_safe.py",
            "start_line": 1,
            "end_line": 1,
            "original": "first_block = 1",
            "updated": "first_block = 10",
            "anchor": "first_block = 1",
        },
        {
            "path": "seq_safe.py",
            "start_line": 3,
            "end_line": 3,
            "original": "second_block = 3",
            "updated": "second_block = 30",
            "anchor": "second_block = 3",
        },
    ]

    success, msg, touched = apply_atomic_patch_sequence(str(tmp_path), patches)
    assert success
    content = target.read_text(encoding="utf-8")
    assert "first_block = 10" in content
    assert "second_block = 30" in content


# ═══════════════════════════════════════════════════════════════════════════
# G5: Explicit 5-Branch Syntax Check Fail-Mode Contract
# ═══════════════════════════════════════════════════════════════════════════

def test_g5_syntax_branch1_fail_closed_on_new_break(capsys):
    """Branch 1: Recognized code + available checker + newly broken -> FAIL-CLOSED."""
    broken_py = "def broken(:\n    pass\n"
    ok, err = syntax_check("py", broken_py)
    assert not ok
    assert "Python syntax error" in err or "parse error" in err


def test_g5_syntax_branch2_preexisting_broken_allowed(capsys):
    """Branch 2: Pre-existing broken file edited without worsening is allowed."""
    orig_broken = "def syntax_err(\n    return 1\n"
    upd_still_broken = "def syntax_err(\n    return 2\n"

    ok, err = syntax_check("py", upd_still_broken, original_source=orig_broken)
    assert ok
    assert "already broken pre-patch" in err
    captured = capsys.readouterr()
    assert "[SYNTAX_PREEXISTING_BROKEN]" in captured.out


def test_g5_syntax_branch3_unavailable_checker_fail_open(capsys):
    """Branch 3: Recognized code extension with unavailable checker -> FAIL-OPEN ([SYNTAX_SKIP])."""
    go_code = "package main\nfunc main() {}\n"
    ok, err = syntax_check("go", go_code)
    assert ok
    assert err == "syntax: unchecked"
    captured = capsys.readouterr()
    assert "[SYNTAX_SKIP] ext=go" in captured.out


def test_g5_syntax_branch4_non_code_fail_open(capsys):
    """Branch 4: Non-code extension (.md, .txt, .yaml, .toml) -> FAIL-OPEN ([SYNTAX_SKIPPED_NONCODE])."""
    md_content = "# Title\nThis is plain markdown with unmatched { brackets."
    ok, err = syntax_check(".md", md_content)
    assert ok
    captured = capsys.readouterr()
    assert "[SYNTAX_SKIPPED_NONCODE] ext=md" in captured.out


def test_g5_syntax_branch5_internal_error_fail_open(capsys):
    """Branch 5: Unexpected internal exception inside checker -> FAIL-OPEN ([SYNTAX_INTERNAL_ERROR])."""
    with patch("ast.parse", side_effect=RuntimeError("ast parser crashed")):
        ok, err = syntax_check("py", "x = 1\n")
        assert ok
        assert "syntax: internal error" in err
        captured = capsys.readouterr()
        assert "[SYNTAX_INTERNAL_ERROR] ext=py" in captured.out


# ═══════════════════════════════════════════════════════════════════════════
# V2.5: Denied Tool Arguments Never Passed To Classifier
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_denied_tool_args_not_fed_to_classifier(tmp_path):
    """V2.5: Denied-tool path calls _classify_task_effort with turn context only (NO tool name/args)."""
    from unittest.mock import MagicMock, patch
    from app.features.ai.chat_harness import ChatAgentRequest, run_chat_agent
    from app.features.ai.providers.base import ProviderStreamEvent

    captured_kwargs = []

    def mock_classify(*args, **kwargs):
        captured_kwargs.append((args, kwargs))
        return (1, "Quick Task", "gemini-2.5-flash")

    tool_call_chunk = (
        "[TOOL_CALL]\n"
        '{"name": "edit_range", "arguments": {"path": "foo.py", "start_line": 1, "end_line": 5, "updated": "secret_arg_value"}}\n'
        "[/TOOL_CALL]\n\n"
        "[DONE]\n"
    )

    async def mock_stream(*args, **kwargs):
        yield tool_call_chunk

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(return_value=mock_stream())

    req = ChatAgentRequest(
        messages=[{"role": "user", "content": "say hi"}],
        workspace=str(tmp_path),
        model="gemini-2.5-flash",
        provider="mock",
    )

    from unittest.mock import AsyncMock
    with patch("app.features.ai.chat_harness._classify_task_effort", side_effect=mock_classify) as mock_cls, \
         patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):

        async for sse in run_chat_agent(req):
            if "tool_denied" in sse or "escalation" in sse:
                break

        assert len(captured_kwargs) >= 1
        for args, kwargs in captured_kwargs:
            user_q = kwargs.get("user_query", "") or (args[0] if args else "")
            assert "edit_range" not in str(user_q)
            assert "secret_arg_value" not in str(user_q)
            assert "foo.py" not in str(user_q)
            assert "edit_range" not in str(args)
            assert "secret_arg_value" not in str(args)
            assert "secret_arg_value" not in str(kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# V3: Multi-Patch Chain Propagation (A -> B -> C)
# ═══════════════════════════════════════════════════════════════════════════

def test_three_patch_chain_anchor_propagation(tmp_path: Path):
    """V3.2: 3-patch chain (A->B->C): A inserts text X, B depends on anchor Y, C depends on anchor Z (which B duplicates)."""
    target = tmp_path / "chain.py"
    initial_code = (
        "# header\n"
        "anchor_y = 'anchor_y_original_text'\n"
        "middle = 1\n"
        "anchor_z = 'anchor_z_unique_before_b'\n"
        "# footer\n"
    )
    target.write_text(initial_code, encoding="utf-8")

    # Patch A inserts text X above anchor_y
    # Patch B targets anchor_y and its updated code introduces a duplicate of anchor_z
    # Patch C targets anchor_z (which is unique in initial text, but made ambiguous by B)
    patches = [
        {
            "path": "chain.py",
            "start_line": 1,
            "end_line": 1,
            "original": "# header",
            "updated": "# header\ntext_x_inserted = True",
            "anchor": "# header",
        },
        {
            "path": "chain.py",
            "start_line": 2,
            "end_line": 2,
            "original": "anchor_y = 'anchor_y_original_text'",
            "updated": "anchor_y = 'updated'\nanchor_z = 'anchor_z_unique_before_b'",
            "anchor": "anchor_y = 'anchor_y_original_text'",
        },
        {
            "path": "chain.py",
            "start_line": 4,
            "end_line": 4,
            "original": "anchor_z = 'anchor_z_unique_before_b'",
            "updated": "anchor_z = 'final_updated'",
            "anchor": "anchor_z = 'anchor_z_unique_before_b'",
        },
    ]

    success, err, touched = apply_atomic_patch_sequence(str(tmp_path), patches)
    assert success is False
    assert "seq_anchor_ambiguous" in err
    assert "subsequent patch would become ambiguous" in err
    # Zero disk writes
    assert target.read_text(encoding="utf-8") == initial_code


# ═══════════════════════════════════════════════════════════════════════════
# V5: Harder Pre-Existing Breakage Cases
# ═══════════════════════════════════════════════════════════════════════════

def test_syntax_preexisting_one_error_fixed_another_remains():
    """V5.1: File has errors at line 2 AND line 6. Patch fixes line 2 but leaves line 6 broken -> ALLOW."""
    orig_code = (
        "def error_one():\n"
        "    if True\n"
        "        pass\n"
        "\n"
        "def error_two():\n"
        "    if False\n"
        "        pass\n"
    )
    patched_code = (
        "def error_one():\n"
        "    if True:\n"
        "        pass\n"
        "\n"
        "def error_two():\n"
        "    if False\n"
        "        pass\n"
    )
    ok, msg = syntax_check("py", patched_code, original_source=orig_code)
    assert ok is True
    assert "already broken pre-patch" in msg


def test_syntax_preexisting_error_swapped_for_different_error():
    """V5.1: Swapping error E1 for E2 (same count=1) -> ALLOW. Introducing extra error (count 1->2) -> REJECT."""
    orig_code = (
        "def error_one():\n"
        "    if True\n"
        "        pass\n"
        "\n"
        "def clean_func():\n"
        "    return 42\n"
    )
    swapped_code = (
        "def error_one():\n"
        "    if True:\n"
        "        pass\n"
        "\n"
        "def clean_func():\n"
        "    if False\n"
        "        return 42\n"
    )
    ok_swap, msg_swap = syntax_check("py", swapped_code, original_source=orig_code)
    assert ok_swap is True
    assert "already broken pre-patch" in msg_swap

    worsened_code = (
        "def error_one():\n"
        "    if True\n"
        "        pass\n"
        "\n"
        "def clean_func():\n"
        "    if False\n"
        "        return 42\n"
    )
    ok_worse, msg_worse = syntax_check("py", worsened_code, original_source=orig_code)
    assert ok_worse is False
    assert "Syntax worsened" in msg_worse or "Python syntax error" in msg_worse


# ═══════════════════════════════════════════════════════════════════════════
# V6: Re-Read Non-Auto-Approve Assertion
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reread_never_auto_approves(tmp_path: Path):
    """V6.3: reread_and_restage_approval yields fresh PendingApproval with status='pending' and approved=False."""
    f = tmp_path / "module.py"
    f.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")

    action_id = "act-test-v6"
    old_pending = PendingApproval(
        action_id=action_id,
        action_type="edit",
        detail="lines 1-2 of module.py",
        reason="Test",
        workspace=str(tmp_path),
        path="module.py",
        approved=False,
        status="pending",
        metadata={
            "start_line": 1,
            "end_line": 2,
            "relocation_event": {
                "relocated": True,
                "old_range": [1, 2],
                "new_range": [2, 3],
            },
        },
    )
    _pending_approvals[action_id] = old_pending

    res = await reread_and_restage_approval(action_id)
    assert res is not None
    assert res["status"] == "restaged"
    new_aid = res["new_action_id"]

    # (a) Old approval invalidated
    assert old_pending.status == "invalidated"
    assert old_pending.replaced_by == new_aid
    assert old_pending.approved is False
    assert action_id not in _pending_approvals

    # (b) & (c) New approval is pending and NOT approved
    assert new_aid in _pending_approvals
    new_pending = _pending_approvals[new_aid]
    assert new_pending.status == "pending"
    assert new_pending.approved is False
    assert new_pending.metadata["status"] == "pending"
    assert not new_pending.event.is_set()

    # Cleanup
    _pending_approvals.pop(new_aid, None)

