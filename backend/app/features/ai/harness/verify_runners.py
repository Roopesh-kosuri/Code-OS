"""Test runner hook and baseline attribution engine for CODE OS (Phase 14).

Executes targeted, bounded test runs for changed files with:
- Strict trust gating (Restricted Mode rejection)
- Scrubbed environment (no API keys, tokens, or credentials)
- Process tree kill on Windows (taskkill /F /T /PID)
- Outside-workspace temp JUnit XML parsing (process return codes NOT trusted)
- Reverse-import mapping (AST parse of tests for imported changed modules)
- Baseline attribution overlay (pre-existing failures are classified as WARN, not blamed on turn)
"""

from __future__ import annotations

import ast
import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.terminal.service import _sanitize_env
from app.features.workspaces.trust_service import get_workspace_trust
from app.features.ai.harness.approval_coordinator import (
    _is_command_trusted,
    _is_workspace_trusted_sync,
    _save_trusted_command,
)
from app.features.ai.harness.verification_matrix import (
    VerifyResult,
    VerifyStatus,
    is_code_file,
    is_test_file,
    parse_verify_settings,
)

logger = logging.getLogger(__name__)

# ANSI escape sequence regex for output sanitization
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Max output capture size (200 KB)
MAX_OUTPUT_BYTES = 200 * 1024


# ── Temp Dir Management (Isolated outside workspace) ─────────────────────────

def create_verify_temp_dir(prefix: str = "codeos_verify_") -> Path:
    """Create an isolated temporary directory outside the workspace for reports/overlays."""
    temp_dir = tempfile.mkdtemp(prefix=prefix)
    return Path(temp_dir)


def cleanup_verify_temp_dir(temp_path: Path | str | None) -> None:
    """Safely remove temporary directory and all contents."""
    if temp_path:
        try:
            p = Path(temp_path)
            if p.exists() and p.is_dir():
                shutil.rmtree(str(p), ignore_errors=True)
        except Exception as exc:
            logger.warning("cleanup_verify_temp_dir failed for %s: %s", temp_path, exc)


# ── Process Tree Kill & Subprocess Execution ─────────────────────────────────

async def _taskkill_process_tree(pid: int) -> None:
    """Kill process tree asynchronously on Windows using taskkill /F /T /PID."""
    if os.name != "nt" or not pid:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "taskkill",
            "/F",
            "/T",
            "/PID",
            str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
    except Exception as exc:
        logger.warning("Failed to taskkill process tree %s: %s", pid, exc)


