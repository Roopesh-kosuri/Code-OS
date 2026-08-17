"""
chat_harness.py — Lightweight autonomous coding agent loop for Rony Agent in CODE OS chat.

This is an isolated, fast, and robust agent harness providing:
- Bounded, observable, and adaptive tool-use loop
- Direct SSE streaming with interactive security approval gates
- False-success guard preventing intent-only responses from ending as successful
- Semantic & symbol workspace retrieval (RAG)
- Smart proposal-gated code editing with exact-match pre-validation
- Token history compaction to prevent quadratic context growth
- Automatic Duo Loop escalation for difficult multi-pass tasks
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...core.paths import ensure_within_workspace, normalize_workspace
from ..settings.service import get_api_key
from .schemas import ChatMessage, ChatRequest, EditProposalRequest, FileChange
from .service import provider_for, create_proposal, PROPOSAL_RE
from .context_service import gather_context
from ..search.semantic_service import semantic_search
from .artifact_auditor import audit_generated_artifact, ArtifactAuditReport

# Reuse tool implementations from agent_tools (READ-ONLY import — no modifications)
from .agents.agent_tools import (
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

logger = logging.getLogger(__name__)

# ── Constants & Limits ───────────────────────────────────────────────────────

MAX_AGENT_ITERATIONS = 12
MAX_TOOL_CALLS_PER_ITERATION = 5
MAX_RETRY_BEFORE_ESCALATE = 3
SEMANTIC_SEARCH_TOP_K = 10
COMMAND_APPROVAL_TIMEOUT_SECONDS = 60.0
COMPACTION_THRESHOLD_TURNS = 5

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

# Safe prefixes
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


def _is_command_safe(command: str) -> bool:
    """Check if a terminal command is on the strict safe allowlist.
    
    Returns True ONLY for commands explicitly allowlisted.
    Everything else returns False (fail closed).
    """
    cmd = command.strip().lower()
    if not cmd:
        return False
    
    # Reject compound operators (pipes, chains, redirects, subshells)
    if any(op in cmd for op in ("|", "&&", "||", ";", ">", ">>", "<", "`", "$(")):
        return False
    
    # Exact match
    if cmd in SAFE_COMMAND_ALLOWLIST:
        return True
    
    # Prefix match
    for prefix in SAFE_COMMAND_PREFIXES:
        if cmd.startswith(prefix):
            return True
    
    return False


# ── Pending Approval State ───────────────────────────────────────────────────

COMMAND_APPROVAL_TIMEOUT_SECONDS: float = 60.0
EDIT_APPROVAL_TIMEOUT_SECONDS: float = 300.0  # 5 minutes for reviewing file diffs


@dataclass
class PendingApproval:
    """A command or edit action awaiting user approval."""
    action_id: str
    action_type: str  # "command" | "edit"
    detail: str
    reason: str
    proposal_id: str = ""
    path: str = ""
    diff_summary: str = ""
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False
    created_at: float = field(default_factory=time.time)


_pending_approvals: dict[str, PendingApproval] = {}


async def approve_action(action_id: str) -> bool:
    """Approve a pending action."""
    pending = _pending_approvals.get(action_id)
    if not pending:
        return False
    pending.approved = True
    pending.event.set()
    return True


async def reject_action(action_id: str) -> bool:
    """Reject a pending action."""
    pending = _pending_approvals.get(action_id)
    if not pending:
        return False
    pending.approved = False
    pending.event.set()
    return True


# ── SSE Event Formatting ─────────────────────────────────────────────────────

def _sse_event(event_type: str, data: dict) -> str:
    """Format a typed Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _sse_status(status_type: str, message: str, **kwargs) -> str:
    payload = {"type": status_type, "message": message}
    payload.update(kwargs)
    return _sse_event("status", payload)


def _sse_token(content: str) -> str:
    return _sse_event("token", {"content": content})


def _sse_plan(steps: list[str], current: int = 0, **kwargs) -> str:
    payload = {"steps": steps, "current": current}
    payload.update(kwargs)
    return _sse_event("plan", payload)


def _sse_approval_request(
    action_id: str,
    action_type: str,
    detail: str,
    reason: str,
    proposal_id: str = "",
    path: str = "",
    diff_summary: str = "",
    command: str = "",
) -> str:
    return _sse_event("approval_request", {
        "action_id": action_id,
        "action_type": action_type,
        "detail": detail,
        "reason": reason,
        "proposal_id": proposal_id,
        "path": path,
        "diff_summary": diff_summary,
        "command": command or (detail if action_type == "command" else ""),
    })


def _sse_proposal(proposal_id: str, path: str, **kwargs) -> str:
    payload = {"proposal_id": proposal_id, "path": path}
    payload.update(kwargs)
    return _sse_event("proposal", payload)


def _sse_command_result(command: str, output: str, exit_code: int = 0, success: bool = True) -> str:
    """Emit command execution stdout/stderr and exit code to live chat feed."""
    return _sse_event("command_result", {
        "command": command,
        "output": output,
        "exit_code": exit_code,
        "success": success,
    })


def _sse_metrics(iterations: int, tools_executed: int, duration_ms: float) -> str:
    return _sse_event("metrics", {
        "iterations": iterations,
        "tools_executed": tools_executed,
        "duration_ms": duration_ms,
    })


def _sse_done(success: bool, message: str = "", **kwargs) -> str:
    payload = {"success": success, "message": message}
    payload.update(kwargs)
    return _sse_event("done", payload)


def _sse_error(message: str, **kwargs) -> str:
    payload = {"message": message}
    payload.update(kwargs)
    return _sse_event("error", payload)


# ── Plan & Control Markers Parsing ───────────────────────────────────────────

_PLAN_RE = re.compile(
    r"\[PLAN\]\s*\n?(.*?)\n?\[/PLAN\]",
    re.DOTALL | re.IGNORECASE,
)

def _parse_plan(response: str) -> list[str] | None:
    """Extract ordered step list from [PLAN] ... [/PLAN] block."""
    match = _PLAN_RE.search(response)
    if not match:
        return None
    
    raw_steps = match.group(1).strip().splitlines()
    steps: list[str] = []
    for line in raw_steps:
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[\d]+[.)]\s*", "", line)
        line = re.sub(r"^[-*]\s*", "", line)
        line = line.strip()
        if line:
            steps.append(line)
    
    return steps if steps else None


def _has_escalate_marker(response: str) -> bool:
    """Check if the LLM has requested Duo Loop escalation."""
    return "[ESCALATE]" in response


def _response_is_done(response: str) -> bool:
    """Check if the LLM has completed all task steps."""
    return "[DONE]" in response


def _declares_tool_intent(text: str) -> bool:
    """Detect if response declared intent to execute tools without calling them."""
    if "[DONE]" in text:
        return False
    lower = text.lower()
    
    # Exclude explanations or reports of test/command results
    if any(res in lower for res in [
        "test passed", "tests passed", "test failed", "tests failed",
        "pytest passed", "pytest failed", "output shows", "result is",
        "exited with code", "failed with exit", "passed with", "is not working",
        "is working", "it is working", "it is not working",
    ]):
        return False

    explicit_intent_phrases = [
        "use the run_test tool", "use the run_command tool", "use the read_file tool",
        "use the edit_file tool", "use the search_code tool", "use the append_file tool",
        "let's run pytest", "we need to run pytest", "let's run the test",
        "we need to run tests", "i will run pytest", "i will run the test",
        "let me run the test", "let me run pytest", "i'll run python", "let's run python",
        "i will execute", "let's execute", "we need to execute",
        "i will run", "let's run", "we need to run", "let me run", "i'll run",
        "edit_file", "append_file", "generate the file", "we'll output",
        "i will create", "i will generate", "let me create", "let's create",
        "we will create", "we need to create", "i'll create", "we will generate",
        "i will write", "let's write", "we'll write", "we will output", "i'll output",
        "i will output", "we'll output edit_file", "output edit_file", "output append_file",
        "create hello.html", "generate hello.html", "create file", "write file",
        "build the portfolio", "create the portfolio", "generate the portfolio",
        "creating hello.html", "generating hello.html", "let's build", "i will build",
        "we will build", "let me build", "i'll build", "let's generate", "let me generate",
    ]
    return any(phrase in lower for phrase in explicit_intent_phrases)


# ── Smart Code Editing Tool Handler ──────────────────────────────────────────

