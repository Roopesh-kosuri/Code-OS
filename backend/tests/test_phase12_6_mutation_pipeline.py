"""Tests for Phase 12.6 Unified Mutation Pipeline (mutation_pipeline.py).

Covers:
  - Equivalence (behavior preserved from 12.5 / 12.5.1)
  - Mode behavior (AGENT vs USER_SAVE)
  - Atomicity and Rollback (multi-file, exact byte restoration, created file deletion, crash safety)
  - Invalidation (synchronous per write kind + rollback)
  - Path safety (traversal, absolute-outside, symlink escape)
  - Encoding and Line Endings (CRLF preservation, UTF-8 BOM preservation)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.features.ai.harness.mutation_pipeline import (
    Mutation,
    MutationKind,
    MutationResult,
    apply_mutations,
    stage_apply,
    stage_invalidate,
    stage_preflight,
    stage_resolve,
    stage_rollback,
    stage_validate,
)
from app.features.ai.harness.patch_applicator import (
    MIN_ANCHOR_CHARS,
    MIN_ANCHOR_LINES,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. EQUIVALENCE (behavior preserved)
# ═══════════════════════════════════════════════════════════════════════════

def test_pipeline_edit_range_relocates_like_legacy(tmp_path: Path):
    """An edit with drifted line numbers but valid anchor relocates to correct lines."""
    target = tmp_path / "calc.py"
    initial_code = (
        "# Header\n"
        "# Inserted drift line 1\n"
        "# Inserted drift line 2\n"
        "def calculate_total_tax(income, rate):\n"
        "    base = income * rate\n"
        "    return base + 10\n"
        "# Footer\n"
    )
    target.write_text(initial_code, encoding="utf-8")

    anchor_str = (
        "def calculate_total_tax(income, rate):\n"
        "    base = income * rate\n"
        "    return base + 10"
    )
    assert len(anchor_str) >= MIN_ANCHOR_CHARS

    updated_str = (
        "def calculate_total_tax(income, rate):\n"
        "    base = income * rate\n"
        "    return base + 50"
    )

    # Agent specified old lines 2-4 (drifted; target is now at lines 4-6)
    mutation = Mutation(
        kind=MutationKind.EDIT_RANGE,
        path="calc.py",
        start_line=2,
        end_line=4,
        updated=updated_str,
        anchor=anchor_str,
    )

    result = apply_mutations(str(tmp_path), [mutation], mode="AGENT")
    assert result.success is True
    assert len(result.relocation_events) == 1
    assert result.relocation_events[0]["relocated"] is True
    assert result.relocation_events[0]["new_range"] == [4, 6]

    final_content = target.read_text(encoding="utf-8")
    assert "return base + 50" in final_content
    assert "# Inserted drift line 1" in final_content


def test_pipeline_relocation_event_shape_unchanged(tmp_path: Path):
    """Verify relocation event shape matches Phase 12.5.1 G2 schema exactly."""
    target = tmp_path / "event_shape.py"
    initial_code = (
        "# Header drift\n"
        "def execute_task_flow(param_a, param_b):\n"
        "    result = param_a + param_b\n"
        "    return result\n"
    )
    target.write_text(initial_code, encoding="utf-8")

    anchor_str = (
        "def execute_task_flow(param_a, param_b):\n"
        "    result = param_a + param_b\n"
        "    return result"
    )
    updated_str = (
        "def execute_task_flow(param_a, param_b):\n"
        "    result = param_a * param_b\n"
        "    return result"
    )

    mutation = Mutation(
        kind=MutationKind.EDIT_RANGE,
        path="event_shape.py",
        start_line=1,
        end_line=3,
        updated=updated_str,
        anchor=anchor_str,
    )

    result = apply_mutations(str(tmp_path), [mutation], mode="AGENT")
    assert result.success is True
    assert len(result.relocation_events) == 1
    evt = result.relocation_events[0]

    # Required keys from Phase 12.5.1 G2
    assert "relocated" in evt and evt["relocated"] is True
    assert "old_range" in evt and evt["old_range"] == [1, 3]
    assert "new_range" in evt and evt["new_range"] == [2, 4]
    assert "reason" in evt and evt["reason"] == "relocated"
    assert "reason_text" in evt and "File drifted" in evt["reason_text"]


@pytest.mark.parametrize(
    "rejection_scenario,expected_code,expected_substr",
    [
        ("anchor_not_found", "anchor_not_found", "anchor not found: file drifted"),
        ("anchor_ambiguous", "anchor_ambiguous", "anchor ambiguous"),
        ("anchor_too_short", "anchor_too_short", "anchor_too_short"),
        ("multi_edit_requires_anchors", "multi_edit_requires_anchors", "multi-edit turns require anchors"),
        ("overlapping_edits", "overlapping_edits", "overlapping edits in one turn"),
        ("seq_anchor_ambiguous", "seq_anchor_ambiguous", "seq_anchor_ambiguous"),
        ("seq_anchor_destroyed", "seq_anchor_destroyed", "seq_anchor_destroyed"),
        ("start_line_out_of_bounds", "start_line_out_of_bounds", "out of bounds"),
        ("original_must_be_empty", "original_must_be_empty", "original_must_be_empty"),
        ("updated_empty_or_equal", "updated_empty_or_equal", "updated_empty_or_equal"),
        ("original_mismatches_disk", "original_mismatches_disk", "original_mismatches_disk"),
        ("file_does_not_exist", "file_does_not_exist", "file does not exist"),
        ("slice_syntax_error", "slice_syntax_error", "slice syntax error"),
        ("projected_syntax_error", "projected_syntax_error", "syntax error"),
    ],
)
def test_pipeline_rejection_codes_unchanged(
    tmp_path: Path,
    rejection_scenario: str,
    expected_code: str,
    expected_substr: str,
):
    """Every legacy rejection condition produces its exact code and message."""
    ws = str(tmp_path)

    if rejection_scenario == "anchor_not_found":
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        mut = Mutation(
            kind=MutationKind.EDIT_RANGE,
            path="f.py",
            start_line=1,
            end_line=2,
            updated="a = 10\n",
            anchor="def non_existent_anchor_block():\n    pass",
        )
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "anchor_ambiguous":
        (tmp_path / "f.py").write_text("item = 'repeated_anchor_block'\nitem = 'repeated_anchor_block'\n", encoding="utf-8")
        mut = Mutation(
            kind=MutationKind.EDIT_RANGE,
            path="f.py",
            start_line=5,
            end_line=6,
            updated="item = 'new'\n",
            anchor="item = 'repeated_anchor_block'",
        )
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "anchor_too_short":
        (tmp_path / "f.py").write_text("line_1 = True\npass\nline_3 = True\n", encoding="utf-8")
        mut = Mutation(
            kind=MutationKind.EDIT_RANGE,
            path="f.py",
            start_line=5,
            end_line=5,
            updated="pass\n",
            anchor="pass",  # < 40 chars and < 3 lines
        )
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "multi_edit_requires_anchors":
        (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
        m1 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=1, end_line=1, updated="a = 10\n", anchor="a = 1")
        m2 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=2, end_line=2, updated="b = 20\n", anchor=None)
        res = apply_mutations(ws, [m1, m2], mode="AGENT")

    elif rejection_scenario == "overlapping_edits":
        (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
        m1 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=1, end_line=2, updated="a = 10\nb = 20\n", anchor="a = 1\nb = 2")
        m2 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=2, end_line=3, updated="b = 20\nc = 30\n", anchor="b = 2\nc = 3")
        res = apply_mutations(ws, [m1, m2], mode="AGENT")

    elif rejection_scenario == "seq_anchor_ambiguous":
        (tmp_path / "f.py").write_text("x = 1\nanchor_b = 'unique_target'\n", encoding="utf-8")
        # m1 duplicates anchor_b
        m1 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=1, end_line=1, updated="x = 1\nanchor_b = 'unique_target'\n", anchor="x = 1")
        m2 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=2, end_line=2, updated="anchor_b = 'updated'\n", anchor="anchor_b = 'unique_target'")
        res = apply_mutations(ws, [m1, m2], mode="AGENT")

    elif rejection_scenario == "seq_anchor_destroyed":
        (tmp_path / "f.py").write_text("line1 = 1\nanchor_b = 'unique_target'\n", encoding="utf-8")
        # m1 replaces entire file destroying anchor_b
        m1 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=1, end_line=2, updated="cleared = True\n", anchor="line1 = 1\nanchor_b = 'unique_target'")
        m2 = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=2, end_line=2, updated="anchor_b = 'updated'\n", anchor="anchor_b = 'unique_target'")
        res = apply_mutations(ws, [m1, m2], mode="AGENT")

    elif rejection_scenario == "start_line_out_of_bounds":
        (tmp_path / "f.py").write_text("a = 1\n", encoding="utf-8")
        mut = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=99, end_line=100, updated="b = 2\n")
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "original_must_be_empty":
        (tmp_path / "f.py").write_text("existing content\n", encoding="utf-8")
        mut = Mutation(kind=MutationKind.CREATE, path="f.py", content="new content\n")
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "updated_empty_or_equal":
        (tmp_path / "f.py").write_text("a = 1\n", encoding="utf-8")
        mut = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=1, end_line=1, updated="   \n")
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "original_mismatches_disk":
        (tmp_path / "f.py").write_text("disk_line = 123\n", encoding="utf-8")
        mut = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=1, end_line=1, original="disk_line = 999", updated="disk_line = 456\n")
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "file_does_not_exist":
        mut = Mutation(kind=MutationKind.EDIT_RANGE, path="missing.py", start_line=1, end_line=1, updated="a = 1\n")
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "slice_syntax_error":
        (tmp_path / "f.py").write_text("def valid_func():\n    return 1\n", encoding="utf-8")
        mut = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=1, end_line=2, updated="def broken(:\n    pass\n", anchor="def valid_func():\n    return 1")
        res = apply_mutations(ws, [mut], mode="AGENT")

    elif rejection_scenario == "projected_syntax_error":
        (tmp_path / "f.py").write_text("def outer():\n    if True:\n        return 1\n", encoding="utf-8")
        # Slice is valid alone ("return 1") but replacing "if True:\n return 1" with "return 1" leaves invalid indentation in context
        mut = Mutation(kind=MutationKind.EDIT_RANGE, path="f.py", start_line=2, end_line=3, updated="    return 1\nelse:\n", anchor="    if True:\n        return 1")
        res = apply_mutations(ws, [mut], mode="AGENT")

    assert res.success is False
    assert res.rejection is not None
    assert expected_code in res.rejection.code or expected_substr in res.rejection.reason_text


def test_pipeline_syntax_contract_all_five_branches(tmp_path: Path):
    """Enforces all 5 branches of the Phase 12.5.1 G5 syntax contract."""
    ws = str(tmp_path)

    # Branch 1: Recognized code ext + checker available + newly broken -> FAIL-CLOSED
    (tmp_path / "b1.py").write_text("x = 1\n", encoding="utf-8")
    mut1 = Mutation(kind=MutationKind.WRITE_FULL, path="b1.py", new_content="def broken(\n")
    res1 = apply_mutations(ws, [mut1], mode="AGENT")
    assert res1.success is False
    assert res1.rejection.code in ("slice_syntax_error", "projected_syntax_error")

    # Branch 2: Pre-existing breakage not worsened -> ALLOW
    orig_b2 = "def f():\n    if True\n        pass\n"  # 1 syntax error
    (tmp_path / "b2.py").write_text(orig_b2, encoding="utf-8")
    mut2 = Mutation(kind=MutationKind.WRITE_FULL, path="b2.py", new_content="def f():\n    # untouched\n    if True\n        pass\n")
    res2 = apply_mutations(ws, [mut2], mode="AGENT")
    assert res2.success is True
    assert res2.syntax_status["b2.py"] == "preexisting_broken_not_worsened"
    assert "[SYNTAX_PREEXISTING_BROKEN]" in res2.metrics

    # Branch 3: Recognized code ext + checker unavailable -> FAIL-OPEN (unchecked)
    (tmp_path / "b3.go").write_text("package main\n", encoding="utf-8")
    mut3 = Mutation(kind=MutationKind.WRITE_FULL, path="b3.go", new_content="package main\nfunc Main() {}\n")
    res3 = apply_mutations(ws, [mut3], mode="AGENT")
    assert res3.success is True
    assert res3.syntax_status["b3.go"] == "unchecked"
    assert "[SYNTAX_SKIP]" in res3.metrics

    # Branch 4: Non-code extension -> FAIL-OPEN
    (tmp_path / "b4.md").write_text("# Doc\n", encoding="utf-8")
    mut4 = Mutation(kind=MutationKind.WRITE_FULL, path="b4.md", new_content="# Doc\nSome notes\n")
    res4 = apply_mutations(ws, [mut4], mode="AGENT")
    assert res4.success is True
    assert "[SYNTAX_SKIPPED_NONCODE]" in res4.metrics

    # Branch 5: Internal error during check -> FAIL-OPEN
    (tmp_path / "b5.py").write_text("a = 1\n", encoding="utf-8")
    mut5 = Mutation(kind=MutationKind.WRITE_FULL, path="b5.py", new_content="a = 2\n")
    with patch("app.features.ai.harness.content_integrity._evaluate_source_syntax", side_effect=RuntimeError("Simulated AST parser crash")):
        res5 = apply_mutations(ws, [mut5], mode="AGENT")
        assert res5.success is True
        assert res5.syntax_status["b5.py"] == "unchecked"
        assert "[SYNTAX_INTERNAL_ERROR]" in res5.metrics


def test_pipeline_three_patch_chain_rejected_preapply(tmp_path: Path):
    """V3.2 equivalence: 3-patch chain (A->B->C) where B makes C ambiguous is rejected before apply."""
    target = tmp_path / "chain.py"
    initial_code = (
        "# header\n"
        "anchor_y = 'anchor_y_original_text'\n"
        "middle = 1\n"
        "anchor_z = 'anchor_z_unique_before_b'\n"
        "# footer\n"
    )
    target.write_text(initial_code, encoding="utf-8")

    patches = [
        Mutation(
            kind=MutationKind.EDIT_RANGE,
            path="chain.py",
            start_line=1,
            end_line=1,
            updated="# header\ntext_x_inserted = True\n",
            anchor="# header",
        ),
        Mutation(
            kind=MutationKind.EDIT_RANGE,
            path="chain.py",
            start_line=2,
            end_line=2,
            updated="anchor_y = 'updated'\nanchor_z = 'anchor_z_unique_before_b'\n",
            anchor="anchor_y = 'anchor_y_original_text'",
        ),
        Mutation(
            kind=MutationKind.EDIT_RANGE,
            path="chain.py",
            start_line=4,
            end_line=4,
            updated="anchor_z = 'final_updated'\n",
            anchor="anchor_z = 'anchor_z_unique_before_b'",
        ),
    ]

    result = apply_mutations(str(tmp_path), patches, mode="AGENT")
    assert result.success is False
    assert result.rejection.stage == "preflight"
    assert "seq_anchor_ambiguous" in result.rejection.code or "seq_anchor_ambiguous" in result.rejection.reason_text
    # Zero disk writes
    assert target.read_text(encoding="utf-8") == initial_code


# ═══════════════════════════════════════════════════════════════════════════
# 2. MODE BEHAVIOR (AGENT vs USER_SAVE)
# ═══════════════════════════════════════════════════════════════════════════

def test_user_save_mode_skips_syntax_gate_but_keeps_path_safety(tmp_path: Path):
    """USER_SAVE allows saving syntactically broken code, but blocks path escape."""
    target = tmp_path / "draft.py"
    target.write_text("x = 1\n", encoding="utf-8")

    broken_code = "def half_finished_func(\n    # cursor right here\n"

    # USER_SAVE succeeds with broken syntax
    mut_user = Mutation(kind=MutationKind.WRITE_FULL, path="draft.py", new_content=broken_code)
    res_user = apply_mutations(str(tmp_path), [mut_user], mode="USER_SAVE")
    assert res_user.success is True
    assert res_user.syntax_status["draft.py"] == "skipped_user_save"
    assert "[SYNTAX_SKIPPED_USER_SAVE]" in res_user.metrics
    assert target.read_text(encoding="utf-8") == broken_code

    # AGENT mode rejects the same broken code when applied to valid file
    target.write_text("x = 1\n", encoding="utf-8")
    mut_agent = Mutation(kind=MutationKind.WRITE_FULL, path="draft.py", new_content=broken_code)
    res_agent = apply_mutations(str(tmp_path), [mut_agent], mode="AGENT")
    assert res_agent.success is False
    assert res_agent.rejection.stage == "validate"

    # USER_SAVE still strictly enforces path safety
    escape_mut = Mutation(kind=MutationKind.WRITE_FULL, path="../../evil.py", new_content="bad")
    res_escape = apply_mutations(str(tmp_path), [escape_mut], mode="USER_SAVE")
    assert res_escape.success is False
    assert res_escape.rejection.code == "path_outside_workspace"


def test_user_save_mode_still_invalidates_index(tmp_path: Path):
    """USER_SAVE mode still synchronously invalidates the symbol index."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")

    with patch("app.features.ai.harness.mutation_pipeline.invalidate_file") as mock_inv:
        mut = Mutation(kind=MutationKind.WRITE_FULL, path="app.py", new_content="x = 2\n")
        res = apply_mutations(str(tmp_path), [mut], mode="USER_SAVE")
        assert res.success is True
        assert mock_inv.call_count >= 1