def strip_ansi_and_cap(raw_bytes: bytes, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    """Decode, strip ANSI escapes, and cap output keeping head and tail."""
    if not raw_bytes:
        return ""
    if len(raw_bytes) > max_bytes:
        half = max_bytes // 2
        raw_bytes = raw_bytes[:half] + b"\n... [TRUNCATED OUTPUT] ...\n" + raw_bytes[-half:]
    text = raw_bytes.decode("utf-8", errors="replace")
    return ANSI_ESCAPE_RE.sub("", text)


def build_scrubbed_env() -> dict[str, str]:
    """Build a strictly scrubbed environment allowlist for verification subprocesses."""
    safe = _sanitize_env()
    # Force clean Python flags
    safe["PYTHONDONTWRITEBYTECODE"] = "1"
    safe["CI"] = "1"
    safe["PYTHONIOENCODING"] = "utf-8"
    # Ensure no secrets or API keys leak
    for k in list(safe.keys()):
        k_upper = k.upper()
        if any(bad in k_upper for bad in ("KEY", "TOKEN", "SECRET", "PASS", "CREDENTIAL")):
            if k_upper not in ("SSH_AGENT_PID", "SSH_AUTH_SOCK"):
                safe.pop(k, None)
    return safe


# ── Reverse-Import Mapping & Test Detection ──────────────────────────────────

# In-memory mtime-based cache of test import mappings per workspace
_REVERSE_IMPORT_CACHE: dict[str, tuple[float, dict[str, list[str]]]] = {}


def _get_python_module_name(ws_path: Path, py_path: Path) -> list[str]:
    """Compute possible import identifiers for a python file relative to workspace root."""
    try:
        rel = py_path.relative_to(ws_path)
    except ValueError:
        return [py_path.stem]
    
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    
    dotted = ".".join(parts)
    stem = py_path.stem
    # If file is backend/app/features/calc.py, candidates: backend.app.features.calc, app.features.calc, calc
    candidates = [stem, dotted]
    for i in range(1, len(parts)):
        candidates.append(".".join(parts[i:]))
    return list(dict.fromkeys(candidates))


def build_reverse_import_index(ws_path: Path, max_files: int = 500) -> dict[str, list[str]]:
    """Scan all test files in workspace and map imported modules to test file paths.
    
    Returns: dict[imported_mod_name -> list[rel_test_path]]
    """
    index: dict[str, list[str]] = {}
    test_files: list[Path] = []

    # Exclusions
    excluded_dirs = {".git", "node_modules", ".code_os", "dist", "build", "__pycache__", ".pytest_cache"}

    file_count = 0
    for root, dirs, files in os.walk(str(ws_path)):
        dirs[:] = [d for d in dirs if d not in excluded_dirs and "venv" not in d.lower()]
        for f in files:
            if f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")):
                test_files.append(Path(root) / f)
                file_count += 1
                if file_count >= max_files:
                    break
        if file_count >= max_files:
            break

    for tf in test_files:
        try:
            rel_tf = str(tf.relative_to(ws_path)).replace("\\", "/")
        except ValueError:
            rel_tf = str(tf).replace("\\", "/")

        try:
            content = tf.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(tf))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    index.setdefault(name, []).append(rel_tf)
                    # Also record top/tail parts
                    parts = name.split(".")
                    if parts:
                        index.setdefault(parts[-1], []).append(rel_tf)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                index.setdefault(mod, []).append(rel_tf)
                parts = mod.split(".")
                if parts:
                    index.setdefault(parts[-1], []).append(rel_tf)
                for alias in node.names:
                    index.setdefault(alias.name, []).append(rel_tf)

    # Deduplicate test paths
    for mod_name, paths in index.items():
        index[mod_name] = list(dict.fromkeys(paths))

    return index


def get_targeted_tests_for_files(
    ws_path: Path,
    changed_rel_paths: list[str],
    max_test_files: int = 20,
) -> tuple[list[str], str | None]:
    """Map changed files to a bounded, deduplicated list of targeted test files.
    
    Order:
    1. Changed file is itself a test -> include it.
    2. Reverse-import map: test files importing the changed module.
    3. Naming convention fallback (test_<name>.py, <name>_test.py, etc.).
    
    Returns: (targeted_test_paths, coverage_note)
    """
    targeted: list[str] = []
    
    # 1. Changed files that are tests
    for rel_p in changed_rel_paths:
        if is_test_file(rel_p):
            full_p = ws_path / rel_p
            if full_p.is_file():
                targeted.append(rel_p.replace("\\", "/"))

    # 2. Reverse-import mapping for changed code files
    code_changes = [p for p in changed_rel_paths if is_code_file(p) and not is_test_file(p)]
    if code_changes:
        index = build_reverse_import_index(ws_path)
        for rel_p in code_changes:
            full_p = ws_path / rel_p
            mod_names = _get_python_module_name(ws_path, full_p)
            for m in mod_names:
                for test_file in index.get(m, []):
                    test_full = ws_path / test_file
                    if test_full.is_file() and test_file not in targeted:
                        targeted.append(test_file)

    # 3. Naming convention fallbacks
    for rel_p in code_changes:
        stem = Path(rel_p).stem
        candidates = [
            f"tests/test_{stem}.py",
            f"backend/tests/test_{stem}.py",
            f"test_{stem}.py",
            f"{stem}_test.py",
            f"tests/{stem}_test.py",
            f"{stem}.test.ts",
            f"{stem}.test.tsx",
            f"{stem}.test.js",
            f"{stem}_test.go",
        ]
        for cand in candidates:
            if (ws_path / cand).is_file():
                norm_cand = cand.replace("\\", "/")
                if norm_cand not in targeted:
                    targeted.append(norm_cand)

    deduped = list(dict.fromkeys(targeted))
    total_found = len(deduped)

    if total_found > max_test_files:
        coverage_note = f"partial: {max_test_files} of {total_found} test files"
        return deduped[:max_test_files], coverage_note

    return deduped, None


