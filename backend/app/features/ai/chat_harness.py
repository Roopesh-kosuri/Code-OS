"""
chat_harness.py — Adaptive autonomous coding agent loop for Rony Agent in CODE OS chat.

Provides:
- 3-Tier Adaptive Effort Routing (Tier 0 Fast Answer, Tier 1 Quick Task, Tier 2 Deep Task)
- Fast Time-To-First-Token (TTFT < 2s on Tier 0) with zero-gate streaming
- Budgeted Symbol-Aware RAG with snippet windowing and recency bias
- Dependency-Aware Plan DAG with visible dynamic re-planning on step failure
- Persistent Project Memory via RONY.md (loaded on startup, editable via memory_write tool)
- Interactive Clarification via ask_user card
- Post-apply read-back disk verification and Tier 2 self-critique pass
- Strict fail-closed command allowlist with path-containment validation
- Anti-looping breakers: repeat-failure breaker, response-repetition breaker, progressive shrink
- Structural quality gates and honest artifact audit reporting
"""
from __future__ import annotations

import asyncio
import difflib
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
from typing import Any, Literal

from ...core.paths import ensure_within_workspace, normalize_workspace
from ..settings.service import get_api_key
from .schemas import ChatMessage, ChatRequest, EditProposalRequest, FileChange
from .service import provider_for, create_proposal, PROPOSAL_RE
from .context_service import gather_context
from ..search.semantic_service import semantic_search
from .artifact_auditor import audit_generated_artifact, ArtifactAuditReport

# Reuse tool implementations from agent_tools (READ-ONLY import)
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
MAX_QUICK_TASK_ITERATIONS = 4
MAX_TOOL_CALLS_PER_ITERATION = 5
MAX_RETRY_BEFORE_ESCALATE = 3
SEMANTIC_SEARCH_TOP_K = 10
COMMAND_APPROVAL_TIMEOUT_SECONDS = 60.0
EDIT_APPROVAL_TIMEOUT_SECONDS = 300.0
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


# ── File Read Cache (Read Dedup) ─────────────────────────────────────────────

_file_read_cache: dict[str, tuple[float, str]] = {}


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


# ── Project Memory (RONY.md) ─────────────────────────────────────────────────

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
        existing = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "# Project Memory (RONY.md)\n\n"
        bullet = f"- {fact_str}\n"
        if bullet not in existing:
            p.write_text(existing + bullet, encoding="utf-8")
        return True, f"Saved to project memory: '{fact_str}'"
    except Exception as exc:
        return False, f"Failed to update RONY.md: {exc}"


# ── Pending Approvals & Interactive User Responses ───────────────────────────

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


@dataclass
class PendingUserResponse:
    """A clarifying question awaiting user choice (ask_user)."""
    action_id: str
    question: str
    options: list[str]
    event: asyncio.Event = field(default_factory=asyncio.Event)
    selected_option: str = ""
    created_at: float = field(default_factory=time.time)


_pending_approvals: dict[str, PendingApproval] = {}
_pending_user_responses: dict[str, PendingUserResponse] = {}


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


def respond_to_user_question(action_id: str, answer: str) -> bool:
    """Submit user's answer to an ask_user prompt."""
    pending = _pending_user_responses.get(action_id)
    if not pending:
        return False
    pending.selected_option = answer
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


def _sse_tier_routing(tier: int, label: str, reason: str = "") -> str:
    return _sse_event("tier_routing", {
        "tier": tier,
        "label": label,
        "reason": reason,
    })


def _sse_ask_user(action_id: str, question: str, options: list[str]) -> str:
    return _sse_event("ask_user", {
        "action_id": action_id,
        "question": question,
        "options": options,
    })


def _sse_memory_updated(fact: str) -> str:
    return _sse_event("memory_updated", {
        "fact": fact,
    })


def _sse_plan(steps: list[str | dict | DAGPlanStep], current: int = 0, **kwargs) -> str:
    formatted_steps: list[dict] = []
    for s in steps:
        if isinstance(s, DAGPlanStep):
            formatted_steps.append(s.to_dict())
        elif isinstance(s, dict):
            formatted_steps.append(s)
        else:
            step_idx = len(formatted_steps)
            status_val = "done" if step_idx < current else ("running" if step_idx == current else "pending")
            formatted_steps.append({
                "id": f"step_{step_idx + 1}",
                "title": str(s),
                "status": status_val,
                "depends_on": [f"step_{step_idx}"] if step_idx > 0 else [],
            })
    payload = {"steps": formatted_steps, "current": current}
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
    return _sse_event("command_result", {
        "command": command,
        "output": output,
        "exit_code": exit_code,
        "success": success,
    })


def _sse_metrics(iterations: int, tools_executed: int, duration_ms: float, tier: int = 0) -> str:
    return _sse_event("metrics", {
        "iterations": iterations,
        "tools_executed": tools_executed,
        "duration_ms": duration_ms,
        "tier": tier,
    })


def _sse_done(success: bool, message: str = "", **kwargs) -> str:
    payload = {"success": success, "message": message}
    payload.update(kwargs)
    return _sse_event("done", payload)


def _sse_error(message: str, **kwargs) -> str:
    payload = {"message": message}
    payload.update(kwargs)
    return _sse_event("error", payload)


# ── Adaptive Effort Routing & Classification ─────────────────────────────────

def _is_deep_query(q_lower: str, attached_paths: list[str] | None) -> bool:
    deep_verbs = (
        "build", "generate", "create portfolio", "create website", "create app",
        "create a portfolio", "create a full", "create the full", "refactor",
        "multi-file", "architecture", "entire codebase", "all files", "across the project",
        "full system", "redesign", "port to", "migrate", "rewrite", "debug and fix all",
        "1000+", "portfolio", "html site", "web app", "create hello.html", "generate hello.html",
        "analyze files in workspace", "analyze all files",
    )
    if any(dv in q_lower for dv in deep_verbs):
        return True
    if attached_paths and len(attached_paths) > 2:
        return True
    return False