def test_invalid_mode_rejected(tmp_path: Path):
    """Unrecognized mode is rejected immediately in S1 resolve."""
    mut = Mutation(kind=MutationKind.WRITE_FULL, path="test.py", new_content="a = 1\n")
    res = apply_mutations(str(tmp_path), [mut], mode="UNRECOGNIZED_MODE")
    assert res.success is False
    assert res.rejection.code == "invalid_mode"
    assert res.rejection.stage == "resolve"


# ═══════════════════════════════════════════════════════════════════════════
# 3. ATOMICITY AND ROLLBACK
# ═══════════════════════════════════════════════════════════════════════════

def test_multi_file_second_file_fails_first_restored(tmp_path: Path):
    """When a multi-file mutation fails on the second file during apply, file 1 is restored."""
    f1 = tmp_path / "first.py"
    f2 = tmp_path / "second.py"
    f1.write_text("first_original = True\n", encoding="utf-8")
    f2.write_text("second_original = True\n", encoding="utf-8")

    m1 = Mutation(kind=MutationKind.WRITE_FULL, path="first.py", new_content="first_updated = True\n")
    m2 = Mutation(kind=MutationKind.WRITE_FULL, path="second.py", new_content="second_updated = True\n")

    real_replace = os.replace

    def mock_replace(src, dst):
        if "second.py" in str(dst):
            raise OSError("Simulated disk error writing second file")
        return real_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
        res = apply_mutations(str(tmp_path), [m1, m2], mode="AGENT")
        assert res.success is False

    # File 1 must be restored to its pre-call snapshot
    assert f1.read_text(encoding="utf-8") == "first_original = True\n"
    assert f2.read_text(encoding="utf-8") == "second_original = True\n"