# ── Runner Detection & Argv Construction ─────────────────────────────────────

def detect_runners_for_files(
    ws_path: Path,
    targeted_tests: list[str],
) -> list[dict[str, Any]]:
    """Detect test runners for targeted test files (pytest, vitest, jest, go, cargo)."""
    runners: list[dict[str, Any]] = []

    py_tests = [t for t in targeted_tests if t.endswith(".py")]
    js_tests = [t for t in targeted_tests if any(t.endswith(ext) for ext in (".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.js"))]
    go_tests = [t for t in targeted_tests if t.endswith("_test.go")]
    cargo_tests = [t for t in targeted_tests if t.endswith(".rs") or "cargo" in t.lower()]

    if cargo_tests:
        runners.append({
            "type": "cargo",
            "files": cargo_tests,
            "status": "unsupported",
            "skip_reason": "cargo not supported yet",
        })

    if py_tests:
        # Prefer sys.executable
        py_exe = sys.executable
        runners.append({
            "type": "pytest",
            "files": py_tests,
            "executable": py_exe,
        })

    if js_tests:
        # Check for local vitest or jest binary
        vitest_bin = ws_path / "node_modules" / ".bin" / ("vitest.cmd" if os.name == "nt" else "vitest")
        jest_bin = ws_path / "node_modules" / ".bin" / ("jest.cmd" if os.name == "nt" else "jest")
        if vitest_bin.is_file():
            runners.append({
                "type": "vitest",
                "files": js_tests,
                "executable": str(vitest_bin),
            })
        elif jest_bin.is_file():
            runners.append({
                "type": "jest",
                "files": js_tests,
                "executable": str(jest_bin),
            })
        else:
            runners.append({
                "type": "vitest",
                "files": js_tests,
                "executable": "npx vitest",
                "skip_reason": "local test runner binary not found in node_modules/.bin",
            })

    if go_tests:
        go_bin = shutil.which("go")
        if go_bin:
            runners.append({
                "type": "go",
                "files": go_tests,
                "executable": go_bin,
            })
        else:
            runners.append({
                "type": "go",
                "files": go_tests,
                "skip_reason": "go binary not found on PATH",
            })

    return runners


# ── JUnit XML Parsing (T5: Never Trust Return Codes) ─────────────────────────

@dataclass
class JUnitReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failing_ids: list[str] = field(default_factory=list)
    parse_error: str | None = None


def parse_junit_xml(report_path: Path) -> JUnitReport:
    """Parse JUnit XML report directly.
    
    Pytest in this repo force-exits 0 via conftest.py, so process return codes
    must NEVER be trusted. The report is the single source of truth.
    """
    if not report_path.is_file():
        return JUnitReport(parse_error="JUnit report XML file was not generated")

    try:
        tree = ET.parse(str(report_path))
        root = tree.getroot()
    except Exception as exc:
        return JUnitReport(parse_error=f"Malformed JUnit report XML: {exc}")

    total = 0
    failed = 0
    errors = 0
    skipped = 0
    failing_ids: list[str] = []

    # Single testsuite or testsuites container
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if not suites and root.tag == "testsuites":
        suites = list(root)

    for suite in suites:
        for case in suite.findall("testcase"):
            total += 1
            name = case.attrib.get("name", "unknown_test")
            classname = case.attrib.get("classname", "")
            test_id = f"{classname}::{name}" if classname else name

            fail_elem = case.find("failure")
            err_elem = case.find("error")
            skip_elem = case.find("skipped")

            if fail_elem is not None:
                failed += 1
                failing_ids.append(test_id)
            elif err_elem is not None:
                errors += 1
                failing_ids.append(test_id)
            elif skip_elem is not None:
                skipped += 1

    passed = max(0, total - (failed + errors + skipped))
    return JUnitReport(
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        failing_ids=failing_ids,
    )


# ── Safe Test Subprocess Execution ───────────────────────────────────────────