def _find_mismatch_context(current_content: str, original: str) -> str:
    """Find the first differing line/region between expected original and file content."""
    import difflib
    orig_lines = original.splitlines()
    curr_lines = current_content.splitlines()

    if not orig_lines:
        return ""

    # Try to locate the starting line of original in curr_lines
    first_orig = orig_lines[0].strip()
    match_indices = [i for i, line in enumerate(curr_lines) if first_orig and first_orig in line]

    if match_indices:
        best_idx = match_indices[0]
        for offset, o_line in enumerate(orig_lines):
            curr_idx = best_idx + offset
            if curr_idx >= len(curr_lines):
                return (
                    f"First mismatch at line {curr_idx + 1}:\n"
                    f"  Expected: '{o_line.strip()}'\n"
                    f"  Actual:   (file ended early)"
                )
            if o_line.strip() != curr_lines[curr_idx].strip():
                snippet_start = max(0, curr_idx - 2)
                snippet_end = min(len(curr_lines), curr_idx + 3)
                actual_snippet = "\n".join(f"  Line {i+1}: {curr_lines[i]}" for i in range(snippet_start, snippet_end))
                return (
                    f"First differing line at line {curr_idx + 1}:\n"
                    f"  Expected: '{o_line.strip()}'\n"
                    f"  Actual:   '{curr_lines[curr_idx].strip()}'\n"
                    f"Actual file context around line {curr_idx + 1}:\n{actual_snippet}"
                )

    # First line not matched exactly — find closest matching line in file using difflib
    close = difflib.get_close_matches(first_orig, curr_lines, n=1, cutoff=0.3)
    if close:
        close_line = close[0]
        close_idx = curr_lines.index(close_line)
        snippet_start = max(0, close_idx - 2)
        snippet_end = min(len(curr_lines), close_idx + 3)
        actual_snippet = "\n".join(f"  Line {i+1}: {curr_lines[i]}" for i in range(snippet_start, snippet_end))
        return (
            f"First line '{first_orig[:50]}' was not found verbatim.\n"
            f"Closest match in file is line {close_idx + 1}: '{close_line.strip()}'\n"
            f"File context around line {close_idx + 1}:\n{actual_snippet}"
        )
    else:
        sample = "\n".join(f"  Line {i+1}: {curr_lines[i]}" for i in range(min(5, len(curr_lines))))
        return f"Starting line '{first_orig[:50]}' was not found. File begins with:\n{sample}"


def _validate_smart_edit(workspace: str, arguments: dict) -> tuple[bool, str, FileChange | None]:
    """Validate a file edit request against the workspace files."""
    raw_path = arguments.get("path", "")
    rel_path = _clean_rel_path(raw_path)
    original = arguments.get("original", "")
    updated = arguments.get("updated", "")

    if not rel_path or rel_path == ".":
        return False, "Missing required parameter: path", None
    if not updated and not original:
        return False, "Both 'original' and 'updated' are empty — nothing to edit", None

    try:
        target = ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return False, f"Path rejected: {exc}", None

    if target.is_file():
        try:
            current_content = target.read_text(encoding="utf-8", errors="replace")
            if original.strip():
                if original in current_content:
                    pass
                elif original.replace("\r\n", "\n") in current_content.replace("\r\n", "\n"):
                    pass
                elif original.strip() in current_content:
                    pass
                elif original.replace("'", '"') in current_content.replace("'", '"'):
                    pass
                elif original.replace('"', "'") in current_content.replace('"', "'"):
                    pass
                else:
                    mismatch_info = _find_mismatch_context(current_content, original)
                    diff_detail = f"\n\n[Mismatch Diagnostic]\n{mismatch_info}" if mismatch_info else ""
                    return False, (
                        f"The 'original' snippet was not found verbatim in '{rel_path}'. "
                        f"Please review the mismatch below and use exact line content before editing:{diff_detail}"
                    ), None
        except OSError as exc:
            return False, f"Error reading file '{rel_path}': {exc}", None
    else:
        original = ""

    change = FileChange(path=rel_path, original=original, updated=updated)
    return True, "", change


def _handle_append_file(workspace: str, arguments: dict, staged_changes: list[FileChange]) -> tuple[bool, str, FileChange | None]:
    """Append content to a staged or existing file without requiring verbatim original."""
    raw_path = arguments.get("path", "")
    rel_path = _clean_rel_path(raw_path)
    content = arguments.get("content") or arguments.get("updated") or ""

    if not rel_path or rel_path == ".":
        return False, "Missing required parameter: path", None
    if not content:
        return False, "Parameter 'content' is empty — nothing to append", None

    try:
        target = ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return False, f"Path rejected: {exc}", None

    # Check if there is already a staged change for this file
    existing = next((c for c in staged_changes if c.path == rel_path), None)
    if existing:
        if existing.updated and not existing.updated.endswith("\n") and not content.startswith("\n"):
            existing.updated += "\n" + content
        else:
            existing.updated += content
        return True, "", existing

    if target.is_file():
        try:
            current_content = target.read_text(encoding="utf-8", errors="replace")
            new_content = current_content + ("\n" if current_content and not current_content.endswith("\n") else "") + content
            change = FileChange(path=rel_path, original=current_content, updated=new_content)
        except OSError as exc:
            return False, f"Error reading file '{rel_path}': {exc}", None
    else:
        change = FileChange(path=rel_path, original="", updated=content)

    staged_changes.append(change)
    return True, "", change


def _generate_diff_summary(change: FileChange) -> str:
    """Generate a clean unified diff preview for the inline approval card."""
    import difflib
    orig_lines = change.original.splitlines(keepends=True) if change.original else []
    upd_lines = change.updated.splitlines(keepends=True) if change.updated else []
    diff = list(difflib.unified_diff(orig_lines, upd_lines, fromfile=f"a/{change.path}", tofile=f"b/{change.path}", n=3))
    if diff:
        clean_lines = [l.rstrip("\r\n") for l in diff]
        if len(clean_lines) > 30:
            return "\n".join(clean_lines[:30]) + f"\n... ({len(clean_lines) - 30} more lines in Diff Inspector)"
        return "\n".join(clean_lines)
    elif not change.original and change.updated:
        upd_list = change.updated.splitlines()
        preview = [f"+ {l}" for l in upd_list[:20]]
        if len(upd_list) > 20:
            preview.append(f"... ({len(upd_list) - 20} more lines)")
        return f"--- /dev/null\n+++ b/{change.path}\n" + "\n".join(preview)
    return f"Modified {change.path}"


def _handle_smart_edit_file(workspace: str, arguments: dict, staged_changes: list) -> ToolResult:
    """Backward compatibility helper for staging file edits."""
    if arguments.get("append") is True:
        valid, err_msg, change = _handle_append_file(workspace, arguments, staged_changes)
    else:
        valid, err_msg, change = _validate_smart_edit(workspace, arguments)
        if valid and change:
            existing = next((c for c in staged_changes if c.path == change.path), None)
            if existing:
                existing.original = change.original
                existing.updated = change.updated
            else:
                staged_changes.append(change)
    if not valid or not change:
        return ToolResult(tool_name="edit_file", success=False, output="", error=err_msg or "Invalid edit arguments")
    action = "new file" if not change.original else "modified file"
    return ToolResult(
        tool_name="edit_file",
        success=True,
        output=f"✓ Staged {action} for '{change.path}' ({len(change.updated)} chars ready for proposal)",
    )


# ── Terminal Command Execution ───────────────────────────────────────────────

async def _execute_command_async(workspace: str, command: str) -> ToolResult:
    """Execute a shell command asynchronously sandboxed to the workspace root without blocking the event loop."""
    from ..terminal.service import _build_safe_environment
    
    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()
        
        effective_command = command.strip()
        if os.name == "nt":
            if effective_command.startswith("pytest ") or effective_command == "pytest":
                effective_command = "python -m " + effective_command
            elif effective_command.startswith("python3 ") or effective_command == "python3":
                effective_command = "python " + effective_command[8:]
            args = ["powershell", "-NoLogo", "-NoProfile", "-Command", effective_command]
        else:
            args = ["bash", "-c", effective_command]
        
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(norm_ws),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=35.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return ToolResult(
                tool_name="run_command",
                success=False,
                output="",
                error=f"Command timed out after 35 seconds: {command}"
            )
        
        raw_output = (stdout.decode("utf-8", errors="replace") or "") + \
                     ("\n" + stderr.decode("utf-8", errors="replace") if stderr else "")
        status_str = "SUCCESS" if proc.returncode == 0 else f"EXIT {proc.returncode}"
        
        if len(raw_output) > 3000:
            raw_output = raw_output[:3000] + "\n... [Output truncated to preserve token efficiency]"
        
        return ToolResult(
            tool_name="run_command",
            success=proc.returncode == 0,
            output=f"=== COMMAND: {command} [{status_str}] ===\n{raw_output.strip() or '(no output)'}",
            error="" if proc.returncode == 0 else f"Process exited with code {proc.returncode}"
        )
    except Exception as exc:
        return ToolResult(
            tool_name="run_command",
            success=False,
            output="",
            error=f"Execution error: {exc}"
        )