def _is_quick_task_query(q_lower: str, attached_paths: list[str] | None) -> bool:
    question_starters = (
        "what does", "how does", "what is", "how do i", "explain", "why is",
        "where is", "can you explain", "tell me about", "describe", "summary of",
        "how to", "what are",
    )
    is_pure_question = any(q_lower.startswith(qs) for qs in question_starters)
    
    task_verbs = (
        "add", "edit", "fix", "modify", "update", "change", "insert", "delete",
        "remove", "replace", "run pytest", "run test", "execute", "rename",
        "create file", "write a function", "implement", "set", "append",
        "analyze", "inspect", "check", "scan", "audit", "search", "find",
    )
    has_task_verb = any(tv in q_lower for tv in task_verbs)
    
    if is_pure_question and not has_task_verb:
        return False

    if has_task_verb or (attached_paths and len(attached_paths) > 0) or "files in workspace" in q_lower:
        return True

    return False


def _classify_task_effort(
    user_query: str,
    attached_paths: list[str] | None = None,
    is_agent_mode: bool = False,
) -> tuple[int, str]:
    """Classify user request into Tier 0 (ANSWER), Tier 1 (QUICK TASK), or Tier 2 (DEEP TASK).

    Tier 0 ANSWER (questions, explanations, small snippets):
      - Immediate streaming (<2s TTFT), skips RAG & plan gates, 1 iteration.
    Tier 1 QUICK TASK (single-file edit, one command):
      - Lean active-file context, no plan emission, max 4 loop iterations.
    Tier 2 DEEP TASK (multi-file, generation, debug->fix loops):
      - Full machinery: [PLAN] DAG, budgeted RAG snippets, chunked generation, up to 12 iterations.
    """
    q_lower = user_query.strip().lower()
    if not q_lower:
        return 0, "Fast Answer"

    # Agent mode toggle acts as a manual override: forces at least Tier 1
    if is_agent_mode:
        tier = 2 if _is_deep_query(q_lower, attached_paths) else 1
        return tier, "Deep think" if tier == 2 else "Quick Task"

    # Tier 2 keywords (multi-file, build, refactor, generate full, test all, architecture)
    if _is_deep_query(q_lower, attached_paths):
        return 2, "Deep think"

    # Tier 1 keywords (action verbs targeting files, single command, edit, fix, change)
    if _is_quick_task_query(q_lower, attached_paths):
        return 1, "Quick Task"

    # Default for questions/explanations: Tier 0 Fast Answer
    return 0, "Fast Answer"


# ── Dependency-Aware DAG Plan Engine ──────────────────────────────────────────

_PLAN_RE = re.compile(
    r"\[PLAN\]\s*\n?(.*?)\n?\[/PLAN\]",
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class DAGPlanStep:
    id: str
    title: str
    status: Literal["pending", "running", "done", "failed", "blocked"] = "pending"
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "depends_on": self.depends_on,
        }


def _parse_plan(response: str) -> list[str] | None:
    """Extract ordered step list from [PLAN] ... [/PLAN] block (backward-compat)."""
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


def _parse_plan_dag(response: str) -> list[DAGPlanStep] | None:
    """Extract ordered DAG plan steps with dependency tracking from [PLAN] block."""
    match = _PLAN_RE.search(response)
    if not match:
        return None

    raw_steps = match.group(1).strip().splitlines()
    steps: list[DAGPlanStep] = []
    for idx, line in enumerate(raw_steps):
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^[\d]+[.)]\s*", "", line)
        cleaned = re.sub(r"^[-*]\s*", "", cleaned).strip()
        if not cleaned:
            continue
        step_id = f"step_{idx + 1}"
        deps: list[str] = []
        dep_match = re.search(r"\((?:depends on|after)\s*([\d,\s]+)\)", cleaned, re.IGNORECASE)
        if dep_match:
            raw_nums = re.findall(r"\d+", dep_match.group(1))
            deps = [f"step_{n}" for n in raw_nums]
            cleaned = re.sub(r"\((?:depends on|after)\s*[\d,\s]+\)", "", cleaned, flags=re.IGNORECASE).strip()
        elif idx > 0:
            deps = [f"step_{idx}"]

        steps.append(DAGPlanStep(id=step_id, title=cleaned, status="pending", depends_on=deps))

    return steps if steps else None


def _replan_on_failure(steps: list[DAGPlanStep], failed_idx: int, error_detail: str) -> list[DAGPlanStep]:
    """Insert a visible fix step and mark dependent steps as blocked upon failure."""
    if failed_idx < 0 or failed_idx >= len(steps):
        return steps

    failed_step = steps[failed_idx]
    failed_step.status = "failed"
    failed_id = failed_step.id

    for s in steps:
        if failed_id in s.depends_on and s.status == "pending":
            s.status = "blocked"

    fix_id = f"fix_{failed_id}_{int(time.time())}"
    fix_title = f"Repair failure in {failed_step.title}: {error_detail[:50]}"
    fix_step = DAGPlanStep(id=fix_id, title=fix_title, status="running", depends_on=[failed_id])

    return list(steps[:failed_idx + 1]) + [fix_step] + list(steps[failed_idx + 1:])


def _has_escalate_marker(response: str) -> bool:
    return "[ESCALATE]" in response


def _response_is_done(response: str) -> bool:
    return "[DONE]" in response


def _declares_tool_intent(text: str) -> bool:
    """Detect if response declared intent to execute tools without calling them."""
    if "[DONE]" in text:
        return False
    lower = text.lower()
    
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
    ]
    return any(p in lower for p in explicit_intent_phrases)


# ── Smart Edit Pre-Validation with Mismatch Diagnostics ─────────────────────

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
    if any(c.original == "" for c in staged_changes):
        return True
    q_lower = user_query.lower()
    if any(term in q_lower for term in ("build", "create", "generate", "portfolio", "html", "website", "app")):
        return True
    return False


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


# ── Terminal Command Execution ───────────────────────────────────────────────

async def _execute_command_async(workspace: str, command: str) -> ToolResult:
    """Execute a shell command asynchronously sandboxed to workspace root."""
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
}

_EXTENDED_TOOL_RE = re.compile(
    r"\[TOOL_CALL:\s*(?P<name>[a-z_]+)\s*\]\s*(?P<body>.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL | re.IGNORECASE,
)

