#!/usr/bin/env python3
"""verify_bundle_runtime.py — Post-bundle runtime verification & build gate.

Runs the BUNDLED python (never system python), bundled git, and bundled node.
Asserts:
  1. Bundled Python imports tiktoken.
  2. Offline Unicode encode via bundled TIKTOKEN_CACHE_DIR blobs.
  3. Bundled Python imports watchdog.
  4. Bundled Python imports chromadb.
  5. Bundled git --version succeeds.
  6. Bundled node --version succeeds.

ANY failure exits with code 1, failing the build.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure UTF-8 output across Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = ROOT / "resources"


def find_bundled_python() -> Path:
    candidates = [
        RESOURCES_DIR / "python" / "python.exe",
        RESOURCES_DIR / "python" / "bin" / "python3",
        RESOURCES_DIR / "python" / "bin" / "python",
        RESOURCES_DIR / "python" / "python",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"Bundled Python not found in {RESOURCES_DIR / 'python'}")


def find_bundled_git() -> Path:
    candidates = [
        RESOURCES_DIR / "git" / "cmd" / "git.exe",
        RESOURCES_DIR / "git" / "bin" / "git.exe",
        RESOURCES_DIR / "git" / "bin" / "git",
        RESOURCES_DIR / "git" / "cmd" / "git",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"Bundled git not found in {RESOURCES_DIR / 'git'}")


def find_bundled_node() -> Path:
    candidates = [
        RESOURCES_DIR / "node" / "node.exe",
        RESOURCES_DIR / "node" / "bin" / "node",
        RESOURCES_DIR / "node" / "node",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"Bundled node not found in {RESOURCES_DIR / 'node'}")


def verify_bundle() -> bool:
    print("=" * 70)
    print("CODE OS — POST-BUNDLE RUNTIME BUILD GATE")
    print("=" * 70)

    # 1. Locate runtimes
    py_exe = find_bundled_python()
    git_exe = find_bundled_git()
    node_exe = find_bundled_node()
    tk_dir = RESOURCES_DIR / "tiktoken"

    print(f"✓ Bundled Python : {py_exe}")
    print(f"✓ Bundled Git    : {git_exe}")
    print(f"✓ Bundled Node   : {node_exe}")
    print(f"✓ Tiktoken Cache : {tk_dir}")

    if not tk_dir.is_dir():
        print(f"FAIL: Tiktoken cache directory missing: {tk_dir}", file=sys.stderr)
        return False

    # 2. Bundled Python assertions: tiktoken, unicode encode, watchdog, chromadb
    env = os.environ.copy()
    env["TIKTOKEN_CACHE_DIR"] = str(tk_dir)
    env.pop("PYTHONPATH", None)

    py_code = (
        "import sys\n"
        "if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "import tiktoken\n"
        "enc = tiktoken.get_encoding('cl100k_base')\n"
        "tokens = enc.encode('héllo 🙂 宇宙')\n"
        "assert len(tokens) > 0, 'Unicode tokens empty'\n"
        "print(f'[OK] tiktoken cl100k_base encoded sample: {tokens}')\n"
        "import watchdog\n"
        "print(f'[OK] watchdog imported ({getattr(watchdog, \"__version__\", \"ok\")})')\n"
        "import chromadb\n"
        "print(f'[OK] chromadb imported ({getattr(chromadb, \"__version__\", \"ok\")})')\n"
    )

    print("\n[1/3] Testing Bundled Python runtime (isolated, -s flag)...")
    res = subprocess.run(
        [str(py_exe), "-s", "-c", py_code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    if res.returncode != 0:
        print("FAIL: Bundled Python assertions failed!", file=sys.stderr)
        print("STDOUT:\n" + res.stdout, file=sys.stderr)
        print("STDERR:\n" + res.stderr, file=sys.stderr)
        return False
    print(res.stdout.strip())

    # 3. Bundled Git assertion
    print("\n[2/3] Testing Bundled Git binary...")
    git_res = subprocess.run([str(git_exe), "--version"], capture_output=True, text=True)
    if git_res.returncode != 0 or "git version" not in git_res.stdout.lower():
        print(f"FAIL: Bundled git failed: {git_res.stderr}", file=sys.stderr)
        return False
    print(f"✓ {git_res.stdout.strip()}")

    # 4. Bundled Node assertion
    print("\n[3/3] Testing Bundled Node binary...")
    node_res = subprocess.run([str(node_exe), "--version"], capture_output=True, text=True)
    if node_res.returncode != 0 or not node_res.stdout.strip().startswith("v"):
        print(f"FAIL: Bundled node failed: {node_res.stderr}", file=sys.stderr)
        return False
    print(f"✓ node version: {node_res.stdout.strip()}")

    print("\n" + "=" * 70)
    print("ALL BUNDLED RUNTIMES VERIFIED SUCCESSFULLY!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    try:
        ok = verify_bundle()
        sys.exit(0 if ok else 1)
    except Exception as exc:
        print(f"FATAL: verify_bundle_runtime error: {exc}", file=sys.stderr)
        sys.exit(1)