def _execute_command(workspace: str, command: str) -> ToolResult:
    """Synchronous fallback wrapper for shell command execution."""
    from ..terminal.service import _build_safe_environment
    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()
        
        effective_command = command.strip()
        if os.name == "nt":
            if effective_command.startswith("pytest ") or effective_command == "pytest":
                effective_command = "python -m " + effective_command
            elif effective_command.startswith("python3 ") or effective_command == "python3":
                effective_command = "python " + effective_command[8:]
            args = ["powershell", "-NoLogo", "-NoProfile", "-Command", effective_command]
        else:
            args = ["bash", "-c", effective_command]
        
        proc = subprocess.run(
            args,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=35.0,
        )
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        status_str = "SUCCESS" if proc.returncode == 0 else f"EXIT {proc.returncode}"
        
        if len(raw_output) > 3000:
            raw_output = raw_output[:3000] + "\n... [Output truncated to preserve token efficiency]"
        
        return ToolResult(
            tool_name="run_command",
            success=proc.returncode == 0,
            output=f"=== COMMAND: {command} [{status_str}] ===\n{raw_output.strip() or '(no output)'}",
            error="" if proc.returncode == 0 else f"Process exited with code {proc.returncode}"
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_name="run_command",
            success=False,
            output="",
            error=f"Command timed out after 35 seconds: {command}"
        )
    except Exception as exc:
        return ToolResult(
            tool_name="run_command",
            success=False,
            output="",
            error=f"Execution error: {exc}"
        )


# ── Tool Registry & Parsing ──────────────────────────────────────────────────

HARNESS_TOOLS = {
    **AGENT_TOOLS,
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
        "description": "Execute a terminal command in the workspace. Safe read-only commands (ls, cat, grep, git status) run immediately. Other commands trigger an interactive user approval card.",
        "parameters": {
            "command": "The terminal command string to execute.",
        },
    },
}

_EXTENDED_TOOL_RE = re.compile(
    r"\[TOOL_CALL:\s*(?P<name>[a-z_]+)\s*\]\s*(?P<body>.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL | re.IGNORECASE,
)

# Markdown code block fallback: ```tool_call / ```json {"tool": "..."}
_CODEBLOCK_TOOL_RE = re.compile(
    r"```(?:tool_call|json)\s*\n(\{\s*\"(?:tool|name)\"\s*:\s*\"[a-z_]+\"[\s\S]*?\})\s*```",
    re.IGNORECASE,
)


def _parse_tool_calls_extended(response: str) -> list[ToolCall]:
    """Extract tool calls from LLM response across multiple formatting styles."""
    calls: list[ToolCall] = []
    
    # 1. Standard [TOOL_CALL: name] ... [/TOOL_CALL]
    for match in _EXTENDED_TOOL_RE.finditer(response):
        name = match.group("name").strip().lower()
        body = match.group("body").strip()
        raw = match.group(0)
        
        if name not in HARNESS_TOOLS:
            logger.warning("chat_harness: skipping unknown tool '%s'", name)
            continue
        
        try:
            json_match = re.search(r'\{.*\}', body, re.DOTALL)
            if json_match:
                args = json.loads(json_match.group())
            else:
                args = {"path": body.strip().strip("\"'"), "command": body.strip(), "content": body.strip()}
        except json.JSONDecodeError:
            args = {"path": body.strip().strip("\"'"), "command": body.strip(), "content": body.strip()}
        
        calls.append(ToolCall(name=name, arguments=args, raw_text=raw))
    
    if calls:
        return calls[:MAX_TOOL_CALLS_PER_ITERATION]
    
    # 2. Markdown json codeblock fallback
    for match in _CODEBLOCK_TOOL_RE.finditer(response):
        try:
            data = json.loads(match.group(1))
            name = (data.get("tool") or data.get("name") or "").lower()
            args = data.get("arguments") or data.get("args") or {k: v for k, v in data.items() if k not in ("tool", "name")}
            if name in HARNESS_TOOLS and isinstance(args, dict):
                calls.append(ToolCall(name=name, arguments=args, raw_text=match.group(0)))
        except Exception:
            pass

    return calls[:MAX_TOOL_CALLS_PER_ITERATION]


def _clean_response_text(text: str) -> str:
    """Strip tool calls, plan tags, and control markers from response to get the user-visible prose."""
    cleaned = _EXTENDED_TOOL_RE.sub("", text)
    cleaned = _CODEBLOCK_TOOL_RE.sub("", cleaned)
    cleaned = _PLAN_RE.sub("", cleaned)
    cleaned = cleaned.replace("[DONE]", "").replace("[ESCALATE]", "").replace("[TRUNCATED: length]", "")
    return cleaned.strip()


def _is_response_truncated(response: str) -> bool:
    """Detect if response was cut off / truncated by output limits, timed out, or ended mid-tool-call."""
    if "[TRUNCATED:" in response:
        return True
    if "[TOOL_CALL:" in response and "[/TOOL_CALL]" not in response:
        return True
    if "[Error:" in response and any(kw in response.lower() for kw in ("timed out", "timeout", "network error", "connection error")):
        return True
    return False


def _extract_heuristic_tool_calls(response: str, user_query: str) -> list[ToolCall]:
    """Fallback heuristic: only fire on explicit intent phrases, never on past-tense explanations or bare mentions."""
    if "[DONE]" in response:
        return []
    lower_resp = response.lower()
    
    # Never extract if the text is discussing test/command results
    if any(res in lower_resp for res in [
        "test passed", "tests passed", "test failed", "tests failed",
        "pytest passed", "pytest failed", "result:", "output:", "exited with code",
        "failed with exit", "passed with", "is not working", "is working",
        "it is working", "it is not working",
    ]):
        return []

    calls: list[ToolCall] = []

    # 1. Explicit Test execution intent in response
    test_intents = [
        "let's run pytest", "we need to run pytest", "let me run pytest",
        "i will run pytest", "use the run_test tool", "let me run the test",
        "i will run the test", "we need to run tests", "let's run tests",
    ]
    if any(ti in lower_resp for ti in test_intents):
        test_file_match = re.search(r"([\w\-./\\]*test[\w\-./\\]*\.py)", response + " " + user_query, re.IGNORECASE)
        if test_file_match:
            cmd = f"pytest {test_file_match.group(1)}"
            calls.append(ToolCall(name="run_command", arguments={"command": cmd}))
        else:
            calls.append(ToolCall(name="run_command", arguments={"command": "pytest"}))
        return calls

    # 2. Explicit Terminal command execution intent
    cmd_intents = [
        "use the run_command tool", "i will run the command", "let me run the command",
        "we need to run the command", "let's run the command", "execute the command",
    ]
    if any(ci in lower_resp for ci in cmd_intents):
        cmd_match = re.search(r"`([^`]+)`", response)
        if cmd_match:
            calls.append(ToolCall(name="run_command", arguments={"command": cmd_match.group(1)}))
            return calls

    # 3. Explicit Read file intent
    read_intents = [
        "use the read_file tool", "let me read the file", "i will read the file",
        "we need to read the file", "let's read the file",
    ]
    if any(ri in lower_resp for ri in read_intents):
        file_match = re.search(r"`([^`]+\.[a-zA-Z0-9]+)`", response) or re.search(r"([\w\-./\\]+\.[a-zA-Z0-9]+)", response)
        if file_match:
            calls.append(ToolCall(name="read_file", arguments={"path": file_match.group(1)}))
            return calls

    # 4. Explicit File creation / edit intent with code block in response
    edit_intents = [
        "edit_file", "append_file", "generate the file", "we'll output", "i will create",
        "we will create", "let me create", "let's create", "i'll create", "we will generate",
        "i will write", "let's write", "we'll write", "here is the code", "here is the full",
        "here is hello.html", "here is the file", "create hello.html", "generate hello.html",
        "portfolio", "html", "creating hello.html", "generating hello.html",
    ]
    if any(ei in lower_resp for ei in edit_intents):
        code_match = re.search(r"```([a-zA-Z0-9_\-]+)?\s*\n([\s\S]+?)\n```", response)
        if code_match:
            code_content = code_match.group(2).strip()
            file_match = re.search(r"([a-zA-Z0-9_\-./\\]+\.(?:html|py|js|ts|tsx|jsx|css|json|md|txt|sh|cpp|c|rs|go))", response + " " + user_query)
            if file_match and len(code_content) > 10:
                file_path = file_match.group(1).strip()
                calls.append(ToolCall(name="edit_file", arguments={"path": file_path, "original": "", "updated": code_content}))
                return calls

    return calls


def _has_tool_calls_extended(response: str) -> bool:
    return bool(_EXTENDED_TOOL_RE.search(response)) or bool(_CODEBLOCK_TOOL_RE.search(response))


# ── Native Tool Definitions for AI Providers ──────────────────────────────────

OPENAI_HARNESS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_test",
            "description": "Execute pytest or npm test files in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The test command to execute, e.g. 'pytest tests/test_generation.py'",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell or terminal command in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The terminal command string to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents with line windowing support.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "start_line": {"type": "integer", "description": "1-indexed start line"},
                    "limit": {"type": "integer", "description": "Number of lines to read"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List directory tree contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '.')"},
                    "max_depth": {"type": "integer", "description": "Recursion depth"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for text or symbol patterns across workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text pattern to find"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Search codebase by meaning using TF-IDF ranking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Stage a file edit with original and updated contents. For new files or initial chunk, original is empty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "original": {"type": "string", "description": "Original text snippet to replace (empty for new file)"},
                    "updated": {"type": "string", "description": "New replacement content"},
                },
                "required": ["path", "updated"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append content chunk to a staged or existing file without needing original text. Used for chunked large-file generation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "content": {"type": "string", "description": "Content chunk to append to the file"},
                },
                "required": ["path", "content"],
            },
        },
    },
]