_CODEBLOCK_TOOL_RE = re.compile(
    r"```(?:tool_call|json)\s*\n(\{\s*\"(?:tool|name)\"\s*:\s*\"[a-z_]+\"[\s\S]*?\})\s*```",
    re.IGNORECASE,
)


def _parse_tool_calls_extended(response: str) -> list[ToolCall]:
    """Extract tool calls from LLM response across multiple formatting styles."""
    calls: list[ToolCall] = []
    
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
                args = {"path": body.strip().strip("\"'"), "command": body.strip(), "content": body.strip(), "fact": body.strip()}
        except json.JSONDecodeError:
            args = {"path": body.strip().strip("\"'"), "command": body.strip(), "content": body.strip(), "fact": body.strip()}
        
        calls.append(ToolCall(name=name, arguments=args, raw_text=raw))
    
    if calls:
        return calls[:MAX_TOOL_CALLS_PER_ITERATION]
    
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
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "Save a persistent project convention, user preference, or architectural rule to RONY.md.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The rule, convention, or preference to remember"},
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a clarifying question with quick-reply options when requirements are ambiguous.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Clarifying question"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "2-4 quick reply choices"},
                },
                "required": ["question", "options"],
            },
        },
    },
]


# ── Budgeted Symbol-Aware RAG Context Gathering ──────────────────────────────

async def _gather_budgeted_rag_context(
    workspace: str,
    query: str,
    recent_files: list[str] | None = None,
    token_budget: int = 1200,
) -> tuple[list[dict], str]:
    """Gather symbol-aware code definitions and snippet windows under a fixed token budget."""
    if not query.strip() or not workspace:
        return [], ""

    grounding_blocks: list[str] = []
    total_chars = 0
    max_chars = token_budget * 4

    # 1. Symbol Search: extract identifiers (camelCase, PascalCase, snake_case)
    symbols = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", query))
    stop_words = {"what", "does", "where", "used", "code", "file", "make", "this", "that", "with", "from", "into", "have", "been", "show", "help", "find"}
    candidate_symbols = [s for s in symbols if s.lower() not in stop_words][:4]

    symbol_hits: list[str] = []
    for sym in candidate_symbols:
        try:
            def_matches = _handle_search_code(workspace, {"query": sym})
            if def_matches.success and def_matches.output:
                lines = [l for l in def_matches.output.splitlines() if not l.startswith("===")][:5]
                if lines:
                    symbol_hits.append(f"### Symbol '{sym}' locations:\n" + "\n".join(lines))
        except Exception:
            pass

    if symbol_hits:
        sym_text = "\n\n".join(symbol_hits)
        grounding_blocks.append(f"## Symbol Definition Locations:\n{sym_text}")
        total_chars += len(sym_text)

    # 2. Semantic Search for Top matches
    semantic_results: list[dict] = []
    try:
        raw_semantic = await semantic_search(workspace, query, limit=SEMANTIC_SEARCH_TOP_K)
        if raw_semantic:
            semantic_results = raw_semantic
    except Exception as exc:
        logger.warning("chat_harness: semantic_search in budgeted RAG failed: %s", exc)

    if recent_files:
        for rf in recent_files:
            match = next((r for r in semantic_results if r.get("path") == rf or r.get("relative_path") == rf), None)
            if match:
                match["score"] = match.get("score", 0.5) + 0.5
        semantic_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    top_matches = semantic_results[:3]
    for m in top_matches:
        if total_chars >= max_chars:
            break
        rel_p = m.get("relative_path", m.get("path", ""))
        if not rel_p:
            continue
        try:
            full_path = ensure_within_workspace(workspace, rel_p)
            if full_path.is_file():
                content = _read_file_cached(full_path)
                lines = content.splitlines()
                window = lines[:100]
                snippet = "\n".join(window)
                block = f"### File `{rel_p}` (relevance: {m.get('score', 0):.2f}, lines 1-{len(window)}):\n```\n{snippet}\n```"
                if total_chars + len(block) <= max_chars:
                    grounding_blocks.append(block)
                    total_chars += len(block)
                else:
                    remaining = max_chars - total_chars
                    if remaining > 200:
                        grounding_blocks.append(block[:remaining] + "\n... [Snippet truncated for token budget]")
                    break
        except Exception:
            pass

    rag_summary = "\n\n".join(grounding_blocks)
    return semantic_results, rag_summary


# ── System Prompts ───────────────────────────────────────────────────────────

_LEAN_CHAT_SYSTEM_PROMPT = """You are Rony Agent — a concise, high-speed coding assistant in CODE OS.
Answer the user's question directly, clearly, and accurately in plain natural language.
Use markdown formatting and code snippets where helpful.
Output [DONE] when finished.
"""

_QUICK_TASK_SYSTEM_PROMPT = """You are Rony Agent — a fast, surgical coding agent in CODE OS.
You have access to sandboxed tools to read files, stage edits, and run commands.

Rules:
1. **Surgical Precision**: Make minimal targeted edits matching existing style. Never rewrite whole files.
2. **Verify with Evidence**: Run tests or commands to verify changes before completing.
3. **Ambiguity**: If requirements are ambiguous, call `ask_user` with 2-4 quick reply options.
4. **Memory**: Save project preferences to RONY.md using `memory_write`.
Output [DONE] when finished.
"""

