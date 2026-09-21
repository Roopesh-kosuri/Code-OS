"""Regression tests for Phase 14 Part 3: Test runner hook (verify_runners.py)."""

import asyncio
import hashlib
import os
import sys
from pathlib import Path
import pytest

from app.features.ai.harness.verification_matrix import (
    compute_verdict,
    Verdict,
    VerdictState,
    VerifyResult,
    VerifyStatus,
)
from app.features.ai.harness.verify_runners import (
    JUnitReport,
    build_reverse_import_index,
    build_scrubbed_env,
    cleanup_verify_temp_dir,
    create_verify_temp_dir,
    detect_runners_for_files,
    get_targeted_tests_for_files,
    parse_junit_xml,
    run_pytest_subprocess,
    run_test_suite_hook,
    strip_ansi_and_cap,
    allow_runner_once,
)
from app.features.workspaces.trust_service import set_workspace_trust


def _hash_dir(directory: Path) -> dict[str, str]:
    """Compute relative path -> sha256 hash for all files in a directory."""
    hashes = {}
    for root, _, files in os.walk(str(directory)):
        for f in sorted(files):
            fp = Path(root) / f
            rel = str(fp.relative_to(directory)).replace("\\", "/")
            try:
                hashes[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()
            except Exception:
                pass
    return hashes


# ── Targeted Tests & Reverse Import Mapping ──────────────────────────────────

def test_reverse_import_mapping_finds_tests_with_nonmatching_names(tmp_path: Path):
    """Test reverse-import AST mapping finds tests whose names do not match changed file."""
    # Create src/auth_engine.py
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    auth_file = src_dir / "auth_engine.py"
    auth_file.write_text("def authenticate(): return True\n", encoding="utf-8")

    # Create tests/test_security_flow.py that imports auth_engine
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_sec = tests_dir / "test_security_flow.py"
    test_sec.write_text("from src.auth_engine import authenticate\ndef test_sec(): assert authenticate()\n", encoding="utf-8")

    index = build_reverse_import_index(tmp_path)
    assert "src.auth_engine" in index or "auth_engine" in index
    
    targeted, note = get_targeted_tests_for_files(tmp_path, ["src/auth_engine.py"])
    assert "tests/test_security_flow.py" in targeted
    assert note is None


def test_runs_only_targeted_tests_for_changed_file(tmp_path: Path):
    """Only targeted tests for the changed file are returned; unrelated tests omitted."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.py").write_text("def func_a(): pass\n", encoding="utf-8")
    (src_dir / "b.py").write_text("def func_b(): pass\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").write_text("import src.a\ndef test_a(): pass\n", encoding="utf-8")
    (tests_dir / "test_b.py").write_text("import src.b\ndef test_b(): pass\n", encoding="utf-8")

    targeted, _ = get_targeted_tests_for_files(tmp_path, ["src/a.py"])
    assert "tests/test_a.py" in targeted
    assert "tests/test_b.py" not in targeted


def test_no_targeted_tests_is_honest_skip_not_pass(tmp_path: Path):
    """When no targeted tests exist for a changed code file, returns SKIPPED with honest reason."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "orphan.py").write_text("def orphan(): pass\n", encoding="utf-8")

    targeted, _ = get_targeted_tests_for_files(tmp_path, ["src/orphan.py"])
    assert targeted == []


def test_partial_coverage_caveat_when_over_cap(tmp_path: Path):
    """When targeted tests exceed max cap, only first N are returned with coverage note."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "util.py").write_text("def util(): pass\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for i in range(25):
        (tests_dir / f"test_u{i}.py").write_text(f"import src.util\ndef test_{i}(): pass\n", encoding="utf-8")

    targeted, note = get_targeted_tests_for_files(tmp_path, ["src/util.py"], max_test_files=5)
    assert len(targeted) == 5
    assert note == "partial: 5 of 25 test files"


# ── JUnit XML Parsing & Exit Code Masking ────────────────────────────────────

def test_zero_collected_is_skip_not_pass(tmp_path: Path):
    """0 collected tests is parsed as total=0 -> treated as SKIPPED, not PASSED."""
    report_file = tmp_path / "junit.xml"
    report_file.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites><testsuite name="pytest" tests="0" errors="0" failures="0" skipped="0"></testsuite></testsuites>',
        encoding="utf-8",
    )
    rep = parse_junit_xml(report_file)
    assert rep.total == 0
    assert rep.failed == 0
    assert rep.passed == 0


def test_junit_used_not_return_code_even_when_process_exits_zero_on_failure(tmp_path: Path):
    """A test failure reported in JUnit XML is detected even if returncode is 0 (exit code masking)."""
    report_file = tmp_path / "junit.xml"
    report_file.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuite name="pytest" tests="2" errors="0" failures="1" skipped="0">\n'
        '  <testcase classname="test_math" name="test_add" time="0.01"/>\n'
        '  <testcase classname="test_math" name="test_sub" time="0.01">\n'
        '    <failure message="assert 1 == 2">def test_sub(): assert 1 == 2</failure>\n'
        '  </testcase>\n'
        '</testsuite>',
        encoding="utf-8",
    )
    rep = parse_junit_xml(report_file)
    assert rep.total == 2
    assert rep.failed == 1
    assert rep.passed == 1
    assert "test_math::test_sub" in rep.failing_ids


def test_missing_report_is_error_unverified(tmp_path: Path):
    """Missing or unparseable report returns JUnitReport with parse_error."""
    non_existent = tmp_path / "does_not_exist.xml"
    rep = parse_junit_xml(non_existent)
    assert rep.parse_error is not None
    assert "not generated" in rep.parse_error


# ── Subprocess Safety: Env Scrubbing, Tree Kill, Workspace Integrity ─────────

def test_env_is_scrubbed_of_keys_and_tokens():
    """Environment scrub drops API keys, secrets, tokens, and credentials."""
    old_env = os.environ.copy()
    try:
        os.environ["OPENAI_API_KEY"] = "sk-secret-123"
        os.environ["MY_SECRET_TOKEN"] = "token-xyz"
        os.environ["DB_PASSWORD"] = "mypassword"
        os.environ["SAFE_PATH"] = "some_val"

        scrubbed = build_scrubbed_env()
        assert "OPENAI_API_KEY" not in scrubbed
        assert "MY_SECRET_TOKEN" not in scrubbed
        assert "DB_PASSWORD" not in scrubbed
        assert scrubbed.get("CI") == "1"
        assert scrubbed.get("PYTHONDONTWRITEBYTECODE") == "1"
    finally:
        os.environ.clear()
        os.environ.update(old_env)


def test_output_is_capped_and_ansi_stripped():
    """Output strips ANSI codes and caps length with head+tail preservation."""
    ansi_text = b"\x1b[31mRed Alert\x1b[0m\n" * 10
    stripped = strip_ansi_and_cap(ansi_text)
    assert "Red Alert" in stripped
    assert "\x1b[31m" not in stripped

    # Capped output
    huge_bytes = b"A" * 300 * 1024
    capped = strip_ansi_and_cap(huge_bytes, max_bytes=1000)
    assert len(capped) < 2000
    assert "[TRUNCATED OUTPUT]" in capped


@pytest.mark.asyncio
async def test_verify_run_leaves_workspace_byte_identical(tmp_path: Path):
    """A pytest run leaves the workspace tree byte-identical (no .pytest_cache or temp files)."""
    # Setup trusted workspace
    ws_str = str(tmp_path)
    await set_workspace_trust(ws_str, True)
    allow_runner_once(tmp_path, "pytest")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "maths.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_maths.py").write_text("from src.maths import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")

    initial_hashes = _hash_dir(tmp_path)

    # Run the test suite hook
    res = await run_test_suite_hook(tmp_path, ["src/maths.py"])
    assert res.status == VerifyStatus.PASSED

    final_hashes = _hash_dir(tmp_path)
    assert initial_hashes == final_hashes, f"Workspace tree modified: {set(final_hashes) ^ set(initial_hashes)}"


@pytest.mark.asyncio
async def test_user_declined_execution_is_skip(tmp_path: Path):
    """When a runner is not approved, returns SKIPPED 'user declined test execution'."""
    ws_str = str(tmp_path)
    await set_workspace_trust(ws_str, True)
    # Do NOT call allow_runner_once

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "maths.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_maths.py").write_text("from src.maths import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")

    res = await run_test_suite_hook(tmp_path, ["src/maths.py"])
    assert res.status == VerifyStatus.SKIPPED
    assert "declined" in res.skip_reason.lower()


@pytest.mark.asyncio
async def test_untrusted_workspace_executes_nothing(tmp_path: Path):
    """Untrusted workspace returns SKIPPED 'workspace untrusted' without executing."""
    ws_str = str(tmp_path)
    await set_workspace_trust(ws_str, False)

    (tmp_path / "calc.py").write_text("def x(): pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text("import calc\ndef test_x(): pass\n", encoding="utf-8")

    res = await run_test_suite_hook(tmp_path, ["calc.py"])
    assert res.status == VerifyStatus.SKIPPED
    assert "untrusted" in res.skip_reason.lower()


def test_vitest_jest_detection_and_argv_construction(tmp_path: Path):
    """Detects vitest/jest when package.json and local binaries exist; reports missing binary."""
    # Vitest with missing local binary in node_modules/.bin
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text('{"devDependencies": {"vitest": "^1.0.0"}}', encoding="utf-8")
    (tmp_path / "calc.test.ts").write_text("test('x', () => {});", encoding="utf-8")

    runners = detect_runners_for_files(tmp_path, ["calc.test.ts"])
    assert len(runners) == 1
    assert runners[0]["type"] == "vitest"
    assert "skip_reason" in runners[0]


@pytest.mark.asyncio
async def test_missing_pytest_or_runner_error_yields_unverified_never_failed(tmp_path: Path):
    """When test runner produces no report XML (e.g. runner crash or missing pytest), status is ERROR and verdict is UNVERIFIED, never FAILED."""
    err_res = VerifyResult(
        hook="test_suite",
        status=VerifyStatus.ERROR,
        summary="no test report produced (runner exited rc=1): No module named pytest",
        details=["ModuleNotFoundError: No module named 'pytest'"],
    )
    # Even with code files changed, verdict must be UNVERIFIED, not FAILED
    verdict = compute_verdict([err_res], {"changed_files": ["app/main.py"]})
    assert verdict.state == VerdictState.UNVERIFIED
    assert verdict.state != VerdictState.FAILED
    assert "hook internal error: test_suite" in verdict.reasons or "test_suite" in " ".join(verdict.reasons)


@pytest.mark.asyncio
async def test_missing_module_imports_yields_unverified_never_failed(tmp_path: Path):
    """When workspace tests fail collection due to missing module dependencies, status is ERROR and verdict is UNVERIFIED, never FAILED."""
    ws_str = str(tmp_path)
    await set_workspace_trust(ws_str, True)
    allow_runner_once(tmp_path, "pytest")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "service.py").write_text("def run(): pass\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # Import a package that does not exist in any Python environment
    (tests_dir / "test_service.py").write_text(
        "import nonexistent_package_xyz_987654321\n"
        "from src.service import run\n"
        "def test_service(): run()\n",
        encoding="utf-8",
    )

    res = await run_test_suite_hook(tmp_path, ["src/service.py"])
    assert res.status in (VerifyStatus.ERROR, VerifyStatus.SKIPPED)
    assert res.status != VerifyStatus.FAILED

    verdict = compute_verdict([res], {"changed_files": ["src/service.py"]})
    assert verdict.state == VerdictState.UNVERIFIED
    assert verdict.state != VerdictState.FAILED

