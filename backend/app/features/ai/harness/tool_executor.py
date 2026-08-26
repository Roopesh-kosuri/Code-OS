"""
tool_executor.py - Execution handlers for chat agent workspace tools.

Handles:
- Smart edit validation with precise mismatch diagnostics
- Incremental file appends
- Fast pytest test node discovery (list_tests)
- Isolated single test execution (run_single_test)
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from ....core.paths import normalize_workspace, ensure_within_workspace
from ...terminal.service import _build_safe_environment
from ..agents.agent_tools import ToolResult
from ..schemas import FileChange

logger = logging.getLogger(__name__)


def _clean_rel_path(path: str) -> str:
    p = path.strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _read_file_cached(full_path: Path) -> str:
    try:
        return full_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("tool_executor: failed reading %s: %s", full_path, exc)
        return ""


def _find_mismatch_context(current_content: str, original: str) -> str:
    """Find the first differing line between the expected original and the file on disk."""
    curr_lines = current_content.splitlines()
    orig_lines = original.splitlines()
    if not orig_lines:
        return "Original snippet is empty."
    
    first_orig_line = orig_lines[0].strip()
    candidate_indices = [i for i, line in enumerate(curr_lines) if first_orig_line in line]
    
    if not candidate_indices:
        close_matches = difflib.get_close_matches(first_orig_line, curr_lines, n=1, cutoff=0.6)
        if close_matches:
            match_line = close_matches[0]
            line_no = curr_lines.index(match_line) + 1
            return (
                f"First differing line at line {line_no}:\n"
                f"Line 1 of original snippet was not found verbatim.\n"
                f"Closest matching line in file is line {line_no}:\n"
                f"  Actual:   '{match_line}'\n"
                f"  Expected: '{orig_lines[0]}'"
            )
        else:
            return f"First line of original snippet was not found anywhere in the file:\n  Expected: '{orig_lines[0]}'"

    best_match_idx = candidate_indices[0]
    mismatch_rel_idx = 0
    for rel_idx, o_line in enumerate(orig_lines):
        target_file_idx = best_match_idx + rel_idx
        if target_file_idx >= len(curr_lines):
            return (
                f"Mismatch at snippet line {rel_idx + 1}: expected file content beyond end-of-file.\n"
                f"  Expected: '{o_line}'"
            )
        c_line = curr_lines[target_file_idx]
        if c_line != o_line:
            mismatch_rel_idx = rel_idx
            line_no = target_file_idx + 1
            start_ctx = max(0, line_no - 3)
            end_ctx = min(len(curr_lines), line_no + 2)
            context_lines = [
                f"  {'>>' if i == line_no - 1 else '  '} Line {i+1}: {curr_lines[i]}"
                for i in range(start_ctx, end_ctx)
            ]
            return (
                f"First differing line at line {line_no}:\n"
                f"First mismatch at snippet line {mismatch_rel_idx + 1} (File line {line_no}):\n"
                f"  Expected snippet line: '{o_line}'\n"
                f"  Actual file line:      '{c_line}'\n"
                f"Surrounding file context:\n" + "\n".join(context_lines)
            )

    return "Whitespace or formatting divergence prevented exact verbatim replacement."


def _validate_smart_edit(
    workspace: str,
    arguments: dict[str, Any],
) -> tuple[bool, str, FileChange | None]:
    """Pre-validate edit_file arguments before creating a proposal."""
    path = arguments.get("path")
    original = arguments.get("original", "")
    updated = arguments.get("updated")
    
    if not path or updated is None:
        return False, "Missing required parameters: 'path' and 'updated' are mandatory", None
    
    try:
        clean_path = _clean_rel_path(path)
        full_path = ensure_within_workspace(workspace, clean_path)
    except Exception as exc:
        return False, f"Invalid file path: {exc}", None

    if not original:
        return True, "", FileChange(path=clean_path, original="", updated=updated)

    if not full_path.is_file():
        return False, f"File does not exist: '{clean_path}'. To create a new file, pass original=''", None

    current_content = _read_file_cached(full_path)
    if original not in current_content:
        diagnostic = _find_mismatch_context(current_content, original)
        err_msg = (
            f"Exact-match pre-validation failed for '{clean_path}'. "
            f"The 'original' snippet does not match verbatim in the existing file.\n"
            f"[Mismatch Diagnostic]:\n{diagnostic}\n\n"
            "Action Required: Use `read_file` to inspect the latest file content and supply the exact matching lines."
        )
        return False, err_msg, None

    return True, "", FileChange(path=clean_path, original=original, updated=updated)


def _handle_append_file(
    workspace: str,
    arguments: dict[str, Any],
    staged_changes: list[FileChange],
) -> tuple[bool, str, FileChange | None]:
    """Append content chunk to a staged or existing file."""
    path = arguments.get("path")
    content = arguments.get("content") or arguments.get("updated") or ""
    
    if not path:
        return False, "Missing required parameter: 'path' is mandatory", None
    if content is None:
        return False, "Missing required parameter: 'content' is mandatory", None
    
    try:
        clean_path = _clean_rel_path(path)
        full_path = ensure_within_workspace(workspace, clean_path)
    except Exception as exc:
        return False, f"Invalid file path: {exc}", None

    existing_staged = next((c for c in staged_changes if c.path == clean_path), None)
    if existing_staged:
        existing_staged.updated += ("\n" if existing_staged.updated and not existing_staged.updated.endswith("\n") else "") + content
        return True, "", existing_staged

    if full_path.is_file():
        current_content = _read_file_cached(full_path)
        new_content = current_content + ("\n" if current_content and not current_content.endswith("\n") else "") + content
        change = FileChange(path=clean_path, original=current_content, updated=new_content)
        staged_changes.append(change)
        return True, "", change

    change = FileChange(path=clean_path, original="", updated=content)
    staged_changes.append(change)
    return True, "", change


def _handle_list_tests(workspace: str, arguments: dict[str, Any] | None = None) -> ToolResult:
    """Discover pytest test node IDs in the workspace."""
    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        cmd = ["python", "-m", "pytest", "--collect-only", "-q"]
        proc = subprocess.run(
            cmd,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=20.0,
        )
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

        node_ids: list[str] = []
        for line in raw_output.splitlines():
            line_str = line.strip()
            if "::" in line_str and not line_str.startswith("="):
                node_ids.append(line_str)

        total_count = len(node_ids)
        if total_count == 0:
            if proc.returncode != 0 and ("error" in raw_output.lower() or "exception" in raw_output.lower()):
                return ToolResult(
                    tool_name="list_tests",
                    success=False,
                    output="",
                    error=f"Test collection failed (exit code {proc.returncode}):\n{raw_output[:500]}",
                )
            return ToolResult(
                tool_name="list_tests",
                success=True,
                output="=== DISCOVERED TESTS ===\nTotal: 0 tests found in workspace.",
                error="",
            )

        capped = node_ids[:100]
        out_lines = [f"=== DISCOVERED TESTS (showing {len(capped)} of {total_count}) ==="]
        out_lines.extend(capped)
        if total_count > 100:
            out_lines.append(f"... and {total_count - 100} more test(s). Use run_single_test with exact node ID.")

        return ToolResult(
            tool_name="list_tests",
            success=True,
            output="\n".join(out_lines),
            error="",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_name="list_tests",
            success=False,
            output="",
            error="Test discovery timed out after 20 seconds.",
        )
    except Exception as exc:
        return ToolResult(
            tool_name="list_tests",
            success=False,
            output="",
            error=f"Error running test discovery: {exc}",
        )


def _handle_run_single_test(workspace: str, arguments: dict[str, Any]) -> ToolResult:
    """Execute a single pytest test node ID."""
    node_id = arguments.get("node_id") or arguments.get("test_name") or ""
    if not node_id:
        return ToolResult(
            tool_name="run_single_test",
            success=False,
            output="",
            error="Missing required parameter: 'node_id' is mandatory.",
        )

    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        cmd = ["python", "-m", "pytest", node_id, "-v", "--tb=short"]
        start_t = time.time()
        proc = subprocess.run(
            cmd,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        duration = time.time() - start_t
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

        is_pass = proc.returncode == 0
        status_label = "PASSED" if is_pass else f"FAILED (exit code {proc.returncode})"

        header = f"=== SINGLE TEST EXECUTION: {node_id} [{status_label} in {duration:.2f}s] ==="
        body = raw_output.strip() or "(no output)"
        full_out = f"{header}\n{body}"

        return ToolResult(
            tool_name="run_single_test",
            success=is_pass,
            output=full_out,
            error="" if is_pass else f"Test {node_id} failed with exit code {proc.returncode}",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_name="run_single_test",
            success=False,
            output="",
            error=f"Single test run for {node_id} timed out after 30 seconds.",
        )
    except Exception as exc:
        return ToolResult(
            tool_name="run_single_test",
            success=False,
            output="",
            error=f"Error executing test {node_id}: {exc}",
        )


class ToolExecutor:
    """Class wrapper providing unified tool execution and validation."""

    @staticmethod
    def validate_edit(workspace: str, arguments: dict[str, Any]):
        return _validate_smart_edit(workspace, arguments)

    @staticmethod
    def append_file(workspace: str, arguments: dict[str, Any], staged: list[FileChange]):
        return _handle_append_file(workspace, arguments, staged)

    @staticmethod
    def list_tests(workspace: str, arguments: dict[str, Any] | None = None):
        return _handle_list_tests(workspace, arguments)

    @staticmethod
    def run_single_test(workspace: str, arguments: dict[str, Any]):
        return _handle_run_single_test(workspace, arguments)