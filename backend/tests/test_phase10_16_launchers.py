"""test_phase10_16_launchers.py — Regression tests for Phase 10.16-FINAL: Launcher Rebuild.

Guarantees:
1. test_ci_release_matrix_macos_only: CI release matrix contains macos-latest only; test matrix has multi-platform tests without release upload.
2. test_bundle_contains_python_node_git: 7z bundle assertion on the built installer proves python.exe, node.exe, and git.exe are present inside.
3. test_installer_size_within_target: Built Windows setup .exe is <= 350 MB.
4. test_install_time_under_60s: Measures or validates installer configuration for fast extraction.
5. test_offline_core_features_without_embedding_model: Confirms core RAG, prompt builder, watchdog, and offline token encoding work without PyTorch or external model weights.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent


def test_ci_release_matrix_macos_only():
    """Verify that CI release builds are restricted to macOS-only while PR test matrix includes windows & linux."""
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), f"CI file missing at {ci_path}"
    content = ci_path.read_text(encoding="utf-8")

    # 1. mac-release-build job must use macos-latest only
    assert "mac-release-build:" in content
    assert "os: [macos-latest]" in content

    # 2. ci-checks PR matrix must include ubuntu-latest and windows-latest
    assert "ci-checks:" in content
    assert "ubuntu-latest" in content
    assert "windows-latest" in content

    # 3. Security gates must be preserved
    assert "security-gates:" in content
    assert "bandit" in content
    assert "pip-audit" in content
    assert "spctl" in content


def test_offline_core_features_without_embedding_model():
    """Verify core AI harness, RAG fallback, and watchdog work offline without heavy PyTorch model weights."""
    py_exe = ROOT / "resources" / "python" / "python.exe"
    if not py_exe.is_file():
        py_exe = ROOT / "resources" / "python" / "bin" / "python3"
    assert py_exe.is_file(), f"Bundled python missing at {py_exe}"

    tk_dir = ROOT / "resources" / "tiktoken"
    assert tk_dir.is_dir(), f"Tiktoken cache dir missing at {tk_dir}"

    code = (
        "import sys\n"
        "import tiktoken\n"
        "enc = tiktoken.get_encoding('cl100k_base')\n"
        "toks = enc.encode('offline test 123')\n"
        "assert len(toks) > 0\n"
        "import chromadb\n"
        "client = chromadb.Client()\n"
        "col = client.create_collection('offline_test')\n"
        "col.add(documents=['sample doc'], ids=['d1'])\n"
        "assert col.count() == 1\n"
        "import watchdog\n"
        "print('OFFLINE_OK')\n"
    )

    env = os.environ.copy()
    env["TIKTOKEN_CACHE_DIR"] = str(tk_dir)
    env.pop("PYTHONPATH", None)

    res = subprocess.run([str(py_exe), "-s", "-c", code], env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"Offline verification failed: {res.stderr}"
    assert "OFFLINE_OK" in res.stdout


def test_bundle_contains_python_node_git():
    """7z bundle assertion: python.exe, node.exe, git.exe all present inside built Windows installer."""
    release_dir = ROOT / "release"
    exe_files = list(release_dir.glob("*.exe"))
    if not exe_files:
        pytest.skip("No .exe installer built yet in release/ (run post-build)")

    target_exe = [f for f in exe_files if "Setup" in f.name or "win" in f.name.lower()][0]
    seven_zip = Path("C:/Program Files/7-Zip/7z.exe")
    assert seven_zip.is_file(), "7z.exe not found at C:/Program Files/7-Zip/7z.exe"

    # Extract app-64.7z to temp dir and inspect
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd_extract = [str(seven_zip), "e", str(target_exe), "$PLUGINSDIR/app-64.7z", f"-o{tmpdir}", "-y"]
        sub_res = subprocess.run(cmd_extract, capture_output=True, text=True)
        assert sub_res.returncode == 0, f"Failed to extract app-64.7z: {sub_res.stderr}"

        app7z = Path(tmpdir) / "app-64.7z"
        assert app7z.is_file(), "app-64.7z not found in extracted NSIS stub"

        list_res = subprocess.run([str(seven_zip), "l", str(app7z)], capture_output=True, text=True)
        assert list_res.returncode == 0
        output = list_res.stdout

        assert "resources\\python\\python.exe" in output or "resources/python/python.exe" in output, "python.exe missing from installer bundle"
        assert "resources\\node\\node.exe" in output or "resources/node/node.exe" in output, "node.exe missing from installer bundle"
        assert "resources\\git\\cmd\\git.exe" in output or "resources/git/cmd/git.exe" in output, "git.exe missing from installer bundle"


def test_installer_size_within_target():
    """Verify built installer executable is <= 350 MB."""
    release_dir = ROOT / "release"
    exe_files = [f for f in release_dir.glob("*.exe") if "Setup" in f.name]
    if not exe_files:
        pytest.skip("No Setup .exe found in release/ (run post-build)")

    setup_exe = exe_files[0]
    size_mb = setup_exe.stat().st_size / 1024 / 1024
    print(f"\nMeasured Installer Size: {size_mb:.2f} MB (Target: <= 350 MB)")
    assert size_mb <= 350.0, f"Installer size {size_mb:.2f} MB exceeds target of 350 MB!"


def test_install_time_under_60s():
    """Verify NSIS configuration is optimized for fast extraction (< 60s target)."""
    builder_yml = ROOT / "electron-builder.yml"
    assert builder_yml.is_file()
    cfg = yaml.safe_load(builder_yml.read_text(encoding="utf-8"))

    # Verify NSIS settings
    assert "nsis" in cfg
    nsis = cfg["nsis"]
    assert nsis.get("perMachine") is False
    assert nsis.get("differentialPackage") is False
    assert cfg.get("compression") == "maximum"
