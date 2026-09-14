"""Regression tests for Repo Hygiene: Internal Docs Untracked & Excluded."""

from pathlib import Path
import subprocess
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

INTERNAL_PATHS = [
    "docs/audit/EXPECTED_VS_ACTUAL.md",
    "docs/audit/FINDINGS_REGISTER.md",
    "docs/audit/FIX_PLAN.md",
    "PHASE_STATE.md",
    "docs/TEAM_CONSOLE_AUDIT.md",
    "docs/SYSTEM_VERIFICATION_REPORT.md",
    "docs/V4_FINAL_VERIFICATION_REPORT.md",
    "docs/CODEX_CURRENT_ERRORS.md",
    "docs/CODEX_HANDOFF.md",
    "docs/CODE_SIGNING_PLAN.md",
    "docs/PRE_COMMIT_CHECKLIST.md",
    "docs/RELEASE_CLEANUP.md",
]

PUBLIC_TRACKED_PATHS = [
    "docs/macos-install.md",
    "docs/release-process.md",
    ".security-exceptions.json",
    "CHANGELOG.md",
]


def test_gitignore_covers_internal_docs():
    """Assert all internal documents are covered by .gitignore AND absent from git ls-files."""
    # 1. Check that git ls-files contains none of the internal paths
    proc_ls = subprocess.run(
        ["git", "ls-files"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = set(proc_ls.stdout.splitlines())

    for internal in INTERNAL_PATHS:
        normalized = internal.replace("\\", "/")
        assert normalized not in tracked_files, (
            f"Internal document '{normalized}' is still tracked in git ls-files!"
        )

    # 2. Check that git check-ignore matches all internal paths
    for internal in INTERNAL_PATHS:
        proc_ignore = subprocess.run(
            ["git", "check-ignore", internal],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert proc_ignore.returncode == 0, (
            f"Internal path '{internal}' is not ignored by .gitignore!"
        )

    # 3. Check that local copies were preserved on disk (not destroyed)
    for internal in INTERNAL_PATHS:
        file_path = PROJECT_ROOT / internal
        assert file_path.exists(), (
            f"Internal file '{internal}' was unexpectedly deleted from local filesystem!"
        )

    # 4. Check that public release/security files remain tracked or stageable
    for public_path in PUBLIC_TRACKED_PATHS:
        assert (PROJECT_ROOT / public_path).exists(), f"Missing public doc {public_path}"
        # Public files must NOT be ignored
        proc_pub_ignore = subprocess.run(
            ["git", "check-ignore", public_path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert proc_pub_ignore.returncode != 0, (
            f"Public document '{public_path}' was accidentally ignored!"
        )