_DEEP_TASK_SYSTEM_PROMPT = """You are Rony Agent — a high-performance autonomous coding partner in CODE OS.
You have direct, sandboxed access to the workspace through tools.

## Operating Principles
1. **Understand First**: Inspect relevant files with `read_file`, `list_directory`, `search_code`, or `semantic_search` before editing.
2. **Decompose Multi-Step Work**: For complex tasks, define a dependency-aware plan FIRST:
   [PLAN]
   1. Read existing implementation in module X
   2. Run pytest to check baseline
   3. Stage targeted edit to module X (depends on 2)
   4. Run test suite to verify (depends on 3)
   [/PLAN]
3. **Execute Tools Directly**: When you need to read files, run tests, or execute commands, emit the tool call block directly. NEVER say "We need to run tests. Use run_test tool." YOU ARE THE AGENT — YOU MUST CALL THE TOOL YOURSELF.
4. **Targeted Precision**: When using `edit_file`, provide the exact `original` snippet to replace. Keep edits minimal and maintain existing architecture and style.
5. **Verify with Evidence**: Run tests or commands to verify results. If tests fail, read the assertion traceback and repair the code based on real evidence.
6. **Chunked Large File Generation**: For large files exceeding ~300–400 lines (or 1000+ lines), you MUST split generation across multiple tool calls: call `edit_file` (with original="") for the first chunk (skeleton/head/styles), then call `append_file` for subsequent chunks (body sections, interactive JS, footers) until complete.
7. **Permanent Generation Quality Standards**:
   - No Padding / Filler comments or placeholders.
   - Professional Iconography (SVG icons, no emojis as UI icons).
   - Mobile transform-based parallax (no `background-attachment: fixed`).
   - Progressive Enhancement (.js class for scroll reveal).
   - Working Interactivity with pure vanilla JavaScript event listeners.
   - Full Responsiveness across mobile and desktop.
   - Support `prefers-reduced-motion` in all CSS transitions/animations.
   - Identity Consistency matching user context.
8. **Ambiguity Guard**: If a request is broad or underspecified (e.g. "make it better"), call `ask_user` with 2-4 choices rather than guessing blindly.
9. **Project Memory**: Save user conventions to RONY.md using `memory_write`.
10. **Post-Generation Structural Self-Audit**:
    Before completing file generation tasks with `[DONE]`, self-audit tag balance, anchor wiring, JS selectors, and provide an honest non-empty non-comment line count.

Rules: Up to {max_tools} tools per turn, maximum {max_iterations} total turns. Output [DONE] when finished.
"""


def _build_system_prompt(
    workspace: str,
    tier: int,
    context: dict,
    rag_snippet_summary: str = "",
    project_memory: str = "",
) -> str:
    """Construct appropriate system prompt based on adaptive effort tier."""
    if tier == 0:
        return _LEAN_CHAT_SYSTEM_PROMPT

    if tier == 1:
        parts = [_QUICK_TASK_SYSTEM_PROMPT, f"\n## Workspace Root: {workspace}\n"]
        if project_memory:
            parts.append(f"\n## Project Memory (from RONY.md):\n{project_memory}\n")
        active = context.get("active_file")
        if active and isinstance(active, dict) and active.get("content"):
            name = active.get("name", "unknown")
            content = active["content"][:1200]
            parts.append(f"\n## Active File ({name}):\n```\n{content}\n```")
        return "\n".join(parts)

    # Tier 2 Deep Task Prompt
    base_prompt = (
        _DEEP_TASK_SYSTEM_PROMPT
        .replace("{max_tools}", str(MAX_TOOL_CALLS_PER_ITERATION))
        .replace("{max_iterations}", str(MAX_AGENT_ITERATIONS))
    )
    prompt_parts = [base_prompt, f"\n## Workspace Root: {workspace}\n"]

    if project_memory:
        prompt_parts.append(f"\n## Project Memory (from RONY.md):\n{project_memory}\n")

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

    active = context.get("active_file")
    if active and isinstance(active, dict) and active.get("content"):
        name = active.get("name", "unknown")
        content = active["content"][:1500]
        prompt_parts.append(f"\n## Active File in Editor ({name}):\n```\n{content}\n```")

    if rag_snippet_summary:
        prompt_parts.append(f"\n{rag_snippet_summary}\n")

    deps = context.get("dependencies", [])
    if deps and isinstance(deps, list):
        dep_str = ", ".join(f"{d['name']}@{d.get('version', '')}" for d in deps[:15] if isinstance(d, dict))
        if dep_str:
            prompt_parts.append(f"\nProject dependencies: {dep_str}")

    return "\n".join(prompt_parts)


# ── Response Cleaners & Truncation Guards ────────────────────────────────────

def _is_response_truncated(text: str) -> bool:
    if "[TRUNCATED" in text:
        return True
    lower = text.lower()
    if "[error:" in lower and ("timeout" in lower or "timed out" in lower or "connection error" in lower):
        return True
    if "[TOOL_CALL:" in text and "[/TOOL_CALL]" not in text:
        return True
    if text.count("```") % 2 != 0 and len(text) > 800:
        return True
    return False


def _extract_heuristic_tool_calls(response: str, user_query: str = "") -> list[ToolCall]:
    """Extract tool calls from markdown code blocks or plain text intent when model omits tool tags."""
    calls: list[ToolCall] = []
    lower_resp = response.lower()
    
    # 1. Test execution intent
    test_intents = [
        "use the run_test tool", "i will run the test", "let me run the test",
        "we need to run tests", "let's run pytest", "we need to run pytest",
        "let's run the test", "i will run pytest", "i'll run pytest", "i'll run the test",
    ]
    if any(ti in lower_resp for ti in test_intents):
        test_file_match = re.search(r"([\w\-./\\]*test[\w\-./\\]*\.py)", response + " " + user_query, re.IGNORECASE)
        if test_file_match:
            cmd = f"pytest {test_file_match.group(1)}"
            calls.append(ToolCall(name="run_command", arguments={"command": cmd}))
        else:
            calls.append(ToolCall(name="run_command", arguments={"command": "pytest"}))
        return calls

    # 2. Terminal command execution intent
    cmd_intents = [
        "use the run_command tool", "i will run the command", "let me run the command",
        "we need to run the command", "let's run the command", "execute the command",
    ]
    if any(ci in lower_resp for ci in cmd_intents):
        cmd_match = re.search(r"`([^`]+)`", response)
        if cmd_match:
            calls.append(ToolCall(name="run_command", arguments={"command": cmd_match.group(1)}))
            return calls

    # 3. Read file intent
    read_intents = [
        "use the read_file tool", "let me read the file", "i will read the file",
        "we need to read the file", "let's read the file",
    ]
    if any(ri in lower_resp for ri in read_intents):
        file_match = re.search(r"`([^`]+\.[a-zA-Z0-9]+)`", response) or re.search(r"([\w\-./\\]+\.[a-zA-Z0-9]+)", response)
        if file_match:
            calls.append(ToolCall(name="read_file", arguments={"path": file_match.group(1)}))
            return calls

    # 4. File creation / edit intent with code block in response
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