# ── System Prompt Builder ────────────────────────────────────────────────────

_CHAT_AGENT_SYSTEM_PROMPT = """You are Rony Agent — a high-performance autonomous coding partner embedded in the user's IDE.
You have direct, sandboxed access to the workspace through tools.

## Operating Principles
1. **Understand First**: Inspect relevant files with `read_file`, `list_directory`, `search_code`, or `semantic_search` before editing.
2. **Decompose Multi-Step Work**: For multi-step tasks, define a step-by-step plan FIRST:
   [PLAN]
   1. Read existing implementation in module X
   2. Run pytest to check baseline
   3. Stage targeted edit to module X
   4. Run test suite to verify
   [/PLAN]
3. **Execute Tools Directly**: When you need to read files, run tests, or execute commands, emit the tool call block directly. NEVER say "We need to run tests. Use run_test tool." or tell the user how to run tools. YOU ARE THE AGENT — YOU MUST CALL THE TOOL YOURSELF.
4. **Targeted Precision**: When using `edit_file`, provide the exact `original` snippet to replace. Keep edits minimal and maintain existing architecture and style.
5. **Verify with Evidence**: Run tests or commands to verify results. If tests fail, read the assertion traceback and repair the code based on real evidence.
6. **Direct Answers & Completion**: When the user asks follow-up questions about past actions or results (e.g., "so is it correct code and working?"), answer directly and honestly in plain natural language citing the actual tool results from previous turns. Do NOT re-run tools unless explicitly asked. Output [DONE] when finished.
7. **Escalate When Stuck**: If an architectural tradeoff or repeated failure cannot be resolved after bounded attempts, output [ESCALATE] to invoke Duo Loop.
8. **Chunked Large File Generation**: For large files expected to exceed ~300–400 lines (or 1000+ lines), you MUST split generation across multiple tool calls: call `edit_file` (with original="") for the first chunk (HTML skeleton/head/styles), then call `append_file` for subsequent chunks (body sections, interactive JS, footers) until complete. NEVER output one giant payload that risks truncation.
9. **Permanent Generation Quality Standards** (Mandatory across all generated files & artifacts):
   - **No Padding / Filler**: NEVER pad to hit a line-count or size requirement with filler comments, blank lines, or copy-pasted repeated sections. Meet the intent (rich, complete, distinct content). If the numeric target cannot be met with real content, say so honestly instead of padding.
   - **Professional Iconography**: NEVER use emoji as icons in professional/premium deliverables — always use inline SVG icons (`<svg viewBox="...">`).
   - **Mobile Parallax Performance**: NEVER use `background-attachment: fixed` for parallax (broken/janky on mobile browsers) — use transform-based parallax (`rAF + translateY` on scroll) or clean modern CSS layout.
   - **Progressive Enhancement**: Anything that starts hidden (`opacity: 0`) for scroll animations MUST be gated behind a `.js` class the script adds to `<html>` (e.g., `html.js .reveal { opacity: 0; }` + `document.documentElement.classList.add('js')`). Content must NEVER stay invisible if JS fails or is disabled.
   - **Working Interactivity**: Every interactive element created (forms, toggles, buttons, links, filter chips) MUST have working logic behind it, or be explicitly labeled as a placeholder in the answer. No silent dead controls.
   - **Full Responsiveness**: Generated pages must be responsive with hamburger/slide-in nav below ~768px and NO horizontal overflow.
   - **Accessibility & Motion**: Respect `@media (prefers-reduced-motion: reduce)`; include `aria-label`s on icon-only controls.
   - **Identity Consistency**: Maintain the exact same name and branding across `<title>`, meta, header, hero `<h1>`, and footer — never mix disparate names or placeholder identities.
10. **Post-Generation Structural Self-Audit & Final Report Format**:
   - Before completing file creation/generation tasks with `[DONE]`, self-audit the code:
     - Tag balance & clean seams: exactly one `<style>` and `<script>`, no duplicate `<!DOCTYPE>` or `<html>`.
     - Wiring: all `href="#target"` match defined `id`s; all JS `getElementById` and `querySelector` match defined IDs; CSS classes match.
     - Interactivity: event listeners exist; counters end in visible non-zero state.
   - Your final response MUST follow this structured summary format:
     1. **What was built**: Core features, sections, and interactive capabilities.
     2. **Structural Audit Results**: List of verified/passed checks (e.g. tag balance, anchor wiring, JS selectors, mobile responsive queries, progressive enhancement).
     3. **Honest Metrics**: Total non-empty, non-comment line count (excluding blank lines and comment blocks). Never report artificial or padded counts.

## Tool Definitions

**read_file** — Inspect file contents with line windowing:
[TOOL_CALL: read_file]
{"path": "src/module.py", "start_line": 1, "limit": 200}
[/TOOL_CALL]

**list_directory** — Explore directory trees:
[TOOL_CALL: list_directory]
{"path": "src/", "max_depth": 2}
[/TOOL_CALL]

**search_code** — Exact text or symbol search:
[TOOL_CALL: search_code]
{"query": "function_name"}
[/TOOL_CALL]

**semantic_search** — Natural language semantic retrieval:
[TOOL_CALL: semantic_search]
{"query": "database connection retry logic"}
[/TOOL_CALL]

**edit_file** — Stage code changes (generates user-facing proposal):
[TOOL_CALL: edit_file]
{"path": "src/module.py", "original": "def old_fn(): pass", "updated": "def old_fn():\\n    return 42\\n"}
[/TOOL_CALL]
(For new files or initial chunk, set "original" to "")

**append_file** — Append content chunk to a staged or existing file without needing original text:
[TOOL_CALL: append_file]
{"path": "src/module.py", "content": "    return 42\\n"}
[/TOOL_CALL]

**run_test** — Execute pytest or npm test suites:
[TOOL_CALL: run_test]
{"command": "python -m pytest tests/test_module.py"}
[/TOOL_CALL]

**run_command** — Execute terminal command (read-only commands like cat, ls, git status run immediately; others trigger approval card):
[TOOL_CALL: run_command]
{"command": "pytest tests/test_generation.py"}
[/TOOL_CALL]

Rules: Up to {max_tools} tools per turn, maximum {max_iterations} total turns. Output [DONE] when finished.
"""


def _build_system_prompt(
    workspace: str,
    context: dict,
    semantic_results: list[dict] | None = None,
) -> str:
    """Construct full system prompt with workspace context."""
    base_prompt = (
        _CHAT_AGENT_SYSTEM_PROMPT
        .replace("{max_tools}", str(MAX_TOOL_CALLS_PER_ITERATION))
        .replace("{max_iterations}", str(MAX_AGENT_ITERATIONS))
    )
    prompt_parts = [base_prompt, f"\n## Workspace Root: {workspace}\n"]
    
    # Git status
    git_info = context.get("git_status")
    if git_info and isinstance(git_info, dict) and git_info.get("branch"):
        prompt_parts.append(f"Git branch: {git_info['branch']}")
        modified_files: list[str] = []
        if isinstance(git_info.get("unstaged"), list):
            modified_files.extend(str(f) for f in git_info["unstaged"] if f)
        if isinstance(git_info.get("staged"), list):
            modified_files.extend(str(f) for f in git_info["staged"] if f)
        if modified_files:
            prompt_parts.append(f"Modified files: {', '.join(modified_files[:10])}")
    
    # Active open file
    active = context.get("active_file")
    if active and isinstance(active, dict) and active.get("content"):
        name = active.get("name", "unknown")
        content = active["content"][:1500]
        prompt_parts.append(f"\n## Active File in Editor ({name}):\n```\n{content}\n```")
    
    # Semantic search matches
    if semantic_results:
        prompt_parts.append("\n## Top Relevant Workspace Files:")
        for i, res in enumerate(semantic_results[:SEMANTIC_SEARCH_TOP_K]):
            rel_p = res.get("relative_path", res.get("path", "unknown"))
            score = res.get("score", 0)
            lang = res.get("language", "")
            prompt_parts.append(f"  {i+1}. `{rel_p}` (score: {score:.3f}, {lang})")
    
    # Dependencies
    deps = context.get("dependencies", [])
    if deps and isinstance(deps, list):
        dep_str = ", ".join(f"{d['name']}@{d.get('version', '')}" for d in deps[:15] if isinstance(d, dict))
        if dep_str:
            prompt_parts.append(f"\nProject dependencies: {dep_str}")
    
    return "\n".join(prompt_parts)


# ── Conversation Compaction ──────────────────────────────────────────────────

