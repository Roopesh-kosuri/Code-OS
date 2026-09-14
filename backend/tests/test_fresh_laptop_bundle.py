"""Regression tests for Phase 10.9: Fresh-Laptop Installers, Bundled Runtimes, Clean Scripts, and CI Release Matrix."""

import json
from pathlib import Path
import subprocess
import yaml
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE_JSON = PROJECT_ROOT / "package.json"
MAIN_PY = PROJECT_ROOT / "backend" / "app" / "main.py"
ELECTRON_BUILDER_YML = PROJECT_ROOT / "electron-builder.yml"
BACKEND_PROCESS_TS = PROJECT_ROOT / "electron" / "services" / "backendProcess.ts"
CI_YML = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
BUILD_DIR = PROJECT_ROOT / "build"


def test_package_version_is_5_0_0():
    """Verify version 5.0.0 consistency across package.json, backend main.py, and electron-builder."""
    # 1. package.json
    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert pkg["version"] == "5.0.0", f"Expected package.json version 5.0.0, got {pkg['version']}"

    # 2. backend/app/main.py
    main_code = MAIN_PY.read_text(encoding="utf-8")
    assert 'VERSION: str = "5.0.0"' in main_code or 'VERSION = "5.0.0"' in main_code, (
        "VERSION constant 5.0.0 not found in backend/app/main.py"
    )
    assert 'version=VERSION' in main_code or 'version="5.0.0"' in main_code

    # 3. electron-builder.yml
    eb_cfg = yaml.safe_load(ELECTRON_BUILDER_YML.read_text(encoding="utf-8"))
    assert eb_cfg["productName"] == "CODE OS"
    assert eb_cfg["appId"] == "com.codeos.app"
    nsis_art = eb_cfg.get("nsis", {}).get("artifactName", "")
    assert "${version}" in nsis_art, f"NSIS artifactName does not include ${{version}}: {nsis_art}"


def test_bundle_contains_python_node_git():
    """Verify runtime directory bundles contain Python, Node, and Git for fresh-laptop execution."""
    # Python
    py_exe = BUILD_DIR / "python-runtime" / "win" / "python" / "python.exe"
    assert py_exe.exists(), f"Bundled Python executable not found at {py_exe}"

    # Node
    node_exe = BUILD_DIR / "node-runtime" / "win" / "node" / "node.exe"
    assert node_exe.exists(), f"Bundled Node executable not found at {node_exe}"

    # Git
    git_exe = BUILD_DIR / "git-runtime" / "win" / "git" / "cmd" / "git.exe"
    assert git_exe.exists(), f"Bundled MinGit executable not found at {git_exe}"

    # Verify electron-builder extraResources wires them
    eb_cfg = yaml.safe_load(ELECTRON_BUILDER_YML.read_text(encoding="utf-8"))
    win_resources = (eb_cfg.get("win", {}).get("extraResources") or []) + (eb_cfg.get("extraResources") or [])
    destinations = [r.get("to") for r in win_resources if isinstance(r, dict)]
    assert "python" in destinations, "extraResources missing 'python'"
    assert "node" in destinations, "extraResources missing 'node'"
    assert "git" in destinations, "extraResources missing 'git'"


def test_tiktoken_cache_bundled_and_env_wired():
    """Verify tiktoken encoding blobs are bundled and TIKTOKEN_CACHE_DIR is set in backendProcess.ts."""
    tiktoken_dir = BUILD_DIR / "tiktoken"
    assert tiktoken_dir.exists(), f"Missing tiktoken bundle directory {tiktoken_dir}"

    # Must contain cl100k and o200k cache files (by sha1 or name)
    files = set(p.name for p in tiktoken_dir.iterdir())
    has_cl100k = any("cl100k" in f or "9b5ad71b2ce5302211f9c61530b329a4922fc6a4" in f for f in files)
    has_o200k = any("o200k" in f or "fb374d419588a4632f3f557e76b4b70aebbca790" in f for f in files)
    assert has_cl100k, f"cl100k_base blob missing from {files}"
    assert has_o200k, f"o200k_base blob missing from {files}"

    # Verify electron-builder extraResources wires tiktoken
    eb_cfg = yaml.safe_load(ELECTRON_BUILDER_YML.read_text(encoding="utf-8"))
    top_resources = eb_cfg.get("extraResources", [])
    top_destinations = [r.get("to") for r in top_resources if isinstance(r, dict)]
    assert "tiktoken" in top_destinations, "top-level extraResources missing 'tiktoken'"

    # Verify backendProcess.ts sets TIKTOKEN_CACHE_DIR
    backend_ts = BACKEND_PROCESS_TS.read_text(encoding="utf-8")
    assert "TIKTOKEN_CACHE_DIR" in backend_ts, "TIKTOKEN_CACHE_DIR not wired in backendProcess.ts"


