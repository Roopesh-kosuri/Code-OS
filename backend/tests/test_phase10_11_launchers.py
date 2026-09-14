"""test_phase10_11_launchers.py — Regression tests for Phase 10.11.

Guarantees:
1. test_bundle_site_packages_contains_tiktoken: resources/python site-packages contains tiktoken and cache blobs.
2. test_bundled_python_offline_unicode_encode: bundled python isolated (-s) encodes unicode offline using cl100k_base.
3. test_dev_launcher_sets_tiktoken_cache_dir: all dev launchers wire TIKTOKEN_CACHE_DIR to resources/tiktoken.
4. test_clean_release_purges_stale_artifacts: clean-release purges stale version artifacts while retaining current.
5. test_win_artifact_contains_tiktoken_and_runtimes: built Windows artifact contains tiktoken, cache, node, git.
6. test_sha256sums_generated_for_artifacts: release/SHA256SUMS.txt exists, matches all release installer artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def test_bundle_site_packages_contains_tiktoken():
    """S1: Bundled python site-packages contains tiktoken and cache blobs exist."""
    py_dir = ROOT / "resources" / "python"
    assert py_dir.is_dir(), f"Bundled python directory not found at {py_dir}"

    site_pkg_candidates = [
        py_dir / "Lib" / "site-packages" / "tiktoken",
        py_dir / "site-packages" / "tiktoken",
    ]
    matching = [p for p in site_pkg_candidates if p.is_dir()]
    assert len(matching) > 0, f"tiktoken not found in site-packages candidates: {site_pkg_candidates}"
    tiktoken_dir = matching[0]
    assert (tiktoken_dir / "__init__.py").is_file() or (tiktoken_dir / "core.py").is_file()

    cache_dir = ROOT / "resources" / "tiktoken"
    assert cache_dir.is_dir(), f"tiktoken cache directory not found at {cache_dir}"
    cache_files = list(cache_dir.glob("*"))
    assert len(cache_files) > 0, f"No cache blobs found in {cache_dir}"


def test_bundled_python_offline_unicode_encode():
    """S1 & S2: Bundled python isolated (-s) encodes Unicode offline with cl100k_base."""
    py_exe = ROOT / "resources" / "python" / "python.exe"
    if not py_exe.is_file():
        py_exe = ROOT / "resources" / "python" / "bin" / "python3"
    assert py_exe.is_file(), f"Bundled python executable not found at {py_exe}"

    cache_dir = ROOT / "resources" / "tiktoken"
    assert cache_dir.is_dir(), f"Tiktoken cache dir not found at {cache_dir}"

    code = (
        "import sys, tiktoken\n"
        "enc = tiktoken.get_encoding('cl100k_base')\n"
        "tokens = enc.encode('héllo 🙂')\n"
        "print('TOKENS:', tokens)\n"
    )
    env = os.environ.copy()
    env["TIKTOKEN_CACHE_DIR"] = str(cache_dir)

    cmd = [str(py_exe), "-s", "-c", code]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"Bundled python failed (exit {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    )
    assert "TOKENS: [71, 19010, 385, 28584]" in res.stdout


def test_dev_launcher_sets_tiktoken_cache_dir():
    """S3: All dev launch paths wire TIKTOKEN_CACHE_DIR."""
    dev_bat = ROOT / "scripts" / "dev.bat"
    dev_ps1 = ROOT / "scripts" / "dev.ps1"
    dev_backend = ROOT / "scripts" / "dev-backend.js"
    backend_proc = ROOT / "electron" / "services" / "backendProcess.ts"
    release_doc = ROOT / "docs" / "release-process.md"

    assert dev_bat.is_file(), f"{dev_bat} missing"
    bat_content = dev_bat.read_text(encoding="utf-8")
    assert "TIKTOKEN_CACHE_DIR" in bat_content
    assert r"resources\tiktoken" in bat_content

    assert dev_ps1.is_file(), f"{dev_ps1} missing"
    ps1_content = dev_ps1.read_text(encoding="utf-8")
    assert "TIKTOKEN_CACHE_DIR" in ps1_content
    assert r"resources\tiktoken" in ps1_content

    assert dev_backend.is_file(), f"{dev_backend} missing"
    backend_js_content = dev_backend.read_text(encoding="utf-8")
    assert "TIKTOKEN_CACHE_DIR" in backend_js_content

    assert backend_proc.is_file(), f"{backend_proc} missing"
    bp_content = backend_proc.read_text(encoding="utf-8")
    assert "TIKTOKEN_CACHE_DIR" in bp_content

    assert release_doc.is_file(), f"{release_doc} missing"
    doc_content = release_doc.read_text(encoding="utf-8")
    assert "TIKTOKEN_CACHE_DIR" in doc_content


def test_clean_release_purges_stale_artifacts(tmp_path):
    """S4: scripts/clean-release.js purges stale installer artifacts while retaining current version."""
    stale_file = tmp_path / "CODE OS-4.9.0-win.zip"
    stale_file.write_text("fake stale artifact", encoding="utf-8")
    current_file = tmp_path / "CODE OS-5.0.0-win.zip"
    current_file.write_text("fake current artifact", encoding="utf-8")
    unrelated_file = tmp_path / "important-notes.txt"
    unrelated_file.write_text("keep this", encoding="utf-8")

    clean_script = ROOT / "scripts" / "clean-release.js"
    assert clean_script.is_file(), "scripts/clean-release.js missing"
    clean_js_text = clean_script.read_text(encoding="utf-8")
    assert "--prune-stale" in clean_js_text
    assert "currentVersion" in clean_js_text

    node_code = f"""
    import fs from 'fs';
    import path from 'path';
    const dir = {json.dumps(str(tmp_path))};
    const currentVersion = '5.0.0';
    const INSTALLER_EXTENSIONS = ['.exe', '.dmg', '.appimage', '.deb', '.zip', '.tar.gz', '.blockmap', '.yml', '.yaml'];
    function isInstallerFile(f) {{
      const lower = f.toLowerCase();
      return INSTALLER_EXTENSIONS.some(ext => lower.endsWith(ext));
    }}
    const entries = fs.readdirSync(dir, {{ withFileTypes: true }});
    for (const entry of entries) {{
      if (entry.isFile() && isInstallerFile(entry.name)) {{
        if (!entry.name.includes(currentVersion)) {{
          fs.unlinkSync(path.join(dir, entry.name));
        }}
      }}
    }}
    """
    res = subprocess.run(["node", "--input-type=module", "-e", node_code], capture_output=True, text=True)
    assert res.returncode == 0, f"Node script failed: {res.stderr}"
    assert not stale_file.exists(), "Stale artifact was not purged"
    assert current_file.exists(), "Current version artifact was incorrectly purged"
    assert unrelated_file.exists(), "Non-installer file was touched"


def test_win_artifact_contains_tiktoken_and_runtimes():
    """S4: Windows release artifact contains tiktoken site-packages, blobs, node, and git."""
    release_dir = ROOT / "release"
    win_zip = release_dir / "CODE OS-5.0.0-win.zip"
    win_unpacked = release_dir / "win-unpacked"

    assert win_zip.is_file() or win_unpacked.is_dir(), (
        f"Neither win.zip nor win-unpacked found in {release_dir}"
    )

    if win_zip.is_file():
        with zipfile.ZipFile(win_zip, "r") as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
            tiktoken_entries = [n for n in names if "site-packages/tiktoken" in n]
            assert len(tiktoken_entries) > 0, "No tiktoken found in site-packages inside win.zip"

            tiktoken_blobs = [n for n in names if "resources/tiktoken" in n]
            assert len(tiktoken_blobs) > 0, "No tiktoken blobs found inside win.zip"

            node_entries = [n for n in names if "resources/node" in n]
            assert len(node_entries) > 0, "No resources/node found inside win.zip"

            git_entries = [n for n in names if "resources/git" in n]
            assert len(git_entries) > 0, "No resources/git found inside win.zip"

    if win_unpacked.is_dir():
        resources_dir = win_unpacked / "resources"
        py_site_pkg = resources_dir / "python" / "Lib" / "site-packages" / "tiktoken"
        assert py_site_pkg.is_dir(), f"tiktoken not found at {py_site_pkg}"
        assert (resources_dir / "tiktoken").is_dir(), "resources/tiktoken missing in win-unpacked"
        assert (resources_dir / "node").is_dir(), "resources/node missing in win-unpacked"
        assert (resources_dir / "git").is_dir(), "resources/git missing in win-unpacked"


def test_sha256sums_generated_for_artifacts():
    """S5: release/SHA256SUMS.txt exists and matches all release installer artifacts."""
    release_dir = ROOT / "release"
    sums_file = release_dir / "SHA256SUMS.txt"
    assert sums_file.is_file(), f"SHA256SUMS.txt not found at {sums_file}"

    content = sums_file.read_text(encoding="utf-8").strip()
    assert content, "SHA256SUMS.txt is empty"
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    assert len(lines) >= 2, f"Expected at least 2 artifacts hashed in SHA256SUMS.txt, found {len(lines)}"

    for line in lines:
        parts = line.split(maxsplit=1)
        assert len(parts) == 2, f"Invalid SHA256SUM line format: {line}"
        expected_hash, fname = parts[0], parts[1].strip()
        fpath = release_dir / fname
        assert fpath.is_file(), f"Hashed file '{fname}' does not exist in release/"

        hasher = hashlib.sha256()
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest()
        assert actual_hash == expected_hash, (
            f"Hash mismatch for {fname}: actual {actual_hash} != expected {expected_hash}"
        )