def _compact_conversation_history(messages: list[ChatMessage], keep_recent_turns: int = 2) -> list[ChatMessage]:
    """Compact older tool calls and results in the message history to prevent token explosion."""
    if len(messages) <= keep_recent_turns * 2:
        return messages
    
    compacted: list[ChatMessage] = []
    cutoff_index = len(messages) - (keep_recent_turns * 2)
    
    for idx, msg in enumerate(messages):
        if idx == 0 or idx >= cutoff_index:
            compacted.append(msg)
            continue
        
        content = msg.content
        if msg.role == "user":
            if "Tool results:" in content or "[TOOL_RESULT:" in content or "Tool observation results:" in content:
                tool_names = re.findall(r"\[TOOL_RESULT:\s*([a-z_]+)\]", content)
                if tool_names:
                    summary = f"(Historical tool results for: {', '.join(set(tool_names))} — compacted to save context tokens)"
                    compacted.append(ChatMessage(role="user", content=summary))
                else:
                    compacted.append(msg)
            else:
                compacted.append(msg)
        elif msg.role == "assistant":
            # Compact older assistant tool call payloads (like giant append_file or edit_file code blocks)
            if "[TOOL_CALL:" in content and len(content) > 300:
                compact_tool_calls = re.sub(
                    r"(\[\s*TOOL_CALL:\s*([a-z_]+)\s*\])([\s\S]*?)(\[\s*/\s*TOOL_CALL\s*\])",
                    r"\1\n(Tool payload for \2 — compacted to save context tokens)\n\4",
                    content
                )
                compacted.append(ChatMessage(role="assistant", content=compact_tool_calls))
            else:
                compacted.append(msg)
        else:
            compacted.append(msg)
    
    return compacted


# ── Main Agent Loop ──────────────────────────────────────────────────────────

def _should_audit_staged_changes(staged_changes: list[FileChange], user_query: str) -> bool:
    """Determine if post-generation structural audit should run (creation/generation tasks only)."""
    if not staged_changes:
        return False
    # Run on creation tasks or newly created files, not simple targeted edits
    if any(c.original == "" for c in staged_changes):
        return True
    lower = user_query.lower()
    return any(k in lower for k in ("create", "generate", "build", "write", "portfolio", "html", "make", "new file"))


@dataclass
class ChatAgentRequest:
    """Request payload for the chat agent harness."""
    provider: str = "auto"
    model: str = ""
    base_url: str | None = None
    temperature: float = 0.2
    api_key_provider: str | None = None
    messages: list[dict] = field(default_factory=list)
    workspace: str = ""
    attached_paths: list[str] = field(default_factory=list)


