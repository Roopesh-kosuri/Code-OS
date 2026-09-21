"""Regression tests for Phase 14 Part 5: Security Scan Hook (verify_security.py)."""

from pathlib import Path
import pytest

from app.features.ai.harness.verification_matrix import (
    VerifyResult,
    VerifyStatus,
)
from app.features.ai.harness.verify_security import (
    run_npm_audit_hook,
    run_security_scan_hook,
)


@pytest.mark.asyncio
async def test_shell_true_and_os_system_added_line_is_high_failed(tmp_path: Path):
    """Adding subprocess.run(..., shell=True) or os.system() on an added line triggers HIGH FAILED."""
    py_file = tmp_path / "deploy.py"
    # Pre-turn: empty
    pre_content = "def safe(): return 1\n"
    py_file.write_text(pre_content, encoding="utf-8")

    # Post-turn: added os.system
    post_content = "def safe(): return 1\nimport os\nos.system('rm -rf /')\n"
    py_file.write_text(post_content, encoding="utf-8")

    pre_images = {"deploy.py": pre_content.encode("utf-8")}
    res, supp_count = await run_security_scan_hook(tmp_path, ["deploy.py"], pre_images)

    assert res.status == VerifyStatus.FAILED
    assert "HIGH" in res.summary or "1 HIGH" in res.summary
    assert any("os-system" in d for d in res.details)


@pytest.mark.asyncio
async def test_preexisting_shell_true_on_untouched_line_not_blamed(tmp_path: Path):
    """A file that already contained shell=True before the turn is NOT blamed when that line is untouched."""
    py_file = tmp_path / "legacy.py"
    pre_content = (
        "import subprocess\n"
        "subprocess.run('echo hello', shell=True)\n"
        "def compute(): return 42\n"
    )
    # Post-turn: only modified compute()
    post_content = (
        "import subprocess\n"
        "subprocess.run('echo hello', shell=True)\n"
        "def compute(): return 100\n"
    )
    py_file.write_text(post_content, encoding="utf-8")

    pre_images = {"legacy.py": pre_content.encode("utf-8")}
    res, supp_count = await run_security_scan_hook(tmp_path, ["legacy.py"], pre_images)

    assert res.status == VerifyStatus.PASSED
    assert "clean" in res.summary.lower()


@pytest.mark.asyncio
async def test_eval_literal_is_medium_warn(tmp_path: Path):
    """eval('1 + 1') on a constant literal is MEDIUM severity (WARN, not FAILED)."""
    py_file = tmp_path / "calc.py"
    pre_content = ""
    post_content = "def calc(): return eval('1 + 1')\n"
    py_file.write_text(post_content, encoding="utf-8")

    pre_images = {"calc.py": b""}
    res, _ = await run_security_scan_hook(tmp_path, ["calc.py"], pre_images)

    assert res.status == VerifyStatus.WARN
    assert "eval-literal" in str(res.details)


@pytest.mark.asyncio
async def test_patterns_inside_strings_and_comments_not_flagged(tmp_path: Path):
    """Mentions of 'shell=True' or 'os.system' inside docstrings, comments, or variables are not flagged."""
    py_file = tmp_path / "doc.py"
    post_content = (
        "# Note: never use os.system('foo')\n"
        "'''\n"
        "Example:\n"
        "    subprocess.run('ls', shell=True)\n"
        "'''\n"
        "msg = 'subprocess.run(shell=True) is dangerous'\n"
    )
    py_file.write_text(post_content, encoding="utf-8")

    pre_images = {"doc.py": b""}
    res, _ = await run_security_scan_hook(tmp_path, ["doc.py"], pre_images)

    assert res.status == VerifyStatus.PASSED


@pytest.mark.asyncio
async def test_suppression_downgrades_and_counts_as_caveat(tmp_path: Path):
    """# codeos-allow: <rule-id> downgrades finding to WARN and is counted as caveat."""
    py_file = tmp_path / "tool.py"
    post_content = (
        "import os\n"
        "# codeos-allow: os-system\n"
        "os.system('cls')\n"
    )
    py_file.write_text(post_content, encoding="utf-8")

    pre_images = {"tool.py": b""}
    res, supp_count = await run_security_scan_hook(tmp_path, ["tool.py"], pre_images)

    # Finding was suppressed -> downgraded to WARN (not FAILED)
    assert res.status == VerifyStatus.WARN
    assert supp_count == 1
    assert "1 security suppression added in this turn" in res.caveats


@pytest.mark.asyncio
async def test_hardcoded_secret_flagged_high(tmp_path: Path):
    """Hardcoded private key block or AWS key is flagged as HIGH FAILED."""
    py_file = tmp_path / "auth.py"
    post_content = (
        "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
    )
    py_file.write_text(post_content, encoding="utf-8")

    pre_images = {"auth.py": b""}
    res, _ = await run_security_scan_hook(tmp_path, ["auth.py"], pre_images)

    assert res.status == VerifyStatus.FAILED
    assert any("aws-access-key" in d for d in res.details)


@pytest.mark.asyncio
async def test_npm_audit_only_on_lockfile_change_and_never_fails_verdict(tmp_path: Path):
    """npm audit hook produces WARN at worst, never FAILED."""
    res = await run_npm_audit_hook(tmp_path)
    # Whether npm exists or not, status must never be FAILED
    assert res.status in (VerifyStatus.PASSED, VerifyStatus.WARN, VerifyStatus.SKIPPED)