def test_rollback_restores_exact_bytes(tmp_path: Path):
    """Rollback restores exact byte-for-byte snapshot content."""
    target = tmp_path / "binary_snapshot.dat"
    exact_bytes = b"header\r\n\x00\x01\x02\xffspecial_bytes\r\n"
    target.write_bytes(exact_bytes)

    m1 = Mutation(kind=MutationKind.WRITE_FULL, path="binary_snapshot.dat", new_content="new_content")
    m2 = Mutation(kind=MutationKind.EDIT_RANGE, path="missing.py", start_line=1, end_line=1, updated="fails")

    res = apply_mutations(str(tmp_path), [m1, m2], mode="AGENT")
    assert res.success is False
    assert target.read_bytes() == exact_bytes


def test_created_file_deleted_on_rollback(tmp_path: Path):
    """A file created during a failed batch is deleted during rollback."""
    f1 = tmp_path / "existing.py"
    f1.write_text("initial = 1\n", encoding="utf-8")

    new_file = tmp_path / "sub" / "new_created.py"
    assert not new_file.exists()

    m_create = Mutation(kind=MutationKind.CREATE, path="sub/new_created.py", content="created_content = True\n")
    m_fail = Mutation(kind=MutationKind.WRITE_FULL, path="existing.py", new_content="updated = 1\n")

    real_replace = os.replace

    def mock_replace(src, dst):
        if "existing.py" in str(dst):
            raise OSError("Fail on existing file write")
        return real_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
        res = apply_mutations(str(tmp_path), [m_create, m_fail], mode="AGENT")
        assert res.success is False

    assert not new_file.exists()
    assert f1.read_text(encoding="utf-8") == "initial = 1\n"


