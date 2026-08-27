from __future__ import annotations
_file_read_cache: dict[str, tuple[float, str]] = {}
"""
tool_executor.py - Execution handlers for chat agent workspace tools.
"""

import difflib
import json
import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.ai.schemas import FileChange
from .compaction_manager import _generate_diff_summary

logger = logging.getLogger(__name__)

PROJECT_MEMORY_MAX_CHARS = 4000
_file_cache: dict[str, tuple[float, str]] = {}

# ── Constants & Limits ───────────────────────────────────────────────────────

MAX_AGENT_ITERATIONS = 12
MAX_QUICK_TASK_ITERATIONS = 4
MAX_TOOL_CALLS_PER_ITERATION = 5
MAX_RETRY_BEFORE_ESCALATE = 3
SEMANTIC_SEARCH_TOP_K = 10
COMMAND_APPROVAL_TIMEOUT_SECONDS = 60.0
EDIT_APPROVAL_TIMEOUT_SECONDS = 300.0
APPROVAL_TIMEOUT_SECONDS = 120.0
COMPACTION_THRESHOLD_TURNS = 5
PROJECT_MEMORY_MAX_CHARS = 1500

# Strict allowlist for terminal commands that can run without interactive approval.
# Fail CLOSED: anything not on this list requires explicit user approval.
SAFE_COMMAND_ALLOWLIST = frozenset({
    "cat", "type",          # read file contents
    "ls", "dir",            # list directory
    "grep", "findstr",      # search
    "head", "tail",         # partial reads
    "wc",                   # word count
    "pwd", "cd",            # navigation
    "echo",                 # print
    "which", "where",       # locate commands
    "git status", "git log", "git diff", "git branch", "git show",
    "git rev-parse",        # git read-only inspection
    "python --version", "python3 --version",
    "node --version", "npm --version",
    "pip list", "pip show", "pip freeze",
    "npm list", "npm ls",
    "tree",                 # directory tree
    "env", "printenv", "set",  # environment
    "whoami",               # identity
    "date",                 # time
    "uname",                # system info
    "file",                 # file type detection
})

SAFE_COMMAND_PREFIXES = tuple(sorted([
    "cat ", "type ", "ls ", "dir ", "grep ", "findstr ",
    "head ", "tail ", "wc ", "echo ", "which ", "where ",
    "git status", "git log", "git diff", "git branch", "git show",
    "git rev-parse",
    "pip list", "pip show", "pip freeze",
    "npm list", "npm ls",
    "tree ", "file ",
    "python --version", "python3 --version",
    "node --version", "npm --version",
], key=lambda x: -len(x)))

MALICIOUS_COMMAND_PATTERNS = [
    r"curl\s+.*\|\s*(bash|sh|zsh|powershell|pwsh|cmd)",
    r"wget\s+.*\|\s*(bash|sh|zsh|powershell|pwsh|cmd)",
    r"eval\s+\$\(.*\)",
    r"curl\s+.*-o\s+(/tmp/|C:\\Windows\\Temp\\|%TEMP%|[A-Za-z]:\\[^ \t\n\r]+\.exe)",
    r"(?i)\b(?:Invoke-Expression|iex)\b[^;\r\n|&]{0,250}\b(?:Invoke-WebRequest|iwr|curl|wget)\b",
    r"powershell.*-enc\s+[A-Za-z0-9+/=]{20,}",
]




from app.features.ai.agents.agent_tools import (
    _handle_read_file,
    _handle_list_directory,
    _handle_search_code,
    _handle_run_test,
    parse_tool_calls,
    has_tool_calls,
    ToolCall,
    ToolResult,
    summarize_test_output,
    _clean_rel_path,
    AGENT_TOOLS,
)