async def run_pytest_subprocess(
    ws_path: Path,
    test_files: list[str],
    timeout_s: int = 120,
    test_filter: str | None = None,
) -> tuple[int, str, Path | None]:
    """Execute pytest with isolated JUnit XML output and process tree cleanup.
    
    Returns: (exit_code, combined_output, report_path)
    """
    temp_dir = create_verify_temp_dir()
    report_file = temp_dir / "report.xml"

    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        f"--junitxml={report_file}",
    ]
    if test_filter:
        argv.extend(["-k", test_filter])
    argv.extend(test_files)

    env = build_scrubbed_env()
    spawn_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(ws_path),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **spawn_kwargs,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(timeout_s),
        )
        combined = strip_ansi_and_cap(stdout_bytes + b"\n" + stderr_bytes)
        return proc.returncode or 0, combined, report_file
    except asyncio.TimeoutError:
        if proc and proc.pid:
            await _taskkill_process_tree(proc.pid)
            try:
                proc.kill()
            except Exception:
                pass
        return -1, "Process timed out", None
    except Exception as exc:
        if proc and proc.pid:
            await _taskkill_process_tree(proc.pid)
        return -2, f"Subprocess launch error: {exc}", None


# ── Baseline Attribution (Part 4) ────────────────────────────────────────────

def create_baseline_overlay(
    ws_path: Path,
    changed_rel_paths: list[str],
    pre_images: dict[str, bytes | None],
    max_mb: int = 200,
    max_files: int = 5000,
) -> tuple[Path | None, str | None]:
    """Create a temporary workspace overlay copy with pre-turn bytes restored.
    
    Excludes .git, node_modules, *venv*, .code_os, build, dist.
    Returns: (temp_dir_path, error_reason)
    """
    temp_dir = create_verify_temp_dir(prefix="codeos_baseline_")
    excluded = {".git", "node_modules", ".code_os", "dist", "build", ".pytest_cache"}

    total_bytes = 0
    total_files = 0
    max_bytes = max_mb * 1024 * 1024

    try:
        for root, dirs, files in os.walk(str(ws_path)):
            dirs[:] = [d for d in dirs if d not in excluded and "venv" not in d.lower()]
            rel_root = Path(root).relative_to(ws_path)
            target_dir = temp_dir / rel_root
            os.makedirs(str(target_dir), exist_ok=True)

            for f in files:
                src_file = Path(root) / f
                dst_file = target_dir / f
                try:
                    size = src_file.stat().st_size
                    total_bytes += size
                    total_files += 1
                    if total_bytes > max_bytes:
                        cleanup_verify_temp_dir(temp_dir)
                        return None, f"workspace exceeds baseline size cap ({max_mb} MB)"
                    if total_files > max_files:
                        cleanup_verify_temp_dir(temp_dir)
                        return None, f"workspace exceeds baseline file count cap ({max_files})"
                    shutil.copy2(str(src_file), str(dst_file))
                except (OSError, PermissionError):
                    continue

        # Restore pre-images on changed files
        for rel_p in changed_rel_paths:
            target_file = temp_dir / rel_p
            original_bytes = pre_images.get(rel_p)
            if original_bytes is None:
                # File was created in this turn; remove from baseline
                if target_file.exists():
                    try:
                        target_file.unlink()
                    except OSError:
                        pass
            else:
                # Restore pre-turn bytes
                os.makedirs(str(target_file.parent), exist_ok=True)
                target_file.write_bytes(original_bytes)

        return temp_dir, None
    except Exception as exc:
        cleanup_verify_temp_dir(temp_dir)
        return None, f"baseline overlay creation failed: {exc}"