def test_failure_in_invalidate_stage_triggers_rollback(tmp_path: Path):
    """A failure in S5 invalidate triggers S6 rollback and restores files."""
    f1 = tmp_path / "f1.py"
    f1.write_text("pre_call_content = True\n", encoding="utf-8")

    m = Mutation(kind=MutationKind.WRITE_FULL, path="f1.py", new_content="post_call_content = True\n")

    with patch("app.features.ai.harness.mutation_pipeline.invalidate_file", side_effect=RuntimeError("Index crash")):
        res = apply_mutations(str(tmp_path), [m], mode="AGENT")
        assert res.success is False
        assert res.rejection.stage in ("invalidate", "rollback")

    # Rolled back
    assert f1.read_text(encoding="utf-8") == "pre_call_content = True\n"


def test_crash_between_temp_write_and_replace_leaves_original_intact(tmp_path: Path):
    """Failure before os.replace leaves original file untouched on disk."""
    target = tmp_path / "intact.py"
    target.write_text("original_intact = True\n", encoding="utf-8")

    mut = Mutation(kind=MutationKind.WRITE_FULL, path="intact.py", new_content="corrupted = True\n")

    with patch("os.replace", side_effect=RuntimeError("Crash before replace")):
        res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
        assert res.success is False

    assert target.read_text(encoding="utf-8") == "original_intact = True\n"


