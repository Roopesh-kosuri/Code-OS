import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.features.ai.service import (
    extract_proposals_robust,
    parse_proposals_from_llm,
    apply_proposal,
    EditProposalDto,
)
from app.features.ai.agents.agent_tools import _handle_edit_file
from app.features.ai.spec_coverage import check_coverage, format_coverage_report


def test_proposal_rejected_when_original_mismatches_disk(tmp_path):
    """Repro fixture test:
    Weak model output containing TWO [PROPOSAL: main.py] blocks where
    ORIGINAL holds the NEW code and UPDATED is empty, plus [TOOL_CALL: ...]
    text and [DONE].
    Must reject, leave disk untouched, and report honest summary.
    """
    main_file = tmp_path / "main.py"
    original_disk_bytes = b"def main():\n    print('real code on disk')\n"
    main_file.write_bytes(original_disk_bytes)

    repro_fixture = """
I have analyzed your request and prepared the changes:

[TOOL_CALL: edit_file]
{"path": "main.py", "original": "pass", "updated": ""}
[/TOOL_CALL]

[PROPOSAL: main.py]
<<<< ORIGINAL
def main():
    print("New code 1 (hallucinated in original)")
====

>>>>

[PROPOSAL: main.py]
<<<< ORIGINAL
def main():
    print("Different new code 2 (hallucinated in original)")
====

>>>>
[DONE]
"""
    # 1. Extraction with workspace validation
    proposals = extract_proposals_robust(repro_fixture, workspace=str(tmp_path))
    assert proposals == [], "Expected zero proposals from malformed repro fixture"

    # 2. Parsing with summary report
    changes, summary = parse_proposals_from_llm(repro_fixture, workspace=str(tmp_path))
    assert changes == []
    assert summary == "model output did not contain a valid proposal"

    # 3. Verify disk is byte-for-byte untouched
    assert main_file.read_bytes() == original_disk_bytes


def test_proposal_rejected_when_updated_empty_or_equal(tmp_path):
    """Verify proposals are rejected when UPDATED is empty or equal to ORIGINAL."""
    sample_file = tmp_path / "calc.py"
    sample_file.write_text("x = 10\n", encoding="utf-8")

    # Case A: UPDATED is empty
    empty_updated_fixture = """
[PROPOSAL: calc.py]
<<<< ORIGINAL
x = 10
====

>>>>
"""
    assert extract_proposals_robust(empty_updated_fixture, workspace=str(tmp_path)) == []

    # Case B: UPDATED is equal to ORIGINAL
    equal_updated_fixture = """
[PROPOSAL: calc.py]
<<<< ORIGINAL
x = 10
====
x = 10
>>>>
"""
    assert extract_proposals_robust(equal_updated_fixture, workspace=str(tmp_path)) == []

    # Case C: _handle_edit_file validation
    staged = []
    res_empty = _handle_edit_file(str(tmp_path), {"path": "calc.py", "original": "x = 10", "updated": ""}, staged)
    assert not res_empty.success
    assert "updated_empty_or_equal" in res_empty.error

    res_equal = _handle_edit_file(str(tmp_path), {"path": "calc.py", "original": "x = 10", "updated": "x = 10"}, staged)
    assert not res_equal.success
    assert "updated_empty_or_equal" in res_equal.error


def test_multiple_proposals_last_wellformed_wins(tmp_path):
    """Verify that when multiple well-formed candidates exist for a path, the LAST wins."""
    app_file = tmp_path / "app.py"
    app_file.write_text("status = 'idle'\n", encoding="utf-8")

    multi_fixture = """
[PROPOSAL: app.py]
<<<< ORIGINAL
status = 'idle'
====
status = 'running'
>>>>

[PROPOSAL: app.py]
<<<< ORIGINAL
status = 'idle'
====
status = 'completed'
>>>>
"""
    proposals = extract_proposals_robust(multi_fixture, workspace=str(tmp_path))
    assert len(proposals) == 1, "Exactly one proposal per path per turn"
    assert proposals[0].path == "app.py"
    assert proposals[0].updated == "status = 'completed'"


def test_invalid_proposal_leaves_disk_untouched_and_reports_reason(tmp_path):
    """Verify invalid proposals leave disk untouched and report accurate failure reasons."""
    target = tmp_path / "module.py"
    target.write_text("def run():\n    return False\n", encoding="utf-8")
    initial_bytes = target.read_bytes()

    staged = []
    # Attempt edit with mismatched original
    res = _handle_edit_file(
        str(tmp_path),
        {"path": "module.py", "original": "def run():\n    return True\n", "updated": "def run():\n    return 42\n"},
        staged
    )
    assert not res.success
    assert "original_mismatches_disk" in res.error
    assert staged == []
    assert target.read_bytes() == initial_bytes

    # Attempt new file with non-empty original
    res_new = _handle_edit_file(
        str(tmp_path),
        {"path": "new_mod.py", "original": "non-empty original", "updated": "def new_fn(): pass"},
        staged
    )
    assert not res_new.success
    assert "original_must_be_empty" in res_new.error
    assert not (tmp_path / "new_mod.py").exists()


def test_completion_claim_requires_readback_and_verification(tmp_path):
    """Verify spec coverage claims require referenced tests to exist, else unverified."""
    # 1. Missing referenced test file -> unverified, never 100%
    reqs = ["implement login", "verify with tests/test_login.py"]
    cov_missing = check_coverage(reqs, manifest_entries={"login.py": {"purpose": "login"}}, completed_tasks=[], workspace=str(tmp_path))
    assert cov_missing["test_file_missing"] is True
    report_missing = format_coverage_report(cov_missing)
    assert "Spec coverage: unverified: test file missing" in report_missing
    assert "100%" not in report_missing
    assert "[VERIFICATIONS RUN]" in report_missing

    # 2. Existing referenced test file -> full coverage
    test_file = tmp_path / "test_login.py"
    test_file.write_text("def test_login(): pass\n", encoding="utf-8")
    cov_present = check_coverage(
        ["login"],
        manifest_entries={"login.py": {"purpose": "login endpoint", "exports": ["login"]}},
        completed_tasks=[{"title": "implement login", "reasoning_summary": "verified with tests/test_login.py"}],
        workspace=str(tmp_path)
    )
    assert cov_present["test_file_missing"] is False
    report_present = format_coverage_report(cov_present, verifications_run=["read_back_hash", "syntax_check:py", "test_suite:passed"])
    assert "Spec coverage: 100%" in report_present
    assert "[VERIFICATIONS RUN] read_back_hash, syntax_check:py, test_suite:passed" in report_present


@pytest.mark.asyncio
async def test_apply_proposal_idempotent_no_op():
    """Verify that applying an already-applied proposal is a safe no-op (Phase 10.19 C2)."""
    mock_proposal = EditProposalDto(
        id="prop-already-applied",
        workspace="/dummy/ws",
        status="applied",
        summary="Test proposal",
        changes=[],
        diff="",
        created_at="2026-09-15T00:00:00Z"
    )
    with patch("app.features.ai.service.get_proposal", new=AsyncMock(return_value=mock_proposal)):
        result = await apply_proposal("prop-already-applied")
        assert result.id == "prop-already-applied"
        assert result.status == "applied"
