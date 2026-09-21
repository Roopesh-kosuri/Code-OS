"""Tests for Phase 14 Part 1: Pure Verdict Logic, Data Model, and Completion Text."""

from pathlib import Path
import pytest

from app.features.ai.harness.verification_matrix import (
    DEFAULT_VERIFY_SETTINGS,
    Verdict,
    VerdictState,
    VerifyResult,
    VerifyStatus,
    completion_line,
    compute_verdict,
    is_code_file,
    is_test_file,
    parse_verify_settings,
)


# ── Table Tests ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "results,info,expected_state,expected_reason_substr,expected_caveat_substr",
    [
        # Row 1a: FAILED readback_hash
        (
            [
                VerifyResult("readback_hash", VerifyStatus.FAILED, "Disk mismatch", ["file.py: hash mismatch"]),
                VerifyResult("test_suite", VerifyStatus.PASSED, "10 passed"),
            ],
            {"changed_files": ["file.py"]},
            VerdictState.FAILED,
            "readback_hash",
            None,
        ),
        # Row 1b: FAILED test_suite (caused by turn)
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult("test_suite", VerifyStatus.FAILED, "1 failed", ["test_add"]),
            ],
            {"changed_files": ["calc.py"]},
            VerdictState.FAILED,
            "test_add",
            None,
        ),
        # Row 1c: FAILED security_scan (HIGH)
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult("test_suite", VerifyStatus.PASSED, "OK"),
                VerifyResult("security_scan", VerifyStatus.FAILED, "High finding", ["os.system at line 10"]),
            ],
            {"changed_files": ["server.py"]},
            VerdictState.FAILED,
            "os.system",
            None,
        ),
        # Row 2a: ERROR (hook crash) and no FAILED -> UNVERIFIED
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult("test_suite", VerifyStatus.ERROR, "Process crashed"),
            ],
            {"changed_files": ["app.py"]},
            VerdictState.UNVERIFIED,
            "hook internal error: test_suite",
            None,
        ),
        # Row 2b: TIMEOUT and no FAILED -> UNVERIFIED
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult("test_suite", VerifyStatus.TIMEOUT, "Exceeded 120s"),
            ],
            {"changed_files": ["app.py"]},
            VerdictState.UNVERIFIED,
            "tests timed out",
            None,
        ),
        # Row 3: readback_hash PASSED, test_suite PASSED -> VERIFIED
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult("test_suite", VerifyStatus.PASSED, "5 passed"),
                VerifyResult("security_scan", VerifyStatus.PASSED, "No findings"),
            ],
            {"changed_files": ["math_utils.py"]},
            VerdictState.VERIFIED,
            None,
            None,
        ),
        # Row 4: Only non-code files changed, readback_hash PASSED -> VERIFIED with caveat
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
            ],
            {"changed_files": ["README.md", "docs/api.txt"], "non_code_only": True},
            VerdictState.VERIFIED,
            None,
            "non-code change: readback only",
        ),
        # Row 5a: Code changed, test_suite SKIPPED (untrusted workspace) -> UNVERIFIED
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult("test_suite", VerifyStatus.SKIPPED, "workspace untrusted", skip_reason="workspace untrusted"),
            ],
            {"changed_files": ["main.py"]},
            VerdictState.UNVERIFIED,
            "workspace untrusted",
            None,
        ),
        # Row 5b: Code changed, test_suite SKIPPED (no targeted tests) -> UNVERIFIED
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult("test_suite", VerifyStatus.SKIPPED, "no targeted tests for changed files", skip_reason="no targeted tests"),
            ],
            {"changed_files": ["orphan.py"]},
            VerdictState.UNVERIFIED,
            "no targeted tests",
            None,
        ),
        # Row 6: Baseline could not attribute failing tests -> UNVERIFIED
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult(
                    "test_suite",
                    VerifyStatus.WARN,
                    "Baseline unavailable: test failures not attributed",
                    caveats=["baseline unavailable"],
                ),
            ],
            {"changed_files": ["core.py"]},
            VerdictState.UNVERIFIED,
            "failures could not be attributed",
            "baseline unavailable",
        ),
        # Row 7: Failing tests that also fail at baseline -> WARN, does NOT fail verdict
        (
            [
                VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
                VerifyResult(
                    "test_suite",
                    VerifyStatus.WARN,
                    "2 pre-existing failures confirmed by baseline",
                    details=["test_preexisting_1", "test_preexisting_2"],
                    caveats=["pre-existing failure"],
                ),
            ],
            {"changed_files": ["core.py"]},
            VerdictState.VERIFIED,
            None,
            "pre-existing failure",
        ),
    ],
)
def test_verdict_table_every_row(
    results, info, expected_state, expected_reason_substr, expected_caveat_substr
):
    verdict = compute_verdict(results, info)
    assert verdict.state == expected_state
    if expected_reason_substr:
        assert any(expected_reason_substr.lower() in r.lower() for r in verdict.reasons), f"Expected reason '{expected_reason_substr}' in {verdict.reasons}"
    if expected_caveat_substr:
        assert any(expected_caveat_substr.lower() in c.lower() for c in verdict.caveats), f"Expected caveat '{expected_caveat_substr}' in {verdict.caveats}"