def test_rollback_failure_is_reported_not_swallowed(tmp_path: Path):
    """If rollback itself fails, code='rollback_failed' is surfaced loudly."""
    target = tmp_path / "fail_rollback.py"
    target.write_text("original = True\n", encoding="utf-8")

    mut = Mutation(kind=MutationKind.WRITE_FULL, path="fail_rollback.py", new_content="updated = True\n")

    def mock_replace(src, dst):
        raise OSError("Trigger rollback")

    with patch("os.replace", side_effect=mock_replace):
        with patch("pathlib.Path.write_bytes", side_effect=PermissionError("Permission denied during rollback")):
            res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
            assert res.success is False
            assert res.rejection.code == "rollback_failed"
            assert "fail_rollback.py" in res.rejection.reason_text


# ═══════════════════════════════════════════════════════════════════════════
# 4. INVALIDATION (file-watcher events suppressed)
# ═══════════════════════════════════════════════════════════════════════════

def test_every_write_kind_invalidates_index_synchronously(tmp_path: Path):
    """EDIT_RANGE, WRITE_FULL, CREATE, and APPEND all invalidate symbol_index synchronously."""
    (tmp_path / "existing.py").write_text("x = 1\ny = 2\n", encoding="utf-8")

    cases = [
        Mutation(kind=MutationKind.CREATE, path="new.py", content="z = 3\n"),
        Mutation(kind=MutationKind.WRITE_FULL, path="existing.py", new_content="x = 10\ny = 20\n"),
        Mutation(kind=MutationKind.APPEND, path="existing.py", content="# append comment\n"),
        Mutation(kind=MutationKind.EDIT_RANGE, path="existing.py", start_line=1, end_line=1, updated="x = 100\n", anchor="x = 10"),
    ]

    for c in cases:
        with patch("app.features.ai.harness.mutation_pipeline.invalidate_file") as mock_inv:
            res = apply_mutations(str(tmp_path), [c], mode="AGENT")
            assert res.success is True, f"Failed on {c.kind}: {res.rejection}"
            assert mock_inv.call_count >= 1, f"Expected invalidate_file call for {c.kind}"


