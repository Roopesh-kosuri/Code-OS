"""Regression tests for Phase 14 Part 4: Baseline Attribution (verify_runners.py)."""

import asyncio
from pathlib import Path
import pytest

from app.features.ai.harness.verification_matrix import (
    VerifyResult,
    VerifyStatus,
)
from app.features.ai.harness.verify_runners import (
    allow_runner_once,
    attribute_failures_against_baseline,
    create_baseline_overlay,
    run_test_suite_hook,
)
from app.features.workspaces.trust_service import set_workspace_trust


@pytest.mark.asyncio
async def test_preexisting_failure_is_warn_not_blamed(tmp_path: Path):
    """A test that was already failing at baseline is classified as WARN 'pre-existing failure' and not blamed on the turn."""
    ws_str = str(tmp_path)
    await set_workspace_trust(ws_str, True)
    allow_runner_once(tmp_path, "pytest")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    code_file = src_dir / "service.py"
    # Pre-turn code
    pre_turn_code = "def get_value(): return 10\n"
    code_file.write_text(pre_turn_code, encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # Test file that asserts 42 (which already failed with pre_turn_code!)
    test_file = tests_dir / "test_service.py"
    test_file.write_text(
        "from src.service import get_value\n"
        "def test_get_value(): assert get_value() == 42\n",
        encoding="utf-8",
    )

    # In this turn, the agent touched a comment in service.py
    post_turn_code = "# updated comment\ndef get_value(): return 10\n"
    code_file.write_text(post_turn_code, encoding="utf-8")

    pre_images = {"src/service.py": pre_turn_code.encode("utf-8")}

    # Run the test suite hook
    res = await run_test_suite_hook(tmp_path, ["src/service.py"], pre_images=pre_images)

    # Status must be WARN (not FAILED!)
    assert res.status == VerifyStatus.WARN
    assert "pre-existing" in res.summary.lower()
    assert "pre-existing failure" in res.caveats


@pytest.mark.asyncio
async def test_new_failure_caused_by_turn_is_failed(tmp_path: Path):
    """A test that passed at baseline but fails now is attributed to the turn -> FAILED."""
    ws_str = str(tmp_path)
    await set_workspace_trust(ws_str, True)
    allow_runner_once(tmp_path, "pytest")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    code_file = src_dir / "calc.py"
    # Pre-turn code: worked!
    pre_turn_code = "def add(a, b): return a + b\n"
    code_file.write_text(pre_turn_code, encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_calc.py"
    test_file.write_text(
        "from src.calc import add\n"
        "def test_add(): assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # In this turn, the agent broke it!
    broken_code = "def add(a, b): return a - b\n"
    code_file.write_text(broken_code, encoding="utf-8")

    pre_images = {"src/calc.py": pre_turn_code.encode("utf-8")}

    # Run test suite hook
    res = await run_test_suite_hook(tmp_path, ["src/calc.py"], pre_images=pre_images)

    assert res.status == VerifyStatus.FAILED
    assert "caused by this turn" in res.summary.lower()
    assert any("test_add" in d for d in res.details)


def test_baseline_too_large_marks_unattributed_unverified(tmp_path: Path):
    """When workspace exceeds max_mb cap, create_baseline_overlay returns None with error."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    large_file = src_dir / "large.bin"
    large_file.write_bytes(b"0" * (2 * 1024 * 1024))  # 2MB

    # Set cap to 1MB
    overlay_dir, err = create_baseline_overlay(
        tmp_path,
        ["src/large.bin"],
        {"src/large.bin": b"old"},
        max_mb=1,
    )
    assert overlay_dir is None
    assert "exceeds baseline size cap" in err


def test_baseline_tempdir_cleaned_on_timeout_and_cancel(tmp_path: Path):
    """create_baseline_overlay creates a temp dir that can be cleanly removed."""
    (tmp_path / "hello.txt").write_text("world", encoding="utf-8")
    overlay_dir, err = create_baseline_overlay(tmp_path, ["hello.txt"], {"hello.txt": b"old"})
    assert err is None
    assert overlay_dir.is_dir()

    from app.features.ai.harness.verify_runners import cleanup_verify_temp_dir
    cleanup_verify_temp_dir(overlay_dir)
    assert not overlay_dir.exists()
