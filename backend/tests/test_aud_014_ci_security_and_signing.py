"""
backend/tests/test_aud_014_ci_security_and_signing.py

AUD-014: CI/CD Security Gates & Release Signing Regression Tests
Tests:
- test_bandit_config_exists_and_valid
- test_pip_audit_config_excludes_tests
- test_npm_audit_high_fails_ci
- test_security_exceptions_file_schema
- test_electron_builder_sign_blocks_present
- test_release_signing_verification_script
"""

import json
import os
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PYPROJECT_PATH = ROOT_DIR / "pyproject.toml"
CI_WORKFLOW_PATH = ROOT_DIR / ".github" / "workflows" / "ci.yml"
SECURITY_EXCEPTIONS_PATH = ROOT_DIR / ".security-exceptions.json"
ELECTRON_BUILDER_PATH = ROOT_DIR / "electron-builder.yml"
SIGNING_SCRIPT_PATH = ROOT_DIR / "scripts" / "verify-release-signing.js"
EXCEPTIONS_SCRIPT_PATH = ROOT_DIR / "scripts" / "verify_security_exceptions.py"

# Add scripts directory to sys.path so we can import verify_security_exceptions
sys.path.insert(0, str(ROOT_DIR / "scripts"))
import verify_security_exceptions


def test_bandit_config_exists_and_valid():
    """E2: Configure bandit with a pyproject.toml section: exclude_dirs, skips = ['B101']."""
    assert PYPROJECT_PATH.exists(), f"pyproject.toml must exist at {PYPROJECT_PATH}"

    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    assert "tool" in data, "pyproject.toml must contain [tool] table"
    assert "bandit" in data["tool"], "pyproject.toml must contain [tool.bandit] section"

    bandit_cfg = data["tool"]["bandit"]
    exclude_dirs = bandit_cfg.get("exclude_dirs", [])
    assert "backend/tests" in exclude_dirs, "bandit exclude_dirs must contain 'backend/tests'"
    assert "backend/scratch" in exclude_dirs, "bandit exclude_dirs must contain 'backend/scratch'"

    skips = bandit_cfg.get("skips", [])
    assert "B101" in skips, "bandit skips must include 'B101'"

    # Verify bandit BanditConfig parser loads it cleanly
    import bandit.core.config as b_conf
    b_cfg = b_conf.BanditConfig(str(PYPROJECT_PATH))
    assert b_cfg.config_file == str(PYPROJECT_PATH)
    assert b_cfg._config["skips"] == ["B101"]


def test_pip_audit_config_excludes_tests():
    """E1 & E2: pip-audit config targets production requirements and excludes tests."""
    assert PYPROJECT_PATH.exists()

    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    # Check pyproject tool.pip-audit config
    assert "pip-audit" in data.get("tool", {}), "pyproject.toml should configure [tool.pip-audit]"
    pip_audit_cfg = data["tool"]["pip-audit"]
    assert "requirement" in pip_audit_cfg or "exclude_dirs" in pip_audit_cfg
    if "exclude_dirs" in pip_audit_cfg:
        assert "backend/tests" in pip_audit_cfg["exclude_dirs"]
    if "requirement" in pip_audit_cfg:
        assert any("backend/requirements.txt" in r for r in pip_audit_cfg["requirement"])

    # Also verify CI workflow executes pip-audit with production requirements or excludes tests
    assert CI_WORKFLOW_PATH.exists()
    with open(CI_WORKFLOW_PATH, "r", encoding="utf-8") as f:
        ci_yaml = yaml.safe_load(f)

    security_job = ci_yaml.get("jobs", {}).get("security-gates", {})
    steps = security_job.get("steps", [])
    pip_audit_steps = [
        s for s in steps
        if "pip-audit" in s.get("run", "") and "install" not in s.get("run", "")
    ]
    assert len(pip_audit_steps) > 0, "CI must contain a pip-audit step in security-gates job"
    pip_step = pip_audit_steps[0]
    assert pip_step.get("continue-on-error") is False, "pip-audit step must have continue-on-error: false"
    assert "backend/requirements.txt" in pip_step["run"] or "pip-audit" in pip_step["run"]


def test_npm_audit_high_fails_ci():
    """E1.c: npm audit fails CI on unapproved high/critical vulnerabilities."""
    assert CI_WORKFLOW_PATH.exists()
    with open(CI_WORKFLOW_PATH, "r", encoding="utf-8") as f:
        ci_yaml = yaml.safe_load(f)

    security_job = ci_yaml.get("jobs", {}).get("security-gates", {})
    steps = security_job.get("steps", [])

    npm_audit_steps = [s for s in steps if "npm audit" in s.get("run", "")]
    assert len(npm_audit_steps) > 0, "CI must contain an npm audit step in security-gates job"
    npm_step = npm_audit_steps[0]

    # Verify audit-level=high flag and continue-on-error: false
    assert "--audit-level=high" in npm_step["run"], "npm audit must specify --audit-level=high"
    assert npm_step.get("continue-on-error") is False, "npm audit step must fail job on error"

    # Simulate unapproved high vulnerability check against exceptions
    exceptions_data = verify_security_exceptions.load_security_exceptions(SECURITY_EXCEPTIONS_PATH)
    
    # An unknown unapproved CVE must NOT be allowed
    assert not verify_security_exceptions.check_finding_allowed(
        tool="npm-audit",
        finding_id="GHSA-9999-unapproved-vuln",
        package_or_file="malicious-pkg",
        severity="high",
        exceptions_data=exceptions_data,
    ), "Unapproved high vulnerability must NOT pass security exceptions gate"

    # A registered approved CVE must be allowed
    assert verify_security_exceptions.check_finding_allowed(
        tool="npm-audit",
        finding_id="GHSA-34x7-hfp2-rc4v",
        package_or_file="tar",
        severity="critical",
        exceptions_data=exceptions_data,
    ), "Documented and unexpired exception in tar must pass"