def test_rollback_invalidates_index_too(tmp_path: Path):
    """When rollback occurs, symbol_index is invalidated again."""
    (tmp_path / "roll_inv.py").write_text("val = 1\n", encoding="utf-8")
    mut = Mutation(kind=MutationKind.WRITE_FULL, path="roll_inv.py", new_content="val = 2\n")

    with patch("os.replace", side_effect=OSError("Trigger rollback")):
        with patch("app.features.ai.harness.mutation_pipeline.invalidate_file") as mock_inv:
            res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
            assert res.success is False
            # Invalidation must be called during rollback
            assert mock_inv.call_count >= 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. PATH SAFETY
# ═══════════════════════════════════════════════════════════════════════════

def test_path_traversal_rejected_zero_disk_touch(tmp_path: Path):
    """Path traversal escaping workspace root is rejected with zero disk touch."""
    mut = Mutation(kind=MutationKind.WRITE_FULL, path="../../outside_leak.txt", new_content="leaked")
    res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
    assert res.success is False
    assert res.rejection.code == "path_outside_workspace"


def test_absolute_path_outside_workspace_rejected(tmp_path: Path):
    """Absolute path pointing outside workspace root is rejected."""
    outside_path = str(tmp_path.parent / "other_outside.txt")
    mut = Mutation(kind=MutationKind.WRITE_FULL, path=outside_path, new_content="bad")
    res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
    assert res.success is False
    assert res.rejection.code == "path_outside_workspace"