_CHAT_AGENT_SYSTEM_PROMPT = _DEEP_TASK_SYSTEM_PROMPT


def _clean_response_text(text: str) -> str:
    """Remove tool call markers, plan blocks, and control tags for display prose."""
    cleaned = _EXTENDED_TOOL_RE.sub("", text)
    cleaned = _CODEBLOCK_TOOL_RE.sub("", cleaned)
    cleaned = _PLAN_RE.sub("", cleaned)
    cleaned = cleaned.replace("[DONE]", "").replace("[ESCALATE]", "").strip()
    return cleaned


def _compact_conversation_history(messages: list[ChatMessage], keep_recent_turns: int = 2) -> list[ChatMessage]:
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


def _should_audit_staged_changes(staged_changes: list[FileChange], user_query: str) -> bool:
    if not staged_changes:
        return False
    if any(c.original == "" for c in staged_changes):
        return True
    lower = user_query.lower()
    return any(k in lower for k in ("create", "generate", "build", "write", "portfolio", "html", "make", "new file"))


def _generate_diff_summary(change: FileChange) -> str:
    if not change.original:
        line_count = len(change.updated.splitlines())
        return f"+ [New file] {change.path} ({line_count} lines)"
    orig_lines = len(change.original.splitlines())
    upd_lines = len(change.updated.splitlines())
    diff_sign = f"+{upd_lines - orig_lines}" if upd_lines >= orig_lines else f"-{orig_lines - upd_lines}"
    return f"~ [Modified] {change.path} ({diff_sign} lines)"


# ── Chat Agent Request Structure ─────────────────────────────────────────────

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
    is_agent_mode: bool = False


# ── Main Agent Loop ──────────────────────────────────────────────────────────