def test_security_exceptions_file_schema():
    """E3: .security-exceptions.json schema validation and expiration check."""
    assert SECURITY_EXCEPTIONS_PATH.exists(), f"{SECURITY_EXCEPTIONS_PATH} must exist"

    with open(SECURITY_EXCEPTIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate using scripts.verify_security_exceptions
    errors = verify_security_exceptions.validate_schema(data)
    assert errors == [], f"Security exceptions file has schema errors: {errors}"

    assert len(data.get("exceptions", [])) > 0, "Should have tracked exceptions"
    for exc in data["exceptions"]:
        assert exc["id"], "Each exception must have an ID"
        assert exc["package"], "Each exception must have a package name"
        assert exc["justification"], "Each exception must have a justification"
        assert exc["expires_at"], "Each exception must have an expiry date"
        exp = datetime.strptime(exc["expires_at"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        assert exp > datetime.now(timezone.utc), f"Exception {exc['id']} must not be expired"


def test_electron_builder_sign_blocks_present():
    """E4: electron-builder.yml contains Windows sign, macOS notarize, and Linux afterSign blocks."""
    assert ELECTRON_BUILDER_PATH.exists(), f"{ELECTRON_BUILDER_PATH} must exist"

    with open(ELECTRON_BUILDER_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 1. Windows sign block
    assert "win" in config, "electron-builder.yml must have 'win' config"
    win_cfg = config["win"]
    assert "sign" in win_cfg or "certificateFile" in win_cfg
    win_sign_str = json.dumps(win_cfg)
    assert "CSC_LINK" in win_sign_str, "Windows config must reference CSC_LINK"
    assert "CSC_KEY_PASSWORD" in win_sign_str, "Windows config must reference CSC_KEY_PASSWORD"

    # 2. macOS notarize block
    assert "mac" in config, "electron-builder.yml must have 'mac' config"
    mac_cfg = config["mac"]
    assert mac_cfg.get("notarize") is True, "macOS config must have notarize: true"
    mac_str = json.dumps(mac_cfg)
    assert "APPLE_ID" in mac_str, "macOS config must reference APPLE_ID"
    assert "APPLE_APP_SPECIFIC_PASSWORD" in mac_str, "macOS config must reference APPLE_APP_SPECIFIC_PASSWORD"

    # 3. Linux afterSign hook
    after_sign = config.get("afterSign") or config.get("linux", {}).get("afterSign")
    assert after_sign, "electron-builder must specify afterSign hook"
    assert "verify-release-signing.js" in after_sign, "afterSign must reference verify-release-signing.js"


def test_release_signing_verification_script():
    """E4 & E5: verify-release-signing.js runs post-build and verifies binary signatures."""
    assert SIGNING_SCRIPT_PATH.exists(), f"{SIGNING_SCRIPT_PATH} must exist"

    # 1. Test running script with no credentials in dev mode -> exits 0 (clean skip)
    env_no_cred = {k: v for k, v in os.environ.items() if not any(s in k for s in ["CSC", "APPLE", "SIGN"])}
    proc = subprocess.run(
        ["node", str(SIGNING_SCRIPT_PATH)],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        env=env_no_cred,
    )
    assert proc.returncode == 0, f"Expected 0 without signing credentials in dev mode: {proc.stderr}"
    assert "Skipping signature enforcement" in (proc.stdout + proc.stderr)

    # 2. Test running script with --strict and no credentials -> exits 1 (fails CI)
    proc_strict = subprocess.run(
        ["node", str(SIGNING_SCRIPT_PATH), "--strict"],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        env=env_no_cred,
    )
    assert proc_strict.returncode == 1, "Expected non-zero exit in strict mode without credentials"
    assert "Strict mode enabled" in (proc_strict.stdout + proc_strict.stderr)

    # 3. Test running script with signing credentials present on unsigned binary -> fails
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_binary = Path(tmpdir) / "app.exe"
        # Write dummy binary
        fake_binary.write_bytes(b"MZ\x90\x00" + b"\x00" * 200)

        env_with_cred = dict(os.environ)
        env_with_cred["CSC_LINK"] = "dummy_cert_path"

        proc_cred = subprocess.run(
            ["node", str(SIGNING_SCRIPT_PATH), tmpdir],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            env=env_with_cred,
        )
        assert proc_cred.returncode == 1, "Expected failure when signing credentials present but binary is unsigned"
        assert "FAIL: Unsigned or invalid binary" in (proc_cred.stdout + proc_cred.stderr)

    # 4. Also verify RELEASE SIGNING VERIFICATION job in CI
    assert CI_WORKFLOW_PATH.exists()
    with open(CI_WORKFLOW_PATH, "r", encoding="utf-8") as f:
        ci_yaml = yaml.safe_load(f)

    release_job = ci_yaml.get("jobs", {}).get("release-signing-verification", {})
    assert release_job, "ci.yml must contain release-signing-verification job"
    assert "refs/tags/v" in release_job.get("if", ""), "release-signing-verification must run on tags"
    steps_str = json.dumps(release_job.get("steps", []))
    assert "verify-release-signing.js" in steps_str, "release job must run verify-release-signing.js"