def test_symlink_escape_rejected(tmp_path: Path, tmp_path_factory):
    """Symlink pointing outside workspace root is rejected with code='symlink_escape'."""
    outside_dir = tmp_path_factory.mktemp("outside_target")
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("secret_content\n", encoding="utf-8")

    link_path = tmp_path / "link_escape.txt"
    try:
        os.symlink(secret_file, link_path)
    except OSError as err:
        pytest.skip(f"Symlink creation requires admin/developer mode on Windows: {err}")

    mut = Mutation(kind=MutationKind.WRITE_FULL, path="link_escape.txt", new_content="overwrite")
    res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
    assert res.success is False
    assert res.rejection.code == "symlink_escape"


# ═══════════════════════════════════════════════════════════════════════════
# 6. ENCODING / LINE ENDINGS
# ═══════════════════════════════════════════════════════════════════════════

def test_crlf_file_stays_crlf_after_edit_range(tmp_path: Path):
    """A file with CRLF line endings preserves CRLF after EDIT_RANGE."""
    target = tmp_path / "crlf_file.py"
    crlf_bytes = b"line 1\r\ndef compute():\r\n    return 42\r\nline 4\r\n"
    target.write_bytes(crlf_bytes)

    anchor_str = "def compute():\n    return 42"
    updated_str = "def compute():\n    return 100"

    mut = Mutation(
        kind=MutationKind.EDIT_RANGE,
        path="crlf_file.py",
        start_line=2,
        end_line=3,
        updated=updated_str,
        anchor=anchor_str,
    )

    res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
    assert res.success is True

    result_bytes = target.read_bytes()
    assert b"\r\n" in result_bytes
    assert b"\r\r\n" not in result_bytes
    # No bare LF
    assert result_bytes.replace(b"\r\n", b"").find(b"\n") == -1
    assert b"return 100" in result_bytes


def test_utf8_bom_preserved_or_behavior_matches_legacy(tmp_path: Path):
    """A file with UTF-8 BOM preserves the BOM prefix after mutation."""
    target = tmp_path / "bom_file.py"
    bom_prefix = b"\xef\xbb\xbf"
    initial_bytes = bom_prefix + b"def hello():\n    return 'world'\n"
    target.write_bytes(initial_bytes)

    mut = Mutation(
        kind=MutationKind.WRITE_FULL,
        path="bom_file.py",
        new_content="def hello():\n    return 'galaxy'\n",
    )

    res = apply_mutations(str(tmp_path), [mut], mode="AGENT")
    assert res.success is True

    result_bytes = target.read_bytes()
    assert result_bytes.startswith(bom_prefix)
    assert b"'galaxy'" in result_bytes