async def run_chat_agent(request: ChatAgentRequest) -> AsyncIterator[str]:
    """Run the complete autonomous coding agent loop, streaming typed SSE events."""
    start_time = time.time()
    total_tools_executed = 0
    workspace = request.workspace

    if not workspace:
        yield _sse_error("No workspace root provided.")
        yield _sse_done(False, "No workspace root provided.")
        return

    try:
        # ── Phase 0: Context Gathering & Semantic RAG ────────────────────────
        yield _sse_status("thinking", "Analyzing request and gathering workspace context...")
        
        user_messages = [m for m in request.messages if m.get("role") == "user"]
        user_query = user_messages[-1]["content"] if user_messages else ""
        
        try:
            context = await gather_context(
                workspace=workspace,
                active_path=request.attached_paths[0] if request.attached_paths else None,
                open_tabs=request.attached_paths,
                query=user_query,
                provider_config={"provider": request.provider, "preset": request.provider},
            )
        except Exception as exc:
            logger.warning("chat_harness: gather_context failed: %s", exc)
            context = {"workspace": workspace}
        
        yield _sse_status("thinking", "Searching codebase for relevant context...")
        semantic_results = None
        if user_query.strip():
            try:
                semantic_results = await semantic_search(workspace, user_query, limit=SEMANTIC_SEARCH_TOP_K)
            except Exception as exc:
                logger.warning("chat_harness: semantic_search failed: %s", exc)
        
        # ── Phase 1: System Prompt & Provider Initialization ─────────────────
        system_prompt = _build_system_prompt(workspace, context, semantic_results)
        
        messages = [ChatMessage(role="system", content=system_prompt)]
        for m in request.messages:
            messages.append(ChatMessage(role=m["role"], content=m["content"]))
        
        chat_request = ChatRequest(
            provider=request.provider,
            model=request.model,
            messages=messages,
            base_url=request.base_url,
            temperature=request.temperature,
            attached_paths=request.attached_paths,
            workspace=workspace,
            api_key_provider=request.api_key_provider,
        )
        
        try:
            provider = await provider_for(chat_request)
        except Exception as exc:
            yield _sse_error(f"Failed to initialize AI model provider: {exc}")
            yield _sse_done(False, f"Provider initialization failed: {exc}")
            return
        
        # ── Phase 2: Autonomous Tool Loop ────────────────────────────────────
        staged_changes: list[FileChange] = []
        plan_steps: list[str] | None = None
        current_step = 0
        consecutive_failures = 0
        consecutive_tool_failures: dict[str, int] = {}
        skipped_items: list[str] = []
        prev_response_prefix: str = ""
        tools_executed_last_turn: int = 0
        intent_retried = False
        truncation_retries = 0
        audit_retried = False
        
        for iteration in range(MAX_AGENT_ITERATIONS):
            status_msg = "Rony Agent is thinking..." if iteration == 0 else f"Rony Agent is working (step {iteration + 1})..."
            yield _sse_status("thinking", status_msg, round=iteration + 1)
            
            effective_messages = _compact_conversation_history(messages)
            
            full_response: list[str] = []
            try:
                try:
                    stream = provider.stream_chat(
                        chat_request.model,
                        effective_messages,
                        chat_request.temperature,
                        tools=OPENAI_HARNESS_TOOLS,
                    )
                except TypeError:
                    stream = provider.stream_chat(
                        chat_request.model,
                        effective_messages,
                        chat_request.temperature,
                    )
                async for token in stream:
                    full_response.append(token)
                    yield _sse_token(token)
            except Exception as exc:
                logger.error("chat_harness: stream_chat error (iteration %d): %s", iteration, exc)
                yield _sse_error(f"AI provider request error: {exc}")
                consecutive_failures += 1
                
                if consecutive_failures >= MAX_RETRY_BEFORE_ESCALATE:
                    yield _sse_status("duo_escalation", "Persistent provider error — escalating to Duo Loop...")
                    async for event in _escalate_to_duo(request, user_query):
                        yield event
                    return
                
                messages.append(ChatMessage(role="assistant", content=f"[Error: AI provider call failed: {exc}]"))
                continue
            
            response_text = "".join(full_response)
            messages.append(ChatMessage(role="assistant", content=response_text))

            # ── Response Repetition Breaker ──────────────────────────────────
            has_tools = _has_tool_calls_extended(response_text)
            curr_prefix = re.sub(r"\s+", " ", response_text[:200]).strip().lower()
            if prev_response_prefix and tools_executed_last_turn == 0 and not has_tools and not _response_is_done(response_text):
                import difflib
                is_exact_prefix = (len(curr_prefix) >= 30 and curr_prefix[:80] == prev_response_prefix[:80])
                similarity = difflib.SequenceMatcher(None, curr_prefix, prev_response_prefix).ratio() if curr_prefix and prev_response_prefix else 0.0
                if is_exact_prefix or similarity > 0.85:
                    logger.warning("chat_harness: detected response repetition loop (similarity=%.2f)", similarity)
                    yield _sse_error("Execution stopped: Agent is repeating near-identical responses without taking action.")
                    yield _sse_done(False, "Stopped: Detected repeated near-identical response loop.")
                    return
            prev_response_prefix = curr_prefix

            # ── Truncation / Timeout Detection & Recovery Guard ────────────────
            if _is_response_truncated(response_text):
                if truncation_retries == 0:
                    truncation_retries += 1
                    yield _sse_status("thinking", "Response was cut off or timed out — instructing agent to chunk the file and shrink chunk size...")
                    messages.append(ChatMessage(
                        role="user",
                        content=(
                            "Your previous response was cut off or timed out. "
                            "Do NOT attempt to output the entire large file in one single tool call or monolithic response. "
                            "Progressive Chunk Shrink Rule: Make the next chunk at most HALF the size of the one that timed out (around ~150–200 lines maximum). "
                            "Use edit_file with original='' for part 1 (HTML skeleton/head/styles), "
                            "then use append_file for subsequent smaller chunks (body sections, interactive JS, footer) until the file is complete. "
                            "Please emit the first smaller chunk with edit_file now."
                        )
                    ))
                    continue
                else:
                    yield _sse_error("output too large for one response — chunking required")
                    yield _sse_done(False, "Task stopped: Output exceeded provider limit or timed out.")
                    return
            
            # ── Plan Parsing & Dynamic Tracking ──────────────────────────────
            if plan_steps is None:
                parsed_plan = _parse_plan(response_text)
                if parsed_plan:
                    plan_steps = parsed_plan
                    current_step = 0
                    yield _sse_plan(plan_steps, current_step)
            
            # ── Escalation Marker ────────────────────────────────────────────
            if _has_escalate_marker(response_text):
                yield _sse_status("duo_escalation", "Rony Agent requested Duo Loop adversarial refinement...")
                async for event in _escalate_to_duo(request, user_query):
                    yield event
                return
            
            # ── Tool Execution ───────────────────────────────────────────────
            has_tools = _has_tool_calls_extended(response_text)
            tool_calls = _parse_tool_calls_extended(response_text) if has_tools else []
            
            # Fallback: extract heuristic tool calls if model expressed action intent without tags
            if not tool_calls and (iteration == 0 or _declares_tool_intent(response_text)):
                heuristic_calls = _extract_heuristic_tool_calls(response_text, user_query)
                if heuristic_calls:
                    tool_calls = heuristic_calls
                    has_tools = True
            
            # False-success guard: check if model declared tool intent without calling tools
            if not tool_calls and not _response_is_done(response_text) and _declares_tool_intent(response_text) and not intent_retried:
                intent_retried = True
                yield _sse_status("thinking", "Instructing Rony Agent to emit the tool call...")
                messages.append(ChatMessage(
                    role="user",
                    content=(
                        "You stated intent to execute tools or run tests/commands, but did not emit the required tool call block. "
                        "To execute tools, you MUST emit a tool block, for example:\n"
                        "[TOOL_CALL: run_command]\n{\"command\": \"pytest tests/test_generation.py\"}\n[/TOOL_CALL]\n"
                        "Please emit the tool call now."
                    )
                ))
                continue
            
            if tool_calls:
                tool_results_list: list[str] = []
                tools_executed_this_turn = 0
                
                for tc in tool_calls:
                    detail = tc.arguments.get("path") or tc.arguments.get("command") or tc.arguments.get("query") or ""
                    try:
                        args_sig = json.dumps(tc.arguments, sort_keys=True)
                    except Exception:
                        args_sig = str(sorted(tc.arguments.items()))
                    tool_sig = f"{tc.name}:{args_sig}"

                    # Repeat-failure breaker: do NOT retry if this exact call failed twice in a row
                    if consecutive_tool_failures.get(tool_sig, 0) >= 2:
                        skip_msg = f"Skipped after 2 failed attempts: {tc.name} ({detail})" if detail else f"Skipped after 2 failed attempts: {tc.name}"
                        yield _sse_status("tool_skipped", skip_msg, tool=tc.name, detail=detail, reason="Failed twice consecutively with identical arguments")
                        skip_desc = f"{tc.name} ({detail})" if detail else tc.name
                        if skip_desc not in skipped_items:
                            skipped_items.append(skip_desc)
                        result = ToolResult(
                            tool_name=tc.name,
                            success=False,
                            output="",
                            error=(
                                f"Action skipped after 2 failed attempts with identical arguments: {tc.name}. "
                                "Do NOT repeat this exact call. Choose a different approach, inspect the file with read_file, or conclude."
                            ),
                        )
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\nERROR: {result.error}\n[/TOOL_RESULT]")
                        continue

                    # Check if command needs approval gate
                    if tc.name == "run_command" and not _is_command_safe(str(tc.arguments.get("command", ""))):
                        cmd_str = str(tc.arguments.get("command", "")).strip()
                        action_id = str(uuid.uuid4())
                        reason = f"Command '{cmd_str.split()[0]}' is not in the safe read-only allowlist"
                        pending = PendingApproval(
                            action_id=action_id,
                            action_type="command",
                            detail=cmd_str,
                            reason=reason,
                        )
                        _pending_approvals[action_id] = pending
                        
                        # Emit approval event immediately to client
                        yield _sse_approval_request(action_id, "command", cmd_str, reason)
                        yield _sse_status("approval_required", f"Approval needed for: {cmd_str}", command=cmd_str)
                        logger.info("chat_harness: awaiting approval for %s (id=%s)", cmd_str, action_id)
                        
                        try:
                            await asyncio.wait_for(pending.event.wait(), timeout=COMMAND_APPROVAL_TIMEOUT_SECONDS)
                            if pending.approved:
                                yield _sse_status("tool", f"Approved: Executing {cmd_str}...", tool="run_command", detail=cmd_str)
                                result = await _execute_command_async(workspace, cmd_str)
                                yield _sse_command_result(cmd_str, result.output or result.error or "", 0 if result.success else 1, result.success)
                            else:
                                result = ToolResult(
                                    tool_name="run_command",
                                    success=False,
                                    output="",
                                    error=f"User rejected permission to execute command: '{cmd_str}'."
                                )
                                yield _sse_command_result(cmd_str, "Command rejected by user.", 1, False)
                        except asyncio.TimeoutError:
                            result = ToolResult(
                                tool_name="run_command",
                                success=False,
                                output="",
                                error=f"Approval timed out after {int(COMMAND_APPROVAL_TIMEOUT_SECONDS)}s for: '{cmd_str}'"
                            )
                            yield _sse_command_result(cmd_str, f"Approval timed out after {int(COMMAND_APPROVAL_TIMEOUT_SECONDS)}s.", 1, False)
                        finally:
                            _pending_approvals.pop(action_id, None)
                    
                    elif tc.name == "read_file":
                        yield _sse_status("tool", f"Reading {detail}...", tool="read_file", detail=detail)
                        result = _handle_read_file(workspace, tc.arguments)
                    elif tc.name == "list_directory":
                        yield _sse_status("tool", f"Listing {detail or '.'}...", tool="list_directory", detail=detail)
                        result = _handle_list_directory(workspace, tc.arguments)
                    elif tc.name == "search_code":
                        yield _sse_status("tool", f"Searching for '{detail}'...", tool="search_code", detail=detail)
                        result = _handle_search_code(workspace, tc.arguments)
                    elif tc.name == "run_test":
                        test_cmd = str(tc.arguments.get("command") or tc.arguments.get("cmd") or tc.arguments.get("path") or detail or "pytest").strip()
                        if not test_cmd.startswith("pytest") and not test_cmd.startswith("python"):
                            test_cmd = f"pytest {test_cmd}"
                        yield _sse_status("tool", f"Running test {test_cmd}...", tool="run_test", detail=test_cmd)
                        result = await _execute_command_async(workspace, test_cmd)
                        yield _sse_command_result(test_cmd, result.output or result.error or "", 0 if result.success else 1, result.success)
                    elif tc.name in ("edit_file", "append_file"):
                        if tc.name == "append_file" or tc.arguments.get("append") is True:
                            valid, err_msg, change = _handle_append_file(workspace, tc.arguments, staged_changes)
                            tool_act = "append_file"
                        else:
                            valid, err_msg, change = _validate_smart_edit(workspace, tc.arguments)
                            if valid and change:
                                existing = next((c for c in staged_changes if c.path == change.path), None)
                                if existing:
                                    existing.original = change.original
                                    existing.updated = change.updated
                                else:
                                    staged_changes.append(change)
                            tool_act = "edit_file"

                        if not valid or not change:
                            result = ToolResult(tool_name=tool_act, success=False, output="", error=err_msg or f"Invalid {tool_act} arguments")
                        else:
                            line_cnt = len(change.updated.splitlines())
                            action_desc = "Appended chunk to" if tool_act == "append_file" else ("Staged new file" if not change.original else "Staged edit for")
                            yield _sse_status("tool", f"{action_desc} {change.path} ({line_cnt} lines)...", tool=tool_act, detail=change.path)
                            yield _sse_command_result(f"{tool_act} {change.path}", f"{action_desc} {change.path} ({line_cnt} lines total)", 0, True)
                            result = ToolResult(
                                tool_name=tool_act,
                                success=True,
                                output=f"✓ {action_desc} '{change.path}'. Total staged lines: {line_cnt}. If more chunks remain, call append_file; otherwise summarize your work and output [DONE]."
                            )
                    elif tc.name == "semantic_search":
                        yield _sse_status("tool", f"Semantic search for '{detail}'...", tool="semantic_search", detail=detail)
                        query = tc.arguments.get("query", "").strip()
                        if query:
                            try:
                                matches = await semantic_search(workspace, query, limit=SEMANTIC_SEARCH_TOP_K)
                                if matches:
                                    match_lines = [
                                        f"  - `{m.get('relative_path', m.get('path', '?'))}` (relevance: {m.get('score', 0):.3f})"
                                        for m in matches
                                    ]
                                    result = ToolResult(
                                        tool_name="semantic_search",
                                        success=True,
                                        output=f"=== SEMANTIC MATCHES FOR '{query}' ===\n" + "\n".join(match_lines)
                                    )
                                else:
                                    result = ToolResult(
                                        tool_name="semantic_search",
                                        success=True,
                                        output=f"No semantic matches found for '{query}'."
                                    )
                            except Exception as exc:
                                result = ToolResult(tool_name="semantic_search", success=False, output="", error=f"Semantic search error: {exc}")
                        else:
                            result = ToolResult(tool_name="semantic_search", success=False, output="", error="Missing query")
                    elif tc.name == "run_command":
                        cmd_str = str(tc.arguments.get("command", "")).strip()
                        yield _sse_status("tool", f"Executing {cmd_str}...", tool="run_command", detail=cmd_str)
                        result = await _execute_command_async(workspace, cmd_str)
                        yield _sse_command_result(cmd_str, result.output or result.error or "", 0 if result.success else 1, result.success)
                    else:
                        result = ToolResult(tool_name=tc.name, success=False, output="", error=f"Unknown tool: {tc.name}")
                    
                    total_tools_executed += 1
                    tools_executed_this_turn += 1
                    intent_retried = False

                    # Track consecutive failures by tool signature
                    if not result.success:
                        consecutive_tool_failures[tool_sig] = consecutive_tool_failures.get(tool_sig, 0) + 1
                        if consecutive_tool_failures[tool_sig] >= 2:
                            skip_msg = f"Skipped after 2 failed attempts: {tc.name} ({detail})" if detail else f"Skipped after 2 failed attempts: {tc.name}"
                            yield _sse_status("tool_skipped", skip_msg, tool=tc.name, detail=detail, reason=result.error or "Failed twice consecutively")
                            skip_desc = f"{tc.name} ({detail})" if detail else tc.name
                            if skip_desc not in skipped_items:
                                skipped_items.append(skip_desc)
                    else:
                        consecutive_tool_failures.pop(tool_sig, None)

                    if result.success:
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\n{result.output}\n[/TOOL_RESULT]")
                    else:
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\nERROR: {result.error}\n[/TOOL_RESULT]")
                
                tools_executed_last_turn = tools_executed_this_turn
                
                tool_results_text = "\n\n".join(tool_results_list)
                
                # Advance step progress if plan is active
                if plan_steps and current_step < len(plan_steps):
                    yield _sse_status(
                        "step_complete",
                        f"Completed step {current_step + 1}/{len(plan_steps)}",
                        step=current_step,
                        total=len(plan_steps),
                    )
                    current_step = min(current_step + 1, len(plan_steps) - 1)
                    yield _sse_plan(plan_steps, current_step)
                
                # Check for test failures
                if "FAILED" in tool_results_text and any(tc.name in ("run_test", "run_command") for tc in tool_calls):
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_RETRY_BEFORE_ESCALATE:
                        yield _sse_status("duo_escalation", "Repeated test failures — escalating to Duo Loop...")
                        async for event in _escalate_to_duo(request, user_query):
                            yield event
                        return
                else:
                    consecutive_failures = 0
                
                # If response already included [DONE] marker along with visible prose explanation
                clean_prose = _clean_response_text(response_text)
                if _response_is_done(response_text) and clean_prose:
                    if _should_audit_staged_changes(staged_changes, user_query) and not audit_retried:
                        audit_reports = [audit_generated_artifact(c.updated, c.path) for c in staged_changes]
                        failed_reports = [r for r in audit_reports if r.has_errors]
                        if failed_reports:
                            audit_retried = True
                            summary_text = "\n\n".join(r.format_summary() for r in failed_reports)
                            yield _sse_status("thinking", "Post-generation structural audit detected issues — instructing agent to fix...")
                            messages.append(ChatMessage(
                                role="user",
                                content=(
                                    f"Post-generation structural quality gate detected issues in staged file(s):\n\n"
                                    f"{summary_text}\n\n"
                                    "Please fix these structural issues using `edit_file` before completing the task. "
                                    "Ensure all tags are closed, all anchor href targets exist, and no mobile antipatterns remain."
                                )
                            ))
                            continue

                    if _should_audit_staged_changes(staged_changes, user_query):
                        for c in staged_changes:
                            rep = audit_generated_artifact(c.updated, c.path)
                            yield _sse_status(
                                "audit",
                                f"Structural audit passed for {c.path} ({rep.non_empty_non_comment_lines} non-empty lines)",
                                path=c.path,
                                is_clean=rep.is_clean,
                                non_empty_lines=rep.non_empty_non_comment_lines,
                            )

                    async for event in _finalize_staged_changes(staged_changes, workspace):
                        yield event
                    duration_ms = (time.time() - start_time) * 1000.0
                    yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms)
                    yield _sse_done(True, "All tasks completed and verified successfully.")
                    return

                # Inject tool observation back into conversation to generate natural language explanation
                messages.append(ChatMessage(
                    role="user",
                    content=(
                        f"Tool observation results:\n\n{tool_results_text}\n\n"
                        "Inspect the results above and directly answer the user's question with your findings in plain language. If all tasks or checks are complete, summarize the outcome and output [DONE]."
                    )
                ))
                continue
            
            # ── Done Marker Check ────────────────────────────────────────────
            if _response_is_done(response_text):
                if _should_audit_staged_changes(staged_changes, user_query) and not audit_retried:
                    audit_reports = [audit_generated_artifact(c.updated, c.path) for c in staged_changes]
                    failed_reports = [r for r in audit_reports if r.has_errors]
                    if failed_reports:
                        audit_retried = True
                        summary_text = "\n\n".join(r.format_summary() for r in failed_reports)
                        yield _sse_status("thinking", "Post-generation structural audit detected issues — instructing agent to fix...")
                        messages.append(ChatMessage(
                            role="user",
                            content=(
                                f"Post-generation structural quality gate detected issues in staged file(s):\n\n"
                                f"{summary_text}\n\n"
                                "Please fix these structural issues using `edit_file` before completing the task. "
                                "Ensure all tags are closed, all anchor href targets exist, and no mobile antipatterns remain."
                            )
                        ))
                        continue

                clean_prose = _clean_response_text(response_text)
                if not clean_prose and total_tools_executed > 0:
                    messages.append(ChatMessage(
                        role="user",
                        content="Answer the user's question directly in plain language using the tool observation results above."
                    ))
                    try:
                        stream = provider.stream_chat(
                            chat_request.model,
                            _compact_conversation_history(messages),
                            chat_request.temperature,
                        )
                        async for token in stream:
                            yield _sse_token(token)
                    except Exception:
                        pass

                if _should_audit_staged_changes(staged_changes, user_query):
                    for c in staged_changes:
                        rep = audit_generated_artifact(c.updated, c.path)
                        yield _sse_status(
                            "audit",
                            f"Structural audit passed for {c.path} ({rep.non_empty_non_comment_lines} non-empty lines)",
                            path=c.path,
                            is_clean=rep.is_clean,
                            non_empty_lines=rep.non_empty_non_comment_lines,
                        )

                async for event in _finalize_staged_changes(staged_changes, workspace):
                    yield event
                
                duration_ms = (time.time() - start_time) * 1000.0
                yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms)
                yield _sse_done(True, "All tasks completed and verified successfully.")
                return
            
            if not has_tools:
                tools_executed_last_turn = 0

                # Per-turn false-success guard: only block if 0 tools were executed and nothing was staged
                if total_tools_executed == 0 and not staged_changes and _declares_tool_intent(response_text):
                    if intent_retried:
                        yield _sse_error("Rony Agent stated intent to execute tools but did not emit tool calls after retry.")
                        yield _sse_done(False, "Execution stopped: Agent failed to emit required tool calls.")
                        return
                    else:
                        intent_retried = True
                        yield _sse_status("thinking", "Instructing Rony Agent to emit the tool call...")
                        messages.append(ChatMessage(
                            role="user",
                            content=(
                                "You stated intent to execute tools or run tests/commands, but did not emit the required tool call block. "
                                "To execute tools, you MUST emit a tool block, for example:\n"
                                "[TOOL_CALL: run_command]\n{\"command\": \"pytest tests/test_generation.py\"}\n[/TOOL_CALL]\n"
                                "Please emit the tool call now."
                            )
                        ))
                        continue

                clean_prose = _clean_response_text(response_text)
                # Honest completion check: if user asked for file creation/edits or commands, but 0 tools executed and nothing staged
                user_action_keywords = ["create", "write", "generate", "make", "add", "edit", "build", "implement", "run", "fix", "test", "portfolio", "html", "code", "file"]
                if total_tools_executed == 0 and not staged_changes and any(k in user_query.lower() for k in user_action_keywords):
                    yield _sse_error("Nothing was generated: no file-write or tool execution steps were performed.")
                    yield _sse_done(False, "Task ended without generating files or executing tools.")
                    return

                if _should_audit_staged_changes(staged_changes, user_query) and not audit_retried:
                    audit_reports = [audit_generated_artifact(c.updated, c.path) for c in staged_changes]
                    failed_reports = [r for r in audit_reports if r.has_errors]
                    if failed_reports:
                        audit_retried = True
                        summary_text = "\n\n".join(r.format_summary() for r in failed_reports)
                        yield _sse_status("thinking", "Post-generation structural audit detected issues — instructing agent to fix...")
                        messages.append(ChatMessage(
                            role="user",
                            content=(
                                f"Post-generation structural quality gate detected issues in staged file(s):\n\n"
                                f"{summary_text}\n\n"
                                "Please fix these structural issues using `edit_file` before completing the task. "
                                "Ensure all tags are closed, all anchor href targets exist, and no mobile antipatterns remain."
                            )
                        ))
                        continue

                if not clean_prose and total_tools_executed > 0:
                    messages.append(ChatMessage(
                        role="user",
                        content="Answer the user's question directly in plain language using the tool observation results above."
                    ))
                    try:
                        stream = provider.stream_chat(
                            chat_request.model,
                            _compact_conversation_history(messages),
                            chat_request.temperature,
                        )
                        async for token in stream:
                            yield _sse_token(token)
                    except Exception:
                        pass

                if _should_audit_staged_changes(staged_changes, user_query):
                    for c in staged_changes:
                        rep = audit_generated_artifact(c.updated, c.path)
                        yield _sse_status(
                            "audit",
                            f"Structural audit passed for {c.path} ({rep.non_empty_non_comment_lines} non-empty lines)",
                            path=c.path,
                            is_clean=rep.is_clean,
                            non_empty_lines=rep.non_empty_non_comment_lines,
                        )

                async for event in _finalize_staged_changes(staged_changes, workspace):
                    yield event
                
                duration_ms = (time.time() - start_time) * 1000.0
                yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms)
                yield _sse_done(True)
                return
        
        # Max iterations reached — generate honest partial progress report
        async for event in _finalize_staged_changes(staged_changes, workspace):
            yield event
        duration_ms = (time.time() - start_time) * 1000.0
        yield _sse_metrics(MAX_AGENT_ITERATIONS, total_tools_executed, duration_ms)

        report_lines = [
            f"Rony Agent reached iteration limit ({MAX_AGENT_ITERATIONS}). Partial progress report:",
            "Completed Items:",
        ]
        completed_list: list[str] = []
        if staged_changes:
            for c in staged_changes:
                c_desc = f"Staged changes for '{c.path}' ({len(c.updated.splitlines())} lines)"
                report_lines.append(f"  ✓ {c_desc}")
                completed_list.append(c_desc)
        elif total_tools_executed > 0:
            c_desc = f"Executed {total_tools_executed} tool action(s)"
            report_lines.append(f"  ✓ {c_desc}")
            completed_list.append(c_desc)
        else:
            report_lines.append("  - No files were modified.")

        report_lines.append("Skipped / Incomplete Items:")
        skipped_list: list[str] = list(skipped_items)
        if plan_steps and current_step < len(plan_steps):
            for step in plan_steps[current_step:]:
                skipped_list.append(f"Incomplete step: {step}")
        if skipped_list:
            for item in skipped_list:
                report_lines.append(f"  ⚠️ {item}")
        else:
            report_lines.append("  - Generation cut off by iteration limit before full verification.")
            skipped_list.append("Full verification incomplete before iteration limit")

        partial_summary = "\n".join(report_lines)
        yield _sse_status("partial_report", partial_summary)
        yield _sse_done(
            False,
            partial_summary,
            completed_items=completed_list,
            skipped_items=skipped_list,
        )

    except Exception as top_exc:
        logger.exception("chat_harness: unhandled error in run_chat_agent: %s", top_exc)
        yield _sse_error(f"Agent execution error: {top_exc}")
        yield _sse_done(False, f"Agent execution stopped: {top_exc}")