HARNESS_TOOLS = {
    **AGENT_TOOLS,
    "list_tests": {
        "description": "Discover all pytest test node IDs in the workspace without executing them (runs pytest --collect-only -q). Read-only, no approval needed.",
        "parameters": {},
    },
    "run_single_test": {
        "description": "Run a single specific test by its pytest node ID (e.g. 'tests/test_foo.py::test_bar') rather than executing the entire test suite.",
        "parameters": {
            "node_id": "The test node ID to execute (e.g. 'tests/test_foo.py::test_bar').",
        },
    },
    "append_file": {
        "description": "Append text content to a staged or existing file without requiring verbatim original. Used for chunked large-file generation.",
        "parameters": {
            "path": "Relative path to the file.",
            "content": "Content chunk to append to the file.",
        },
    },
    "semantic_search": {
        "description": "Search workspace files by concept/meaning using TF-IDF ranking. Best when exact symbol or filename is unknown.",
        "parameters": {
            "query": "Natural language query describing the desired logic or component.",
        },
    },
    "run_command": {
        "description": "Execute a terminal command in the workspace. Safe read-only commands (ls, cat, grep, git status) run immediately. Other commands trigger an interactive user approval card. Set require_sandbox=True to force container isolation.",
        "parameters": {
            "command": "The terminal command string to execute.",
            "require_sandbox": "Optional boolean: when True, forces execution inside a Docker container sandbox (fails closed if container runtime is unavailable).",
        },
    },
    "memory_write": {
        "description": "Save a persistent project convention, user preference, or architectural rule to RONY.md.",
        "parameters": {
            "fact": "The rule, convention, or preference to remember for this project.",
        },
    },
    "ask_user": {
        "description": "Ask the user a clarifying question with quick-reply options when requirements are ambiguous or underspecified.",
        "parameters": {
            "question": "The clarifying question to ask.",
            "options": "List of 2-4 quick-reply options for the user to choose from.",
        },
    },
    "take_screenshot": {
        "description": "Capture an offscreen visual rendering of a workspace HTML file/URL (preview mode) or the CODE OS application window (app_window mode) and inspect it using Vision QA analysis.",
        "parameters": {
            "mode": "Mode of capture: 'preview' (render HTML/URL offscreen) or 'app_window' (capture CODE OS app screen). Default is 'preview'.",
            "target": "Workspace HTML file (e.g. 'index.html' or 'hello.html') or localhost URL (e.g. 'http://localhost:3000') to render in preview mode.",
            "question": "Specific visual question to inspect (e.g. 'Does the nav render, are sections visible, is anything overlapping or broken?').",
        },
    },
    "inspect_visuals": {
        "description": "Alias for take_screenshot to visually inspect rendered pages or application window.",
        "parameters": {
            "mode": "Mode of capture: 'preview' or 'app_window'.",
            "target": "Workspace HTML file or URL to preview.",
            "question": "Specific visual question to inspect.",
        },
    },
    "find_references": {
        "description": "Find all usages, call sites, and references of a symbol (function, class, variable, constant) across all files in the workspace.",
        "parameters": {
            "symbol": "The identifier/symbol name to find references for.",
        },
    },
    "go_to_definition": {
        "description": "Locate the defining file, line number, and signature for a symbol (function, class, constant).",
        "parameters": {
            "symbol": "The symbol/identifier name to locate.",
        },
    },
    "server_session": {
        "description": "Manage background server processes and perform live HTTP requests for full-stack API verification. Actions: 'start' (command, port), 'request' (method, path, body), 'stop' (session_id), 'list'.",
        "parameters": {
            "action": "Action to perform: 'start', 'request', 'stop', or 'list'.",
            "command": "Server startup command (e.g. 'python -m uvicorn app.main:app --port 8000' or 'node server.js'). Required for 'start'.",
            "port": "Port to bind/request (e.g. 8000, 3000, 5000).",
            "method": "HTTP method for 'request' (GET, POST, PUT, DELETE). Default GET.",
            "path": "HTTP path to hit (e.g. '/api/items', '/health'). Default '/'.",
            "body": "JSON payload or string for POST/PUT requests.",
            "session_id": "Session ID returned from start, required for 'stop' or targeting specific session in 'request'.",
        },
    },
    "git_diff": {
        "description": "Get structured git diff and file change summary compared to the last checkpoint commit or specific revision.",
        "parameters": {
            "since_commit": "Commit hash to compare against. If omitted, compares to the latest rony-turn-N checkpoint or HEAD.",
            "paths": "Optional list of file paths to limit diff scope.",
        },
    },
    "find_dead_code": {
        "description": "Analyze workspace dependency graph and detect unreferenced or orphan source files with zero incoming imports.",
        "parameters": {
            "paths": "Optional list of paths to scan.",
        },
    },
    "update_architecture_doc": {
        "description": "Scan workspace structure and generate/update ARCHITECTURE.md with module map and key entry points.",
        "parameters": {
            "reason": "Reason for updating the architecture documentation.",
        },
    },
}