async def attribute_failures_against_baseline(
    ws_path: Path,
    failing_test_ids: list[str],
    targeted_test_files: list[str],
    changed_rel_paths: list[str],
    pre_images: dict[str, bytes | None],
    timeout_s: int = 120,
    max_mb: int = 200,
) -> tuple[list[str], list[str], bool, str | None]:
    """Run failing test IDs on baseline copy to filter pre-existing failures.
    
    Returns:
      (pre_existing_failures, turn_caused_failures, baseline_available, caveat_or_reason)
    """
    if not pre_images:
        return [], failing_test_ids, False, "baseline unavailable"

    base_dir, err = create_baseline_overlay(ws_path, changed_rel_paths, pre_images, max_mb=max_mb)
    if not base_dir or err:
        return [], failing_test_ids, False, err or "baseline unavailable"

    try:
        # Build filter from failing test names
        # Test IDs are format Class::test_name or test_name
        test_names = [tid.split("::")[-1] for tid in failing_test_ids]
        test_filter = " or ".join(test_names)

        rc, out, report_path = await run_pytest_subprocess(
            base_dir,
            targeted_test_files,
            timeout_s=timeout_s,
            test_filter=test_filter,
        )
        if not report_path or not report_path.is_file():
            return [], failing_test_ids, False, "baseline test report missing"

        base_rep = parse_junit_xml(report_path)
        cleanup_verify_temp_dir(report_path.parent)

        pre_existing: list[str] = []
        turn_caused: list[str] = []

        for fid in failing_test_ids:
            base_failed = any(fid == b_fid or fid.endswith(f"::{b_fid}") or b_fid.endswith(f"::{fid}") for b_fid in base_rep.failing_ids)
            if base_failed:
                pre_existing.append(fid)
            else:
                turn_caused.append(fid)

        return pre_existing, turn_caused, True, None
    finally:
        cleanup_verify_temp_dir(base_dir)


# ── Runner Approval Gating (T0b) ─────────────────────────────────────────────

_ALLOWED_ONCE_RUNNERS: set[tuple[str, str]] = set()


def allow_runner_once(workspace: str | Path, runner_name: str) -> None:
    """Grant one-time in-memory approval for a test runner execution in a workspace."""
    norm = str(normalize_workspace(str(workspace)))
    _ALLOWED_ONCE_RUNNERS.add((norm, runner_name.lower()))


def clear_runner_approvals() -> None:
    """Clear in-memory allow-once approvals."""
    _ALLOWED_ONCE_RUNNERS.clear()


def is_runner_approved(ws_path: Path, runner_type: str) -> bool:
    """Check whether a test runner is approved (via stored trusted command or allow-once)."""
    norm = str(ws_path)
    if (norm, runner_type.lower()) in _ALLOWED_ONCE_RUNNERS:
        return True
    return _is_command_trusted(norm, runner_type)


# ── Main Test Suite Hook Entrypoint ──────────────────────────────────────────