# ── Caveat Accumulation Tests ────────────────────────────────────────────────

def test_caveat_when_tests_edited_in_turn():
    results = [
        VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
        VerifyResult("test_suite", VerifyStatus.PASSED, "10 passed"),
    ]
    info = {"changed_files": ["src/logic.py", "tests/test_logic.py"]}
    verdict = compute_verdict(results, info)
    assert verdict.state == VerdictState.VERIFIED
    assert "tests were edited in this turn: weaker evidence" in verdict.caveats


def test_caveat_when_security_suppressions_added():
    results = [
        VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
        VerifyResult("test_suite", VerifyStatus.PASSED, "10 passed"),
    ]
    info = {"changed_files": ["src/logic.py"], "suppressions_added": 2}
    verdict = compute_verdict(results, info)
    assert verdict.state == VerdictState.VERIFIED
    assert "2 security suppressions added in this turn" in verdict.caveats


def test_caveat_when_partial_coverage():
    results = [
        VerifyResult("readback_hash", VerifyStatus.PASSED, "OK"),
        VerifyResult("test_suite", VerifyStatus.PASSED, "20 passed", coverage_note="partial: 20 of 45 test files"),
    ]
    info = {"changed_files": ["src/logic.py"]}
    verdict = compute_verdict(results, info)
    assert verdict.state == VerdictState.VERIFIED
    assert "coverage partial: 20 of 45 test files" in verdict.caveats


# ── Completion Line Tests ────────────────────────────────────────────────────

def test_completion_line_is_deterministic_and_never_bare_success():
    # 1. Verified with caveats
    v1 = Verdict(VerdictState.VERIFIED, caveats=["tests were edited in this turn: weaker evidence"])
    line1 = completion_line(v1)
    assert line1 == "Verified (tests were edited in this turn: weaker evidence)."
    assert "successfully completed" not in line1.lower()

    # 2. Verified clean
    v2 = Verdict(VerdictState.VERIFIED)
    line2 = completion_line(v2)
    assert line2 == "Verified."

    # 3. Unverified with reasons
    v3 = Verdict(VerdictState.UNVERIFIED, reasons=["workspace untrusted"])
    line3 = completion_line(v3)
    assert line3 == "Completed unverified: workspace untrusted."

    # 4. Failed with reasons
    v4 = Verdict(VerdictState.FAILED, reasons=["test_suite: test_divide_by_zero failed"])
    line4 = completion_line(v4)
    assert line4 == "Completed with verification failures: test_suite: test_divide_by_zero failed."


# ── Settings Parsing and Clamping Tests ───────────────────────────────────────

def test_settings_defaults_clamps_and_invalid_fallback():
    # Defaults
    s_default = parse_verify_settings({})
    assert s_default == DEFAULT_VERIFY_SETTINGS

    # Valid overrides
    raw = {
        "code_os_verify_enabled": "false",
        "code_os_verify_timeout_s": 50,
        "code_os_verify_max_test_files": 10,
        "code_os_verify_baseline_max_mb": 150,
        "code_os_verify_security_enabled": True,
    }
    parsed = parse_verify_settings(raw)
    assert parsed["code_os_verify_enabled"] is False
    assert parsed["code_os_verify_timeout_s"] == 50
    assert parsed["code_os_verify_max_test_files"] == 10
    assert parsed["code_os_verify_baseline_max_mb"] == 150

    # Clamping: timeout clamped between 5 and 900
    clamped_low = parse_verify_settings({"code_os_verify_timeout_s": 1})
    assert clamped_low["code_os_verify_timeout_s"] == 5

    clamped_high = parse_verify_settings({"code_os_verify_timeout_s": 9999})
    assert clamped_high["code_os_verify_timeout_s"] == 900

    # Invalid types fall back gracefully
    invalid = parse_verify_settings({"code_os_verify_timeout_s": "not-a-number"})
    assert invalid["code_os_verify_timeout_s"] == 120