# ── Proposal Finalization ────────────────────────────────────────────────────

async def _finalize_staged_changes(
    staged_changes: list[FileChange],
    workspace: str,
) -> AsyncIterator[str]:
    """Convert staged file changes into a consolidated reviewable edit proposal and request inline approval."""
    if not staged_changes:
        return
    
    try:
        proposal_payload = EditProposalRequest(
            workspace=workspace,
            summary=f"Rony Agent: {len(staged_changes)} file(s) created/modified",
            changes=staged_changes,
        )
        proposal = await create_proposal(proposal_payload)
        proposal_id = proposal.id if hasattr(proposal, "id") else str(proposal)
        
        for change in staged_changes:
            path_str = change.path if hasattr(change, "path") else str(change)
            yield _sse_proposal(proposal_id, path_str, summary=f"Changes for {path_str}", changes_count=len(staged_changes))
        
        summary_paths = ", ".join(c.path for c in staged_changes)
        diff_summary = "\n".join(_generate_diff_summary(c) for c in staged_changes)
        action_id = str(uuid.uuid4())
        reason = f"Rony Agent wants to create/modify {summary_paths}"

        pending = PendingApproval(
            action_id=action_id,
            action_type="edit",
            detail=summary_paths,
            reason=reason,
            proposal_id=proposal_id,
            path=summary_paths,
            diff_summary=diff_summary,
        )
        _pending_approvals[action_id] = pending

        # Emit proposal and approval request event immediately
        yield _sse_approval_request(
            action_id=action_id,
            action_type="edit",
            detail=summary_paths,
            reason=reason,
            proposal_id=proposal_id,
            path=summary_paths,
            diff_summary=diff_summary,
        )
        yield _sse_status(
            "approval_required",
            f"Approval needed to apply changes to: {summary_paths}",
            detail=summary_paths,
            proposal_id=proposal_id,
        )
        logger.info("chat_harness: awaiting consolidated edit approval for %s (id=%s, prop=%s)", summary_paths, action_id, proposal_id)

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=EDIT_APPROVAL_TIMEOUT_SECONDS)
            if pending.approved:
                from .service import apply_proposal
                await apply_proposal(proposal_id)
                yield _sse_status("tool", f"Approved: Applied changes to {summary_paths}", tool="edit_file", detail=summary_paths)
                yield _sse_command_result(f"edit {summary_paths}", f"Successfully applied changes to {summary_paths} (Proposal: {proposal_id})", 0, True)
            else:
                from .service import reject_proposal
                try:
                    await reject_proposal(proposal_id)
                except Exception:
                    pass
                yield _sse_command_result(f"edit {summary_paths}", f"User rejected changes to {summary_paths}.", 1, False)
        except asyncio.TimeoutError:
            yield _sse_command_result(f"edit {summary_paths}", f"Edit approval timed out after {int(EDIT_APPROVAL_TIMEOUT_SECONDS)}s.", 1, False)
        finally:
            _pending_approvals.pop(action_id, None)

    except Exception as exc:
        logger.error("chat_harness: failed to create edit proposal: %s", exc)
        yield _sse_error(f"Failed to create edit proposal: {exc}")