async def run_test_suite_hook(
    workspace_root: str | Path,
    changed_rel_paths: list[str],
    pre_images: dict[str, bytes | None] | None = None,
    raw_settings: dict[str, Any] | None = None,
) -> VerifyResult:
    """Execute the targeted test suite verification hook.
    
    Full Phase 14 pipeline:
    1. Trust check (Restricted Mode rejection)
    2. Approval check
    3. Targeted test mapping (AST reverse import + naming convention)
    4. Runner execution with scrubbed environment and JUnit XML parsing
    5. Baseline attribution for pre-existing failures
    """
    t0 = time.perf_counter()
    ws_path = normalize_workspace(str(workspace_root))
    settings = parse_verify_settings(raw_settings)
    timeout_s = settings["code_os_verify_timeout_s"]
    max_tests = settings["code_os_verify_max_test_files"]
    max_mb = settings["code_os_verify_baseline_max_mb"]

    # T0: Trust check
    trust = await get_workspace_trust(str(ws_path))
    if not trust.get("trusted", False):
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.SKIPPED,
            summary="Workspace untrusted",
            skip_reason="workspace untrusted",
            duration_ms=duration_ms,
        )

    # Filter out non-code changes
    code_changes = [f for f in changed_rel_paths if is_code_file(f)]
    if not code_changes and not any(is_test_file(f) for f in changed_rel_paths):
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.SKIPPED,
            summary="No code files changed",
            skip_reason="no code files changed",
            duration_ms=duration_ms,
        )

    # T2 & T3: Targeted test mapping
    targeted, cov_note = get_targeted_tests_for_files(ws_path, changed_rel_paths, max_test_files=max_tests)
    if not targeted:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.SKIPPED,
            summary="No targeted tests for changed files",
            skip_reason="no targeted tests for changed files",
            duration_ms=duration_ms,
        )

    # Runner detection
    runners = detect_runners_for_files(ws_path, targeted)
    if not runners:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.SKIPPED,
            summary="No supported test runner detected",
            skip_reason="no supported test runner detected",
            duration_ms=duration_ms,
        )

    # Check for unsupported runners
    for r in runners:
        if r.get("skip_reason"):
            duration_ms = int((time.perf_counter() - t0) * 1000)
            return VerifyResult(
                hook="test_suite",
                status=VerifyStatus.SKIPPED,
                summary=r["skip_reason"],
                skip_reason=r["skip_reason"],
                duration_ms=duration_ms,
            )

    # T0b: Check approvals for runner command
    if not is_runner_approved(ws_path, "pytest"):
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.SKIPPED,
            summary="User declined test execution",
            skip_reason="user declined test execution",
            duration_ms=duration_ms,
        )

    # Execute pytest runner
    pytest_runner = next((r for r in runners if r["type"] == "pytest"), None)
    if not pytest_runner:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.SKIPPED,
            summary="Non-pytest runners require configured toolchain",
            skip_reason="non-pytest runners require configured toolchain",
            duration_ms=duration_ms,
        )

    rc, out, report_path = await run_pytest_subprocess(
        ws_path,
        pytest_runner["files"],
        timeout_s=timeout_s,
    )
    duration_ms = int((time.perf_counter() - t0) * 1000)

    # Timeout
    if rc == -1:
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.TIMEOUT,
            summary=f"tests timed out after {timeout_s}s",
            duration_ms=duration_ms,
            coverage_note=cov_note,
        )

    # Error
    if not report_path or not report_path.is_file():
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.ERROR,
            summary=f"no test report produced (runner exited rc={rc})",
            details=[out[:500]] if out else [],
            duration_ms=duration_ms,
            coverage_note=cov_note,
        )

    # T5: Parse JUnit XML
    report = parse_junit_xml(report_path)
    cleanup_verify_temp_dir(report_path.parent)

    if report.parse_error:
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.ERROR,
            summary=report.parse_error,
            duration_ms=duration_ms,
            coverage_note=cov_note,
        )

    # 0 collected tests -> SKIPPED
    if report.total == 0:
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.SKIPPED,
            summary="0 tests collected",
            skip_reason="0 tests collected",
            duration_ms=duration_ms,
            coverage_note=cov_note,
        )

    # If all passed
    if report.failed == 0 and report.errors == 0:
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.PASSED,
            summary=f"{report.passed} passed",
            duration_ms=duration_ms,
            coverage_note=cov_note,
        )

    # There are failures: run Baseline Attribution (Part 4)
    pre_existing, turn_caused, base_ok, base_note = await attribute_failures_against_baseline(
        ws_path,
        report.failing_ids,
        pytest_runner["files"],
        changed_rel_paths,
        pre_images or {},
        timeout_s=timeout_s,
        max_mb=max_mb,
    )

    if not base_ok:
        # Baseline failed or unavailable -> UNVERIFIED per Row 6
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.WARN,
            summary="Baseline unavailable: test failures not attributed",
            details=report.failing_ids,
            duration_ms=duration_ms,
            coverage_note=cov_note,
            caveats=["baseline unavailable"],
        )

    if not turn_caused and pre_existing:
        # All failures were pre-existing -> WARN (does not fail verdict per Row 7)
        return VerifyResult(
            hook="test_suite",
            status=VerifyStatus.WARN,
            summary=f"{len(pre_existing)} pre-existing failure(s) confirmed by baseline",
            details=pre_existing,
            duration_ms=duration_ms,
            coverage_note=cov_note,
            caveats=["pre-existing failure"],
        )

    # There are turn-caused failures -> FAILED
    return VerifyResult(
        hook="test_suite",
        status=VerifyStatus.FAILED,
        summary=f"{len(turn_caused)} failure(s) caused by this turn",
        details=turn_caused,
        duration_ms=duration_ms,
        coverage_note=cov_note,
        caveats=["pre-existing failure"] if pre_existing else [],
    )