OPENAI_HARNESS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_tests",
            "description": "Discover all pytest test node IDs in the workspace without executing them (runs pytest --collect-only -q). Read-only.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_single_test",
            "description": "Run a single specific test by its pytest node ID (e.g. 'tests/test_foo.py::test_bar').",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_node_id": {
                        "type": "string",
                        "description": "The pytest node ID to run (e.g. tests/test_foo.py::test_bar)",
                    },
                },
                "required": ["test_node_id"],
            },
        },
    },
]

def _is_command_malicious(command: str) -> bool:
    """Detect injection / remote code execution payloads in terminal commands."""
    cmd_strip = command.strip()
    return any(re.search(pattern, cmd_strip, re.IGNORECASE) for pattern in MALICIOUS_COMMAND_PATTERNS)


def _is_command_safe(command: str, workspace: str = "") -> bool:
    """Check if a terminal command is on the strict safe allowlist and path-contained.

    Returns True ONLY for commands explicitly allowlisted and operating within workspace.
    Everything else returns False (fail closed).
    """
    cmd = command.strip()
    if not cmd:
        return False

    # Reject compound operators (pipes, chains, redirects, subshells)
    if any(op in cmd for op in ("|", "&&", "||", ";", ">", ">>", "<", "`", "$(")):
        return False

    cmd_lower = cmd.lower()
    # Exact match
    if cmd_lower in SAFE_COMMAND_ALLOWLIST:
        return True

    # Prefix match
    is_allowlisted_prefix = False
    for prefix in SAFE_COMMAND_PREFIXES:
        if cmd_lower.startswith(prefix):
            is_allowlisted_prefix = True
            break

    if not is_allowlisted_prefix:
        return False

    # Path argument containment verification for commands with path args
    if workspace:
        file_cmd_prefixes = ("cat ", "type ", "ls ", "dir ", "head ", "tail ", "grep ", "findstr ")
        if any(cmd_lower.startswith(pfx) for pfx in file_cmd_prefixes):
            args = cmd.split()[1:]
            for raw_arg in args:
                arg = raw_arg.strip().strip("\"'")
                if not arg or arg.startswith("-"):
                    continue
                # Explicitly reject absolute paths, drive letters, and parent traversals
                if arg.startswith("/") or arg.startswith("\\") or (len(arg) >= 2 and arg[1] == ":") or ".." in arg.replace("\\", "/").split("/"):
                    return False
                try:
                    target_path = Path(workspace) / arg
                    if not ensure_within_workspace(workspace, str(target_path)):
                        return False
                except Exception:
                    return False
        else:
            parts = cmd.split(maxsplit=1)
            if len(parts) > 1:
                arg = parts[1].strip().strip("\"'")
                if not arg.startswith("-"):  # skip flags like -la
                    try:
                        target_path = Path(arg)
                        if target_path.is_absolute():
                            norm_ws = normalize_workspace(workspace)
                            if not str(target_path.resolve()).startswith(str(norm_ws.resolve())):
                                return False
                        elif ".." in arg.replace("\\", "/").split("/"):
                            ensure_within_workspace(workspace, arg)
                    except Exception:
                        return False

    return True


def _read_file_cached(full_path: Path) -> str:
    """Read file content, reusing cached result if file mtime hasn't changed."""
    str_path = str(full_path.resolve())
    mtime = full_path.stat().st_mtime
    cached = _file_read_cache.get(str_path)
    if cached and cached[0] == mtime:
        return cached[1]
    content = full_path.read_text(encoding="utf-8", errors="replace")
    _file_read_cache[str_path] = (mtime, content)
    return content


def _load_project_memory(workspace: str) -> str:
    """Load persistent user preferences & project conventions from RONY.md."""
    try:
        if not workspace:
            return ""
        p = Path(workspace) / "RONY.md"
        if p.is_file():
            content = p.read_text(encoding="utf-8", errors="replace").strip()
            return content[:PROJECT_MEMORY_MAX_CHARS]
    except Exception as exc:
        logger.warning("chat_harness: failed to load RONY.md: %s", exc)
    return ""