# ── Duo Loop Escalation ──────────────────────────────────────────────────────

async def _escalate_to_duo(
    request: ChatAgentRequest,
    task_description: str,
) -> AsyncIterator[str]:
    """Escalate a difficult task to the Duo Generator/Critic loop."""
    from ..duo.service import start_session as duo_start_session, get_session as duo_get_session
    from ..duo.schemas import DuoSessionRequest, ModelConfig
    
    yield _sse_status("duo_escalation", "Starting Duo Loop adversarial refinement...")
    
    try:
        duo_req = DuoSessionRequest(
            workspace=request.workspace,
            task_description=task_description,
            generator=ModelConfig(
                provider=request.provider or "auto",
                model=request.model or "",
                base_url=request.base_url,
                api_key_provider=request.api_key_provider,
            ),
            critic=ModelConfig(
                provider=request.provider or "auto",
                model=request.model or "",
                base_url=request.base_url,
                api_key_provider=request.api_key_provider,
            ),
            max_rounds=5,
            internal=True,
        )
        
        session = await duo_start_session(duo_req)
        session_id = session.id
        
        yield _sse_status("duo_escalation", f"Duo Loop active (session {session_id[:8]})...")
        
        for _ in range(60):
            await asyncio.sleep(5)
            session = await duo_get_session(session_id)
            
            if session.status in ("approved", "unresolved", "error", "cancelled"):
                break
            
            round_num = session.current_round
            yield _sse_status("duo_escalation", f"Duo Loop: Round {round_num}/{session.max_rounds} (Critic reviewing)...")
        
        if session.status == "approved" and session.final_proposal_id:
            yield _sse_proposal(session.final_proposal_id, "Duo Loop result", summary="Duo Loop approved changes")
            yield _sse_status("duo_escalation", "Duo Loop approved — proposal ready in Diff Inspector")
            yield _sse_done(True, "Duo Loop completed with verified approval. Review changes in Diff Inspector.")
        elif session.status == "unresolved":
            last_round = session.rounds[-1] if session.rounds else None
            if last_round and last_round.proposal_id:
                yield _sse_proposal(last_round.proposal_id, "Duo Loop (best effort)", summary="Best effort proposal")
            yield _sse_done(False, "Duo Loop reached round limit. Best-effort proposal available.")
        else:
            yield _sse_done(False, f"Duo Loop finished with status: {session.status}")
    
    except Exception as exc:
        logger.error("chat_harness: Duo Loop escalation failed: %s", exc)
        yield _sse_error(f"Duo Loop escalation error: {exc}")
        yield _sse_done(False, f"Escalation error: {exc}")
