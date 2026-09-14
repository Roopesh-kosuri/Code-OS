"""
backend/tests/test_aud_015_macos_gatekeeper.py

Phase 10.5: macOS Gatekeeper Hardening Regression Tests
Tests:
- test_mac_builder_hardened_runtime_and_entitlements
- test_mac_notarize_config_uses_env_refs
- test_entitlements_plist_valid_xml_required_keys
- test_release_guard_rejects_unsigned_mac_artifact
- test_ci_mac_job_has_spctl_verify_step
"""

import json
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ELECTRON_BUILDER_PATH = ROOT_DIR / "electron-builder.yml"
ENTITLEMENTS_PATH = ROOT_DIR / "build" / "entitlements.mac.plist"
ENTITLEMENTS_INHERIT_PATH = ROOT_DIR / "build" / "entitlements.mac.inherit.plist"
CI_WORKFLOW_PATH = ROOT_DIR / ".github" / "workflows" / "ci.yml"
RELEASE_GUARD_SCRIPT = ROOT_DIR / "scripts" / "release-guard.js"
MACOS_DOCS_PATH = ROOT_DIR / "docs" / "macos-install.md"


def test_mac_builder_hardened_runtime_and_entitlements():
    """E1: electron-builder mac block specifies hardenedRuntime, gatekeeperAssess, entitlements, dmg+zip."""
    assert ELECTRON_BUILDER_PATH.exists(), f"Missing {ELECTRON_BUILDER_PATH}"
    with open(ELECTRON_BUILDER_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert "mac" in cfg, "electron-builder.yml must contain 'mac' block"
    mac = cfg["mac"]

    assert mac.get("hardenedRuntime") is True, "mac.hardenedRuntime must be true"
    assert mac.get("gatekeeperAssess") is False, "mac.gatekeeperAssess must be false"
    assert mac.get("entitlements") == "build/entitlements.mac.plist", "mac.entitlements must point to build/entitlements.mac.plist"
    assert mac.get("entitlementsInherit") == "build/entitlements.mac.inherit.plist", "mac.entitlementsInherit must point to build/entitlements.mac.inherit.plist"

    # Targets must include both dmg and zip
    targets = [t.get("target") if isinstance(t, dict) else t for t in mac.get("target", [])]
    assert "dmg" in targets, "mac.target must include dmg"
    assert "zip" in targets, "mac.target must include zip (required for notarized auto-updates)"


def test_mac_notarize_config_uses_env_refs():
    """E1: electron-builder mac block configures notarize referencing APPLE_TEAM_ID, APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD."""
    assert ELECTRON_BUILDER_PATH.exists()
    with open(ELECTRON_BUILDER_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    mac = cfg.get("mac", {})
    mac_str = json.dumps(mac)

    assert "APPLE_TEAM_ID" in mac_str, "mac config must reference APPLE_TEAM_ID"
    assert "APPLE_ID" in mac_str, "mac config must reference APPLE_ID"
    assert "APPLE_APP_SPECIFIC_PASSWORD" in mac_str, "mac config must reference APPLE_APP_SPECIFIC_PASSWORD"


def test_entitlements_plist_valid_xml_required_keys():
    """E1: entitlements plist files are valid XML and contain all required Electron keys."""
    assert ENTITLEMENTS_PATH.exists(), f"Missing {ENTITLEMENTS_PATH}"
    assert ENTITLEMENTS_INHERIT_PATH.exists(), f"Missing {ENTITLEMENTS_INHERIT_PATH}"

    with open(ENTITLEMENTS_PATH, "rb") as f:
        plist_main = plistlib.load(f)

    with open(ENTITLEMENTS_INHERIT_PATH, "rb") as f:
        plist_inherit = plistlib.load(f)

    required_keys = [
        "com.apple.security.cs.allow-jit",
        "com.apple.security.cs.allow-unsigned-executable-memory",
        "com.apple.security.cs.disable-library-validation",
        "com.apple.security.network.client",
        "com.apple.security.network.server",
        "com.apple.security.device.audio-input",
    ]

    for key in required_keys:
        assert plist_main.get(key) is True, f"Main entitlements missing {key}"
        assert plist_inherit.get(key) is True, f"Inherit entitlements missing {key}"

    assert plist_inherit.get("com.apple.security.inherit") is True, "Inherit entitlements must specify com.apple.security.inherit"


def test_release_guard_rejects_unsigned_mac_artifact():
    """E2 & E5: Release guard script refuses unsigned mac artifact when channel=release."""
    assert RELEASE_GUARD_SCRIPT.exists(), f"Missing {RELEASE_GUARD_SCRIPT}"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create an unsigned dev artifact
        artifact = Path(tmpdir) / "CODE OS-5.0.0-mac-arm64-UNSIGNED-DEV.dmg"
        artifact.write_bytes(b"dummy dmg content")

        # 1. Reject on channel=release
        proc_release = subprocess.run(
            ["node", str(RELEASE_GUARD_SCRIPT), f"--channel=release", tmpdir],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
        )
        assert proc_release.returncode == 1, "Release guard must reject UNSIGNED-DEV on channel=release"
        assert "BLOCKED publish" in (proc_release.stdout + proc_release.stderr)

        # 2. Allow on channel=dev
        proc_dev = subprocess.run(
            ["node", str(RELEASE_GUARD_SCRIPT), f"--channel=dev", tmpdir],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
        )
        assert proc_dev.returncode == 0, "Release guard should permit UNSIGNED-DEV on non-release channel"
        assert "Allowed for development" in (proc_dev.stdout + proc_dev.stderr)


def test_ci_mac_job_has_spctl_verify_step():
    """E3: CI mac job builds, signs, notarizes, and runs spctl verification step."""
    assert CI_WORKFLOW_PATH.exists()
    with open(CI_WORKFLOW_PATH, "r", encoding="utf-8") as f:
        ci_yaml = yaml.safe_load(f)

    jobs = ci_yaml.get("jobs", {})
    # Find mac job
    mac_job = None
    for j_id, j_def in jobs.items():
        if j_def.get("runs-on") == "macos-latest":
            mac_job = j_def
            break

    assert mac_job is not None, "ci.yml must contain a job with runs-on: macos-latest"

    steps = mac_job.get("steps", [])
    spctl_steps = [s for s in steps if "spctl" in s.get("run", "")]
    assert len(spctl_steps) > 0, "macOS CI job must contain a step running spctl verification"

    spctl_step = spctl_steps[0]
    assert spctl_step.get("continue-on-error") is False, "spctl verification step must fail the job on error"

    # Verify secrets are wired
    job_str = json.dumps(mac_job)
    for secret in ["CSC_LINK", "CSC_KEY_PASSWORD", "APPLE_ID", "APPLE_APP_SPECIFIC_PASSWORD", "APPLE_TEAM_ID"]:
        assert secret in job_str, f"macOS CI job must wire secret '{secret}'"