def _handle_memory_write(workspace: str, arguments: dict) -> tuple[bool, str]:
    """Append a user-stated preference or project convention to RONY.md."""
    fact = arguments.get("fact") or arguments.get("memory") or arguments.get("content") or ""
    if not fact or not str(fact).strip():
        return False, "Parameter 'fact' cannot be empty"
    try:
        p = Path(workspace) / "RONY.md"
        fact_str = str(fact).strip()
        if fact_str.startswith(("- ", "* ")):
            fact_str = fact_str[2:].strip()

        raw_existing = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "# Project Memory (RONY.md)\n\n"
        lines = [line.rstrip() for line in raw_existing.splitlines()]

        # Separate headers from bullets
        header_lines = [l for l in lines if not l.strip().startswith(("-", "*"))]
        if not header_lines:
            header_lines = ["# Project Memory (RONY.md)"]

        bullet_lines = [l for l in lines if l.strip().startswith(("-", "*"))]

        # Deduplication check
        existing_facts = {l.strip().lstrip("-* ").strip().lower() for l in bullet_lines}
        if fact_str.lower() not in existing_facts:
            bullet_lines.append(f"- {fact_str}")

        # Cap at 50 bullets
        if len(bullet_lines) > 50:
            bullet_lines = bullet_lines[-50:]

        content_parts = header_lines + [""] + bullet_lines
        final_content = "\n".join(content_parts).strip() + "\n"
        p.write_text(final_content, encoding="utf-8")
        return True, f"Saved to project memory: '{fact_str}'"
    except Exception as exc:
        return False, f"Failed to update RONY.md: {exc}"


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


def _should_audit_staged_changes(staged_changes: list[FileChange], user_query: str) -> bool:
    """Determine if staged changes require structural quality auditing (generation/creation tasks)."""
    if not staged_changes:
        return False
    if any(c.original == "" for c in staged_changes):
        return True
    q_lower = user_query.lower()
    return any(term in q_lower for term in ("build", "create", "generate", "write", "portfolio", "html", "website", "app", "make", "new file"))


def _validate_smart_edit(
    workspace: str,
    arguments: dict,
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
    arguments: dict,
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


def _handle_list_tests(workspace: str, arguments: dict | None = None) -> ToolResult:
    """Discover pytest test node IDs in the workspace (runs pytest --collect-only -q). Read-only, no approval needed."""
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
                output="No tests collected in workspace (pytest found 0 tests).",
            )

        capped_nodes = node_ids[:50]
        header = f"=== COLLECTED TESTS ({total_count} total" + (f", showing first {len(capped_nodes)}" if total_count > 50 else "") + ") ==="
        body = "\n".join(capped_nodes)
        if total_count > 50:
            body += f"\n... and {total_count - 50} more tests"

        return ToolResult(
            tool_name="list_tests",
            success=True,
            output=f"{header}\n{body}",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool_name="list_tests", success=False, output="", error="pytest --collect-only timed out after 20s")
    except Exception as exc:
        return ToolResult(tool_name="list_tests", success=False, output="", error=f"Failed to list tests: {exc}")


def _handle_run_single_test(workspace: str, arguments: dict) -> ToolResult:
    """Run a single targeted pytest test by its node ID (e.g. tests/test_parser.py::test_empty_input)."""
    node_id = arguments.get("node_id", "") or arguments.get("test", "") or arguments.get("test_id", "")
    if not node_id or not str(node_id).strip():
        return ToolResult(tool_name="run_single_test", success=False, output="", error="Missing required parameter: node_id")

    node_id_clean = str(node_id).strip().strip("\"'")
    if any(ch in node_id_clean for ch in [";", "&", "|", "`", "$", "<", ">", "\n", "\r"]):
        return ToolResult(tool_name="run_single_test", success=False, output="", error=f"Invalid node_id: '{node_id_clean}'")

    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        cmd = ["python", "-m", "pytest", node_id_clean, "-q"]
        proc = subprocess.run(
            cmd,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        status_str = "PASSED" if proc.returncode == 0 else f"FAILED (exit code {proc.returncode})"

        if proc.returncode == 0:
            summary = f"1 test passed: {node_id_clean}"
            lines = [l.strip() for l in raw_output.splitlines() if "passed" in l.lower() or "===" in l]
            if lines:
                summary += f" ({lines[-1]})"
        else:
            summary = summarize_test_output(raw_output, max_chars=1200)

        return ToolResult(
            tool_name="run_single_test",
            success=True,
            output=f"=== TEST RUN: pytest {node_id_clean} [{status_str}] ===\n{summary}",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool_name="run_single_test", success=False, output="", error=f"Test timed out after 30s: {node_id_clean}")
    except Exception as exc:
        return ToolResult(tool_name="run_single_test", success=False, output="", error=f"Execution error: {exc}")