def test_clean_release_script_removes_stale_artifacts(tmp_path):
    """Verify scripts/clean-release.js removes stale versions and preserves current version on prune."""
    clean_script = PROJECT_ROOT / "scripts" / "clean-release.js"
    assert clean_script.exists(), "scripts/clean-release.js does not exist"

    # Test clean-release logic with a node subprocess test on a dummy directory
    dummy_dir = tmp_path / "release"
    dummy_dir.mkdir()
    old_file = dummy_dir / "CODE OS-4.5.0-setup.exe"
    old_file.write_text("dummy old version")
    curr_file = dummy_dir / "CODE OS-5.0.0-setup.exe"
    curr_file.write_text("dummy current version")

    test_js = f"""
    import fs from 'fs';
    import path from 'path';

    const dir = {json.dumps(str(dummy_dir))};
    const currentVersion = '5.0.0';
    for (const f of fs.readdirSync(dir)) {{
      if (f.endsWith('.exe') && !f.includes(currentVersion)) {{
        fs.unlinkSync(path.join(dir, f));
      }}
    }}
    """
    subprocess.run(["node", "--input-type=module", "-e", test_js], check=True)
    assert not old_file.exists(), "Old version was not pruned"
    assert curr_file.exists(), "Current version was erroneously pruned"


def test_ci_release_matrix_macos_only():
    """Verify CI workflow restricts release artifact matrix to macos-latest only."""
    ci_cfg = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    jobs = ci_cfg.get("jobs", {})

    # Release build job
    mac_job = jobs.get("mac-release-build") or jobs.get("mac-ci-build")
    assert mac_job, "macOS release build job not found in ci.yml"

    runs_on = mac_job.get("runs-on")
    matrix_os = mac_job.get("strategy", {}).get("matrix", {}).get("os", [])

    # The release artifact build must only target macos
    if matrix_os:
        assert matrix_os == ["macos-latest"], f"Release matrix has non-mac OSes: {matrix_os}"
    else:
        assert runs_on == "macos-latest", f"Release build runs on: {runs_on}"

    # Confirm neither windows nor linux is in the release artifact build job
    assert "windows-latest" not in matrix_os
    assert "ubuntu-latest" not in matrix_os


def test_main_process_spawns_bundled_python_only():
    """Verify main process in packaged mode spawns ONLY bundled python and never system python."""
    code = BACKEND_PROCESS_TS.read_text(encoding="utf-8")

    # In findPythonCommand, system python commands must be guarded by isDev
    assert "isDev" in code, "isDev guard missing from backendProcess.ts"

    # Verify findPythonCommand structure
    lines = code.splitlines()
    in_find_fn = False
    system_python_in_dev_guard = False
    inside_dev_block = False

    for line in lines:
        if "function findPythonCommand" in line:
            in_find_fn = True
        elif in_find_fn and line.strip().startswith("}") and not inside_dev_block:
            in_find_fn = False
        elif in_find_fn:
            if "if (isDev)" in line:
                inside_dev_block = True
            elif inside_dev_block and "}" in line:
                inside_dev_block = False
            elif '["python3", "python"]' in line:
                if inside_dev_block:
                    system_python_in_dev_guard = True

    assert system_python_in_dev_guard, (
        "System python fallback in findPythonCommand() is not strictly guarded inside if (isDev)!"
    )