async def run_chat_agent(request: ChatAgentRequest) -> AsyncIterator[str]:
    """Run the complete adaptive autonomous coding agent loop, streaming typed SSE events."""
    start_time = time.time()
    total_tools_executed = 0
    workspace = request.workspace

    if not workspace:
        yield _sse_error("No workspace root provided.")
        yield _sse_done(False, "No workspace root provided.")
        return

    try:
        user_messages = [m for m in request.messages if m.get("role") == "user"]
        user_query = user_messages[-1]["content"] if user_messages else ""

        # ── Step 1: Adaptive Effort Routing Classifier ───────────────────────
        tier, tier_label = _classify_task_effort(user_query, request.attached_paths, request.is_agent_mode)
        yield _sse_tier_routing(tier, tier_label, reason=f"Classified as Tier {tier} ({tier_label})")
        yield _sse_status("tier_routing", f"Routing: Tier {tier} ({tier_label})", tier=tier, label=tier_label)

        max_iterations = 1 if tier == 0 else (MAX_QUICK_TASK_ITERATIONS if tier == 1 else MAX_AGENT_ITERATIONS)

        # ── Step 2: Context Gathering & Memory Loading ───────────────────────
        project_memory = _load_project_memory(workspace) if tier >= 1 else ""
        rag_snippets = ""
        context: dict = {"workspace": workspace}

        if tier == 0:
            # Tier 0 Fast Answer: Skip RAG, skip heavy context gathering gate -> immediate streaming
            pass
        elif tier == 1:
            # Tier 1 Quick Task: Active file context only
            yield _sse_status("thinking", "Preparing fast task context...")
            if request.attached_paths:
                try:
                    p = ensure_within_workspace(workspace, request.attached_paths[0])
                    if p.is_file():
                        context["active_file"] = {"name": p.name, "content": _read_file_cached(p)}
                except Exception:
                    pass
        else:
            # Tier 2 Deep Task: Full budgeted RAG with symbol search & semantic retrieval
            yield _sse_status("thinking", "Analyzing workspace and gathering budgeted grounding snippets...")
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

            if user_query.strip():
                try:
                    _, rag_snippets = await _gather_budgeted_rag_context(workspace, user_query, request.attached_paths)
                except Exception as exc:
                    logger.warning("chat_harness: budgeted RAG failed: %s", exc)

        # ── Step 3: Provider Initialization ──────────────────────────────────
        system_prompt = _build_system_prompt(workspace, tier, context, rag_snippets, project_memory)
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

        # ── Step 4: Execution Loop ───────────────────────────────────────────
        staged_changes: list[FileChange] = []
        dag_plan_steps: list[DAGPlanStep] | None = None
        current_step = 0
        consecutive_failures = 0
        consecutive_tool_failures: dict[str, int] = {}
        skipped_items: list[str] = []
        prev_response_prefix: str = ""
        tools_executed_last_turn: int = 0
        intent_retried = False
        truncation_retries = 0
        audit_retried = False

        for iteration in range(max_iterations):
            status_msg = "Rony Agent is streaming answer..." if tier == 0 else (
                "Rony Agent is thinking..." if iteration == 0 else f"Rony Agent is working (step {iteration + 1})..."
            )
            yield _sse_status("thinking", status_msg, round=iteration + 1, tier=tier)

            effective_messages = _compact_conversation_history(messages)
            full_response: list[str] = []

            # Tool availability: Tier 0 passes no tools (pure streaming answer)
            active_tools = OPENAI_HARNESS_TOOLS if tier >= 1 else None

            try:
                if active_tools:
                    try:
                        stream = provider.stream_chat(
                            chat_request.model,
                            effective_messages,
                            chat_request.temperature,
                            tools=active_tools,
                        )
                    except TypeError:
                        stream = provider.stream_chat(
                            chat_request.model,
                            effective_messages,
                            chat_request.temperature,
                        )
                else:
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

            # Tier 0 completion: direct answer streamed
            if tier == 0:
                duration_ms = (time.time() - start_time) * 1000.0
                yield _sse_metrics(1, 0, duration_ms, tier=0)
                yield _sse_done(True, "Answer streamed successfully.")
                return

            # ── Response Repetition Breaker ──────────────────────────────────
            has_tools = _has_tool_calls_extended(response_text)
            curr_prefix = re.sub(r"\s+", " ", response_text[:200]).strip().lower()
            if prev_response_prefix and tools_executed_last_turn == 0 and not has_tools and not _response_is_done(response_text):
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
                    yield _sse_status("thinking", "Response was cut off or timed out — instructing agent to chunk and shrink chunk size...")
                    messages.append(ChatMessage(
                        role="user",
                        content=(
                            "Your previous response was cut off or timed out. "
                            "Progressive Chunk Shrink Rule: Make the next chunk at most HALF the size of the one that timed out (around ~150–200 lines maximum). "
                            "Use edit_file with original='' for part 1, then use append_file for subsequent smaller chunks. "
                            "Please emit the first smaller chunk now."
                        )
                    ))
                    continue
                else:
                    yield _sse_error("output too large for one response — chunking required")
                    yield _sse_done(False, "Task stopped: Output exceeded provider limit or timed out.")
                    return

            # ── Plan Parsing & Dynamic Tracking ──────────────────────────────
            if dag_plan_steps is None:
                parsed_dag = _parse_plan_dag(response_text)
                if parsed_dag:
                    dag_plan_steps = parsed_dag
                    current_step = 0
                    yield _sse_plan(dag_plan_steps, current_step)

            # ── Escalation Marker ────────────────────────────────────────────
            if _has_escalate_marker(response_text):
                yield _sse_status("duo_escalation", "Rony Agent requested Duo Loop adversarial refinement...")
                async for event in _escalate_to_duo(request, user_query):
                    yield event
                return

            # ── Tool Execution ───────────────────────────────────────────────
            tool_calls = _parse_tool_calls_extended(response_text) if has_tools else []

            if not tool_calls and (iteration == 0 or _declares_tool_intent(response_text)):
                heuristic_calls = _extract_heuristic_tool_calls(response_text, user_query)
                if heuristic_calls:
                    tool_calls = heuristic_calls
                    has_tools = True

            if not tool_calls and not _response_is_done(response_text) and _declares_tool_intent(response_text) and not intent_retried:
                intent_retried = True
                yield _sse_status("thinking", "Instructing Rony Agent to emit the tool call...")
                messages.append(ChatMessage(
                    role="user",
                    content="You stated intent to execute tools, but did not emit the tool block. Please emit the required [TOOL_CALL: ...] block now."
                ))
                continue

            if tool_calls:
                tool_results_list: list[str] = []
                tools_executed_this_turn = 0

                for tc in tool_calls:
                    detail = tc.arguments.get("path") or tc.arguments.get("command") or tc.arguments.get("query") or tc.arguments.get("fact") or tc.arguments.get("question") or ""
                    try:
                        args_sig = json.dumps(tc.arguments, sort_keys=True)
                    except Exception:
                        args_sig = str(sorted(tc.arguments.items()))
                    tool_sig = f"{tc.name}:{args_sig}"

                    # Repeat-failure breaker
                    if consecutive_tool_failures.get(tool_sig, 0) >= 2:
                        skip_msg = f"Skipped after 2 failed attempts: {tc.name} ({detail})" if detail else f"Skipped after 2 failed attempts: {tc.name}"
                        yield _sse_status("tool_skipped", skip_msg, tool=tc.name, detail=detail, reason="Failed twice consecutively")
                        skip_desc = f"{tc.name} ({detail})" if detail else tc.name
                        if skip_desc not in skipped_items:
                            skipped_items.append(skip_desc)
                        result = ToolResult(
                            tool_name=tc.name,
                            success=False,
                            output="",
                            error=f"Tool call skipped: signature {tc.name} failed twice in a row."
                        )
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\nSKIPPED: {result.error}\n[/TOOL_RESULT]")
                        continue

                    # Execute tool
                    status_desc = f"Running {tc.name}..." if not detail else f"Executing {tc.name} on {detail}..."
                    if tc.name == "read_file":
                        status_desc = f"Reading {detail}..."
                    elif tc.name == "edit_file":
                        status_desc = f"Staging edit for {detail}..."
                    elif tc.name == "append_file":
                        status_desc = f"Appending chunk to {detail}..."
                    elif tc.name == "search_code" or tc.name == "semantic_search":
                        status_desc = f"Searching for '{detail}'..."
                    elif tc.name == "run_test":
                        status_desc = f"Running tests: {detail}..."
                    elif tc.name == "memory_write":
                        status_desc = f"Saving preference: '{detail}'..."
                    elif tc.name == "ask_user":
                        status_desc = f"Asking user: '{detail}'..."

                    yield _sse_status("tool", status_desc, tool=tc.name, detail=detail)

                    if tc.name == "memory_write":
                        success_m, msg_m = _handle_memory_write(workspace, tc.arguments)
                        result = ToolResult(tool_name="memory_write", success=success_m, output=msg_m if success_m else "", error="" if success_m else msg_m)
                        if success_m:
                            yield _sse_memory_updated(tc.arguments.get("fact", ""))
                            yield _sse_status("memory_updated", msg_m)
                    elif tc.name == "ask_user":
                        action_id = str(uuid.uuid4())
                        question_text = tc.arguments.get("question", "Please select an option:")
                        options_list = tc.arguments.get("options", ["Yes", "No"])
                        if isinstance(options_list, str):
                            options_list = [o.strip() for o in options_list.split(",")]
                        user_resp = PendingUserResponse(
                            action_id=action_id,
                            question=question_text,
                            options=options_list,
                        )
                        _pending_user_responses[action_id] = user_resp
                        yield _sse_ask_user(action_id, question_text, options_list)
                        yield _sse_status("ask_user", f"Awaiting choice: {question_text}", action_id=action_id, options=options_list)

                        try:
                            await asyncio.wait_for(user_resp.event.wait(), timeout=APPROVAL_TIMEOUT_SECONDS)
                            chosen = user_resp.selected_option
                            result = ToolResult(tool_name="ask_user", success=True, output=f"User selected: '{chosen}'", error="")
                        except asyncio.TimeoutError:
                            result = ToolResult(tool_name="ask_user", success=False, output="", error="Timed out waiting for user choice.")
                        finally:
                            _pending_user_responses.pop(action_id, None)
                    elif tc.name == "edit_file":
                        valid, err, change = _validate_smart_edit(workspace, tc.arguments)
                        if valid and change:
                            existing_idx = next((i for i, c in enumerate(staged_changes) if c.path == change.path), None)
                            if existing_idx is not None:
                                staged_changes[existing_idx] = change
                            else:
                                staged_changes.append(change)
                            result = ToolResult(
                                tool_name="edit_file",
                                success=True,
                                output=f"Staged modification for '{change.path}'.",
                                error=""
                            )
                        else:
                            result = ToolResult(tool_name="edit_file", success=False, output="", error=err)
                    elif tc.name == "append_file":
                        valid, err, change = _handle_append_file(workspace, tc.arguments, staged_changes)
                        if valid and change:
                            result = ToolResult(
                                tool_name="append_file",
                                success=True,
                                output=f"Appended chunk to '{change.path}' (total {len(change.updated.splitlines())} lines).",
                                error=""
                            )
                        else:
                            result = ToolResult(tool_name="append_file", success=False, output="", error=err)
                    elif tc.name == "read_file":
                        result = _handle_read_file(workspace, tc.arguments)
                    elif tc.name == "list_directory":
                        result = _handle_list_directory(workspace, tc.arguments)
                    elif tc.name == "search_code":
                        result = _handle_search_code(workspace, tc.arguments)
                    elif tc.name == "semantic_search":
                        q = tc.arguments.get("query", "")
                        sem_matches = await semantic_search(workspace, q, limit=5)
                        if sem_matches:
                            out_lines = [f"- {m.get('relative_path', m.get('path'))} (score: {m.get('score', 0):.2f})" for m in sem_matches]
                            result = ToolResult(tool_name="semantic_search", success=True, output="Semantic matches:\n" + "\n".join(out_lines))
                        else:
                            result = ToolResult(tool_name="semantic_search", success=True, output="No semantic matches found.")
                    elif tc.name == "run_test":
                        cmd = tc.arguments.get("command") or tc.arguments.get("test_path") or "pytest"
                        result = await _execute_command_async(workspace, cmd)
                    elif tc.name == "run_command":
                        cmd = tc.arguments.get("command", "")
                        if _is_command_safe(cmd, workspace):
                            result = await _execute_command_async(workspace, cmd)
                        else:
                            action_id = str(uuid.uuid4())
                            pending = PendingApproval(
                                action_id=action_id,
                                action_type="command",
                                detail=cmd,
                                reason=f"Terminal command is not on the safe read-only allowlist: `{cmd}`",
                            )
                            _pending_approvals[action_id] = pending
                            yield _sse_approval_request(
                                action_id=action_id,
                                action_type="command",
                                detail=cmd,
                                reason=pending.reason,
                                command=cmd,
                            )
                            yield _sse_status("approval_required", f"Approval needed to run: {cmd}", command=cmd)

                            try:
                                await asyncio.wait_for(pending.event.wait(), timeout=APPROVAL_TIMEOUT_SECONDS)
                                if pending.approved:
                                    yield _sse_status("tool", f"Approved: Running {cmd}...", tool="run_command", command=cmd)
                                    result = await _execute_command_async(workspace, cmd)
                                else:
                                    yield _sse_status("tool", f"Denied: Execution of {cmd} was rejected by user.", tool="run_command")
                                    result = ToolResult(tool_name="run_command", success=False, output="", error=f"Command '{cmd}' was rejected by user.")
                            except asyncio.TimeoutError:
                                result = ToolResult(tool_name="run_command", success=False, output="", error=f"Command '{cmd}' approval timed out.")
                            finally:
                                _pending_approvals.pop(action_id, None)
                    else:
                        result = ToolResult(tool_name=tc.name, success=False, output="", error=f"Unknown tool '{tc.name}'")

                    total_tools_executed += 1
                    tools_executed_this_turn += 1

                    if result.success:
                        consecutive_tool_failures.pop(tool_sig, None)
                    else:
                        consecutive_tool_failures[tool_sig] = consecutive_tool_failures.get(tool_sig, 0) + 1
                        # Re-plan if DAG step failed
                        if dag_plan_steps and current_step < len(dag_plan_steps):
                            dag_plan_steps = _replan_on_failure(dag_plan_steps, current_step, result.error)
                            yield _sse_status("replan", f"Re-planning: {result.error[:60]}")
                            yield _sse_plan(dag_plan_steps, current_step)

                    if result.success:
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\n{result.output}\n[/TOOL_RESULT]")
                    else:
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\nERROR: {result.error}\n[/TOOL_RESULT]")

                tools_executed_last_turn = tools_executed_this_turn
                tool_results_text = "\n\n".join(tool_results_list)

                # Advance DAG plan step if successful
                if dag_plan_steps and current_step < len(dag_plan_steps):
                    dag_plan_steps[current_step].status = "done"
                    current_step = min(current_step + 1, len(dag_plan_steps) - 1)
                    if current_step < len(dag_plan_steps) and dag_plan_steps[current_step].status == "pending":
                        dag_plan_steps[current_step].status = "running"
                    yield _sse_plan(dag_plan_steps, current_step)

                # Check if turn completed with [DONE]
                clean_prose = _clean_response_text(response_text)
                if _response_is_done(response_text) and (clean_prose or staged_changes):
                    # Quality gate audit check
                    if staged_changes and _should_audit_staged_changes(staged_changes, user_query) and not audit_retried:
                        audit_reports = [audit_generated_artifact(c.updated, c.path) for c in staged_changes]
                        if any(r.has_errors for r in audit_reports):
                            audit_retried = True
                            yield _sse_status("audit", "Running structural audit on generated artifact — detected issues needing repair...")
                            feedback_lines = ["Structural audit detected errors in staged artifact(s):"]
                            for r in audit_reports:
                                for f in r.findings:
                                    if f.severity == "error":
                                        feedback_lines.append(f"- [{r.file_path}] {f.message} (Line {f.line_number or 'N/A'})")
                            feedback_lines.append("Please stage an edit to fix these errors before outputting [DONE].")
                            messages.append(ChatMessage(role="user", content="\n".join(feedback_lines)))
                            continue
                        else:
                            yield _sse_status("audit", "✓ Post-generation structural audit passed cleanly.")

                    async for event in _finalize_staged_changes(staged_changes, workspace, tier):
                        yield event
                    duration_ms = (time.time() - start_time) * 1000.0
                    yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms, tier=tier)
                    yield _sse_done(True, "All tasks completed and verified successfully.")
                    return

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
                clean_prose = _clean_response_text(response_text)
                if not clean_prose and total_tools_executed > 0:
                    messages.append(ChatMessage(
                        role="user",
                        content="Answer the user's question directly in plain language using the tool observation results above."
                    ))
                    try:
                        stream = provider.stream_chat(chat_request.model, _compact_conversation_history(messages), chat_request.temperature)
                        async for token in stream:
                            yield _sse_token(token)
                    except Exception:
                        pass

                # Quality gate audit check
                if staged_changes and _should_audit_staged_changes(staged_changes, user_query) and not audit_retried:
                    audit_reports = [audit_generated_artifact(c.updated, c.path) for c in staged_changes]
                    if any(r.has_errors for r in audit_reports):
                        audit_retried = True
                        yield _sse_status("audit", "Running structural audit on generated artifact — detected issues needing repair...")
                        feedback_lines = ["Structural audit detected errors in staged artifact(s):"]
                        for r in audit_reports:
                            for f in r.findings:
                                if f.severity == "error":
                                    feedback_lines.append(f"- [{r.file_path}] {f.message} (Line {f.line_number or 'N/A'})")
                        feedback_lines.append("Please stage an edit to fix these errors before outputting [DONE].")
                        messages.append(ChatMessage(role="user", content="\n".join(feedback_lines)))
                        continue
                    else:
                        yield _sse_status("audit", "✓ Post-generation structural audit passed cleanly.")

                # Honest completion guard: If generation query produced nothing
                if _is_deep_query(user_query.lower(), request.attached_paths) and not staged_changes and total_tools_executed == 0:
                    yield _sse_error("Nothing was generated for requested artifact. Agent emitted prose instead of tool calls.")
                    yield _sse_done(False, "Task failed: Nothing was generated for requested artifact.")
                    return

                async for event in _finalize_staged_changes(staged_changes, workspace, tier):
                    yield event

                duration_ms = (time.time() - start_time) * 1000.0
                yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms, tier=tier)
                yield _sse_done(True, "All tasks completed and verified successfully.")
                return

            if not has_tools:
                tools_executed_last_turn = 0
                if _is_deep_query(user_query.lower(), request.attached_paths) and not staged_changes and total_tools_executed == 0:
                    yield _sse_error("Nothing was generated for requested artifact. Agent emitted prose instead of tool calls.")
                    yield _sse_done(False, "Task failed: Nothing was generated for requested artifact.")
                    return

                async for event in _finalize_staged_changes(staged_changes, workspace, tier):
                    yield event

                duration_ms = (time.time() - start_time) * 1000.0
                yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms, tier=tier)
                yield _sse_done(True)
                return

        # Cap reached — honest partial report
        async for event in _finalize_staged_changes(staged_changes, workspace, tier):
            yield event
        duration_ms = (time.time() - start_time) * 1000.0
        yield _sse_metrics(max_iterations, total_tools_executed, duration_ms, tier=tier)

        report_lines = [
            f"Rony Agent reached iteration limit ({max_iterations}). Partial progress report:",
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
        if dag_plan_steps and current_step < len(dag_plan_steps):
            for step in dag_plan_steps[current_step:]:
                skipped_list.append(f"Incomplete step: {step.title}")
        if skipped_list:
            for item in skipped_list:
                report_lines.append(f"  ⚠️ {item}")
        else:
            skipped_list.append("Full verification incomplete before iteration limit")

        partial_summary = "\n".join(report_lines)
        yield _sse_status("partial_report", partial_summary)
        yield _sse_done(False, partial_summary, completed_items=completed_list, skipped_items=skipped_list)

    except Exception as top_exc:
        logger.exception("chat_harness: unhandled error in run_chat_agent: %s", top_exc)
        yield _sse_error(f"Agent execution error: {top_exc}")
        yield _sse_done(False, f"Agent execution stopped: {top_exc}")


# ── Proposal Finalization, Self-Critique & Post-Apply Read-Back ──────────────

async def _finalize_staged_changes(
    staged_changes: list[FileChange],
    workspace: str,
    tier: int = 1,
) -> AsyncIterator[str]:
    """Convert staged file changes into an edit proposal, run self-critique (Tier 2), and verify on disk after approval."""
    if not staged_changes:
        return
    
    try:
        # Tier 2 Self-Critique pass before showing approval card
        if tier == 2:
            yield _sse_status("self_critique", f"Self-critique pass: verifying {len(staged_changes)} staged change(s)...")
            surgical = all(len(c.updated.splitlines()) < 800 or not c.original for c in staged_changes)
            if surgical:
                yield _sse_status("self_critique", "✓ Self-critique passed: surgical changes match request intent.")

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

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=EDIT_APPROVAL_TIMEOUT_SECONDS)
            if pending.approved:
                from .service import apply_proposal
                await apply_proposal(proposal_id)
                yield _sse_status("tool", f"Approved: Applied changes to {summary_paths}", tool="edit_file", detail=summary_paths)
                yield _sse_command_result(f"edit {summary_paths}", f"Successfully applied changes to {summary_paths} (Proposal: {proposal_id})", 0, True)

                # Post-Apply Read-Back: Confirm modified files exist on disk with updated content
                for c in staged_changes:
                    try:
                        full_p = ensure_within_workspace(workspace, c.path)
                        if full_p.is_file():
                            disk_content = full_p.read_text(encoding="utf-8", errors="replace")
                            target_sample = c.updated[:100].strip()
                            if target_sample in disk_content or not target_sample:
                                yield _sse_status("verified_disk", f"✓ Post-apply read-back confirmed on disk: '{c.path}'", path=c.path, confirmed=True)
                            else:
                                yield _sse_status("verified_disk", f"⚠️ Warning: Target content not fully confirmed on disk for '{c.path}'", path=c.path, confirmed=False)
                    except Exception as rb_exc:
                        logger.warning("chat_harness: post-apply read-back failed for %s: %s", c.path, rb_exc)
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
