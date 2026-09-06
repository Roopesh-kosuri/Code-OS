"""verify_service.py — Test execution and safety verification in temporary workspace sandbox."""
from __future__ import annotations

import ast
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


IGNORED_COPY_PATTERNS = shutil.ignore_patterns(
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "dist",
    "build",
    ".tempmediaStorage",
)


def verify_refactor_safety(changes: List[Dict[str, Any]], workspace: str) -> Dict[str, Any]:
    """Verifies refactor safety by copying workspace to a temp sandbox, applying changes,

    and running the existing test suite.

    Never applies changes to the actual workspace until safety is confirmed.

    Returns:
        {
            "safe": bool,
            "test_results": {
                "passed": bool,
                "exit_code": int,
                "output": str,
                "failed_tests": list[str]
            }
        }
    """
    ws_path = Path(workspace).resolve()
    if not ws_path.exists():
        return {
            "safe": False,
            "test_results": {
                "passed": False,
                "exit_code": 1,
                "output": f"Workspace '{workspace}' does not exist.",
                "failed_tests": ["WorkspaceNotFound"],
            },
        }

    with tempfile.TemporaryDirectory(prefix="codeos_refactor_verify_") as tmp_dir:
        tmp_ws = Path(tmp_dir)

        # Copy workspace files to temp sandbox
        try:
            shutil.copytree(ws_path, tmp_ws, dirs_exist_ok=True, ignore=IGNORED_COPY_PATTERNS)
        except Exception as exc:
            return {
                "safe": False,
                "test_results": {
                    "passed": False,
                    "exit_code": 1,
                    "output": f"Failed to initialize sandbox copy: {exc}",
                    "failed_tests": ["SandboxInitError"],
                },
            }

        # Apply candidate changes in temp sandbox
        for change in changes:
            target_rel = change.get("file", "")
            updated_content = change.get("updated_content", "")
            target_file = tmp_ws / target_rel
            try:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(updated_content, encoding="utf-8")
            except Exception as exc:
                return {
                    "safe": False,
                    "test_results": {
                        "passed": False,
                        "exit_code": 1,
                        "output": f"Failed writing changes to sandbox file {target_rel}: {exc}",
                        "failed_tests": [f"FileWriteError: {target_rel}"],
                    },
                }

        # First verify syntax of all modified python files
        for change in changes:
            target_rel = change.get("file", "")
            if target_rel.endswith(".py"):
                sandbox_file = tmp_ws / target_rel
                try:
                    ast.parse(sandbox_file.read_text(encoding="utf-8"))
                except SyntaxError as syn_err:
                    return {
                        "safe": False,
                        "test_results": {
                            "passed": False,
                            "exit_code": 1,
                            "output": f"SyntaxError in {target_rel} at line {syn_err.lineno}: {syn_err.msg}",
                            "failed_tests": [f"SyntaxError: {target_rel}:{syn_err.lineno}"],
                        },
                    }

        # Look for test files in the temp workspace
        test_files = []
        for root, dirs, files in os.walk(tmp_ws):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
            for f in files:
                if (f.startswith("test_") or f.endswith("_test.py")) and f.endswith(".py"):
                    test_files.append(Path(root) / f)

        if test_files:
            # Run pytest in the temporary workspace
            env = dict(os.environ)
            env["PYTHONPATH"] = str(tmp_ws) + os.pathsep + env.get("PYTHONPATH", "")
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "--tb=short"],
                    cwd=str(tmp_ws),
                    capture_output=True,
                    text=True,
                    timeout=45,
                    env=env,
                )
                output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
                passed = proc.returncode == 0
                failed_tests = []
                if not passed:
                    # Extract failing test names
                    for line in output.splitlines():
                        if "FAILED " in line or "ERROR " in line:
                            failed_tests.append(line.strip())
                    if not failed_tests:
                        failed_tests.append("Test suite failed")

                return {
                    "safe": passed,
                    "test_results": {
                        "passed": passed,
                        "exit_code": proc.returncode,
                        "output": output.strip(),
                        "failed_tests": failed_tests,
                    },
                }
            except subprocess.TimeoutExpired:
                return {
                    "safe": False,
                    "test_results": {
                        "passed": False,
                        "exit_code": 124,
                        "output": "Test execution timed out after 45 seconds.",
                        "failed_tests": ["TestTimeout"],
                    },
                }
            except Exception as exc:
                return {
                    "safe": False,
                    "test_results": {
                        "passed": False,
                        "exit_code": 1,
                        "output": f"Test runner error: {exc}",
                        "failed_tests": [str(exc)],
                    },
                }

        # If no tests exist, syntax verification was successful
        return {
            "safe": True,
            "test_results": {
                "passed": True,
                "exit_code": 0,
                "output": "No test suite detected in workspace. Syntax verification passed.",
                "failed_tests": [],
            },
        }
