from __future__ import annotations

"""
approval_coordinator.py - Coordinates interactive user permissions, questions, and git checkpoints.
"""

import asyncio
import fnmatch
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.core.paths import normalize_workspace
from .checkpoint_manager import (
    SENSITIVE_FILE_PATTERNS,
    _ensure_git_checkpoint,
    _is_sensitive_filename,
    undo_turn_files,
)

logger = logging.getLogger(__name__)

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
    workspace: str = ""
    command: str = ""
    always_allow: bool = False
    trust_pattern: str | None = None
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False
    is_native_fallback: bool = False
    task_id: str = ""
    agent_role: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    integrity_status: str = "valid"
    integrity_warning: str | None = None
    relocation_event: dict[str, Any] | None = None
    replaced_by: str | None = None
    status: str = "pending"
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


@dataclass
class PendingEscalation:
    """An adaptive escalation recommendation awaiting user choice ([Escalate] vs [Continue with Rony])."""
    action_id: str
    task: str
    reasoning: str
    confidence: float
    workspace: str = ""
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str = ""  # "escalate" | "continue"
    created_at: float = field(default_factory=time.time)


_pending_approvals: dict[str, PendingApproval] = {}
_pending_user_responses: dict[str, PendingUserResponse] = {}
_pending_escalations: dict[str, PendingEscalation] = {}


def register_pending_escalation(escalation: PendingEscalation) -> None:
    """Register a pending escalation recommendation."""
    _pending_escalations[escalation.action_id] = escalation


def resolve_escalation(action_id: str = "", decision: str = "continue", workspace: str = "", task: str = "") -> bool:
    """Resolve a pending escalation decision ('continue' or 'escalate').

    Requires an exact action_id match. Workspace/task are accepted for API
    compatibility but are NEVER used as fallback resolution criteria (AUD-006).
    Returns False when the action_id is absent or not found.
    """
    if not action_id:
        logger.warning("resolve_escalation: called without action_id — rejecting (AUD-006)")
        return False
    pending = _pending_escalations.get(action_id)
    if pending is None or pending.event.is_set():
        logger.warning("resolve_escalation: action_id %s not found or already resolved", action_id)
        return False
    pending.decision = decision
    pending.event.set()
    return True


def get_pending_escalation(action_id: str) -> Optional[PendingEscalation]:
    """Retrieve pending escalation by action_id."""
    return _pending_escalations.get(action_id)


def remove_pending_escalation(action_id: str) -> None:
    """Clean up pending escalation."""
    _pending_escalations.pop(action_id, None)

def _get_trusted_commands_path(workspace: str) -> Path:
    base = Path(workspace) if workspace else Path.cwd()
    os_dir = base / ".code_os"
    os_dir.mkdir(parents=True, exist_ok=True)
    return os_dir / "trusted_commands.json"


_EXPLICITLY_TRUSTED_WORKSPACES: set[str] = set()


def _is_workspace_trusted_sync(workspace: str) -> bool:
    """Synchronously verify whether a workspace has been explicitly trusted by the user."""
    if not workspace:
        return False
    try:
        from app.core.paths import normalize_workspace
        normalized = normalize_workspace(workspace)
        norm_str = str(normalized)
        if norm_str in _EXPLICITLY_TRUSTED_WORKSPACES:
            return True

        import sqlite3
        from app.core.config import get_settings
        db_path = get_settings().database_path
        if not db_path.exists():
            return False

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, trusted FROM workspace_trust WHERE trusted = 1")
            rows = cursor.fetchall()
            for row_path_str, trusted in rows:
                try:
                    row_path = normalize_workspace(str(row_path_str))
                except Exception:
                    continue
                try:
                    normalized.relative_to(row_path)
                    is_child = True
                except ValueError:
                    is_child = False
                if normalized == row_path or is_child:
                    return True
    except Exception as exc:
        logger.debug("Failed to check workspace trust sync for %s: %s", workspace, exc)
    return False


def _load_trusted_commands(workspace: str) -> list[str]:
    # Honor <workspace>/.code_os/trusted_commands.json ONLY when workspace is trusted
    if not _is_workspace_trusted_sync(workspace):
        return []
    try:
        p = _get_trusted_commands_path(workspace)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [
                    str(x).strip() for x in data
                    if str(x).strip() and str(x).strip().strip("\"'") != "*"
                ]
    except Exception as exc:
        logger.warning("chat_harness: failed to load trusted commands: %s", exc)
    return []


FORBIDDEN_TRUST_OPERATORS = (";", "&&", "||", "|", "&", ">", "<", "`", "$(", "${")


def _save_trusted_command(workspace: str, pattern: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    # Reject bare wildcard pattern on save
    if pattern == "*" or pattern.strip("\"'") == "*":
        return False
    # Reject any shell operator
    if any(op in pattern for op in FORBIDDEN_TRUST_OPERATORS):
        return False

    try:
        import shlex
        tokens = shlex.split(pattern)
        if not tokens or tokens == ["*"] or tokens[0] == "*":
            return False
    except Exception:
        return False

    try:
        if workspace:
            from app.core.paths import normalize_workspace
            _EXPLICITLY_TRUSTED_WORKSPACES.add(str(normalize_workspace(workspace)))

        cmds = _load_trusted_commands(workspace)
        if pattern not in cmds:
            cmds.append(pattern)
            p = _get_trusted_commands_path(workspace)
            p.write_text(json.dumps(cmds, indent=2), encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("chat_harness: failed to save trusted command '%s': %s", pattern, exc)
        return False


def _remove_trusted_command(workspace: str, pattern: str) -> bool:
    pattern = pattern.strip()
    try:
        cmds = _load_trusted_commands(workspace)
        if pattern in cmds:
            cmds.remove(pattern)
            p = _get_trusted_commands_path(workspace)
            p.write_text(json.dumps(cmds, indent=2), encoding="utf-8")
            return True
    except Exception as exc:
        logger.warning("chat_harness: failed to remove trusted command '%s': %s", pattern, exc)
    return False


def _match_command_pattern(pat_tokens: list[str], cmd_tokens: list[str]) -> bool:
    """Match command tokens against pattern tokens structurally."""
    if not pat_tokens or not cmd_tokens:
        return False
    # Bare wildcard is never allowed
    if pat_tokens == ["*"] or pat_tokens[0] == "*":
        return False

    # Exact token match
    if pat_tokens == cmd_tokens:
        return True

    # If pattern ends with *, e.g. ["npm", "*"] or ["git", "*"]
    if pat_tokens[-1] == "*":
        prefix_tokens = pat_tokens[:-1]
        if len(cmd_tokens) >= len(prefix_tokens) and cmd_tokens[:len(prefix_tokens)] == prefix_tokens:
            return True

    # If pattern is e.g. ["pytest*"] as a single token
    if len(pat_tokens) == 1 and pat_tokens[0].endswith("*"):
        prefix = pat_tokens[0][:-1]
        if cmd_tokens[0] == prefix or cmd_tokens[0].startswith(prefix):
            return True

    # Known runner prefix matching, e.g. "npm test" matches "npm test -- --watch"
    if pat_tokens[0] in ("npm", "pytest", "python", "vitest", "jest", "cargo", "go"):
        if len(cmd_tokens) >= len(pat_tokens) and cmd_tokens[:len(pat_tokens)] == pat_tokens:
            return True

    return False


def _is_command_trusted(workspace: str, cmd: str) -> bool:
    """Check if command matches any workspace trusted command pattern."""
    if not workspace or not cmd:
        return False
    cmd_clean = cmd.strip()

    # Never trust compound commands or shell chaining
    if any(op in cmd_clean for op in FORBIDDEN_TRUST_OPERATORS):
        return False

    trusted = _load_trusted_commands(workspace)
    if not trusted:
        return False

    try:
        import shlex
        cmd_tokens = shlex.split(cmd_clean)
    except Exception:
        cmd_tokens = cmd_clean.split()

    if not cmd_tokens:
        return False

    for pattern in trusted:
        pat_clean = pattern.strip()
        # Reject bare wildcard pattern on match
        if not pat_clean or pat_clean == "*" or pat_clean.strip("\"'") == "*":
            continue
        if any(op in pat_clean for op in FORBIDDEN_TRUST_OPERATORS):
            continue

        try:
            import shlex
            pat_tokens = shlex.split(pat_clean)
        except Exception:
            pat_tokens = pat_clean.split()

        if _match_command_pattern(pat_tokens, cmd_tokens):
            return True

    return False


async def register_pending_approval(
    pending: PendingApproval,
    task_id: str = "",
    workspace: str = "",
    payload: Optional[dict] = None,
    expires_in_seconds: float = 3600.0,
) -> None:
    """Store in-memory and persist to SQLite pending_approvals table."""
    _pending_approvals[pending.action_id] = pending
    ws = workspace or pending.workspace
    tid = task_id or pending.proposal_id or "task_general"
    payload_dict = payload or {
        "detail": pending.detail,
        "reason": pending.reason,
        "proposal_id": pending.proposal_id,
        "path": pending.path,
        "diff_summary": pending.diff_summary,
        "command": pending.command,
        "is_native_fallback": pending.is_native_fallback,
        "agent_role": pending.agent_role,
        "task_id": tid,
        "metadata": pending.metadata,
        "relocation_event": pending.relocation_event,
    }
    now = time.time()
    expires_at = now + expires_in_seconds
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        await pool.write_execute(
            """
            INSERT OR REPLACE INTO pending_approvals
            (action_id, task_id, workspace, action_type, payload_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pending.action_id,
                tid,
                ws,
                pending.action_type,
                json.dumps(payload_dict),
                now,
                expires_at,
            )
        )
    except Exception as exc:
        logger.warning("approval_coordinator: failed to persist approval %s: %s", pending.action_id, exc)


async def remove_pending_approval(action_id: str) -> None:
    """Remove from in-memory dict and delete from SQLite."""
    _pending_approvals.pop(action_id, None)
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        await pool.write_execute("DELETE FROM pending_approvals WHERE action_id = ?", (action_id,))
    except Exception as exc:
        logger.warning("approval_coordinator: failed to delete approval %s: %s", action_id, exc)


async def request_approval(
    action_id: str,
    action_type: str,
    detail: str,
    reason: str,
    task_id: str = "",
    workspace: str = "",
    payload: Optional[dict] = None,
    proposal_id: str = "",
    command: str = "",
    diff_summary: str = "",
    path: str = "",
    is_native_fallback: bool = False,
    agent_role: str = "",
    metadata: Optional[dict] = None,
) -> PendingApproval:
    """Create, register and persist a pending approval."""
    meta = metadata.copy() if metadata else {}
    if agent_role and "agent_role" not in meta:
        meta["agent_role"] = agent_role
    if task_id and "task_id" not in meta:
        meta["task_id"] = task_id

    pending = PendingApproval(
        action_id=action_id,
        action_type=action_type,
        detail=detail,
        reason=reason,
        proposal_id=proposal_id,
        path=path,
        diff_summary=diff_summary,
        workspace=workspace,
        command=command,
        is_native_fallback=is_native_fallback,
        task_id=task_id,
        agent_role=agent_role,
        metadata=meta,
        created_at=time.time(),
    )
    await register_pending_approval(pending, task_id=task_id, workspace=workspace, payload=payload)
    return pending


async def load_pending_approvals_from_db() -> list[dict]:
    """Reload non-expired pending approvals from SQLite and delete expired ones."""
    now = time.time()
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        # 1. Clean up expired rows (> 1 hour)
        await pool.write_execute("DELETE FROM pending_approvals WHERE expires_at < ?", (now,))
        
        # 2. Query remaining active rows
        rows = await pool.read_query(
            "SELECT action_id, task_id, workspace, action_type, payload_json, created_at, expires_at FROM pending_approvals"
        )
    except Exception as exc:
        logger.warning("approval_coordinator: error loading pending approvals from DB: %s", exc)
        return []

    results = []
    for r in rows:
        action_id = r["action_id"]
        task_id = r["task_id"]
        workspace = r["workspace"]
        action_type = r["action_type"]
        created_at = r["created_at"]
        expires_at = r["expires_at"]
        try:
            payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
        except Exception:
            payload = {}

        if action_id not in _pending_approvals:
            pending = PendingApproval(
                action_id=action_id,
                action_type=action_type,
                detail=payload.get("detail", ""),
                reason=payload.get("reason", ""),
                proposal_id=payload.get("proposal_id", ""),
                path=payload.get("path", ""),
                diff_summary=payload.get("diff_summary", ""),
                workspace=workspace,
                command=payload.get("command", ""),
                is_native_fallback=payload.get("is_native_fallback", False),
                task_id=task_id,
                agent_role=payload.get("agent_role", ""),
                metadata=payload.get("metadata", {}),
                relocation_event=payload.get("relocation_event") or payload.get("metadata", {}).get("relocation_event"),
                created_at=created_at,
            )
            _pending_approvals[action_id] = pending

        results.append({
            "action_id": action_id,
            "task_id": task_id,
            "workspace": workspace,
            "action_type": action_type,
            "payload": payload,
            "created_at": created_at,
            "expires_at": expires_at,
        })
    return results


async def get_all_pending_approvals(workspace: Optional[str] = None) -> list[dict]:
    """Retrieve all active pending approvals, reloading from DB."""
    all_approvals = await load_pending_approvals_from_db()
    if workspace:
        norm_ws = str(normalize_workspace(workspace))
        return [a for a in all_approvals if a.get("workspace") == norm_ws or a.get("workspace") == workspace]
    return all_approvals


async def approve_action(action_id: str, always_allow: bool = False, trust_pattern: str | None = None) -> bool:
    """Approve a pending action, optionally recording command trust for the workspace."""
    pending = _pending_approvals.get(action_id)
    if not pending:
        await load_pending_approvals_from_db()
        pending = _pending_approvals.get(action_id)
    if not pending:
        return False
    pending.approved = True
    pending.always_allow = always_allow
    pending.trust_pattern = trust_pattern
    if always_allow and pending.workspace:
        pattern = trust_pattern or pending.detail
        _save_trusted_command(pending.workspace, pattern)
    pending.event.set()
    await remove_pending_approval(action_id)
    return True


async def reject_action(action_id: str) -> bool:
    """Reject a pending action."""
    pending = _pending_approvals.get(action_id)
    if not pending:
        await load_pending_approvals_from_db()
        pending = _pending_approvals.get(action_id)
    if not pending:
        return False
    pending.approved = False
    pending.event.set()
    await remove_pending_approval(action_id)
    return True


def respond_to_user_question(action_id: str, answer: str) -> bool:
    """Submit user's answer to an ask_user prompt."""
    pending = _pending_user_responses.get(action_id)
    if not pending:
        return False
    pending.selected_option = answer
    pending.event.set()
    return True


def clear_all_pending() -> int:
    """Clear and reject all pending approvals, user responses, and escalations when run is cancelled."""
    cleared = 0
    for action_id, pending in list(_pending_approvals.items()):
        pending.approved = False
        pending.event.set()
        _pending_approvals.pop(action_id, None)
        cleared += 1
    for action_id, user_resp in list(_pending_user_responses.items()):
        user_resp.selected_option = "Cancelled"
        user_resp.event.set()
        _pending_user_responses.pop(action_id, None)
        cleared += 1
    for action_id, esc in list(_pending_escalations.items()):
        esc.decision = "continue"
        esc.event.set()
        _pending_escalations.pop(action_id, None)
        cleared += 1
    return cleared


def get_pending_approvals(job_id: Optional[str] = None) -> list[PendingApproval]:
    """Retrieve in-memory pending approvals, optionally filtered by job_id."""
    if not job_id:
        return list(_pending_approvals.values())
    res = []
    for p in _pending_approvals.values():
        if p.metadata.get("job_id") == job_id or (p.task_id and job_id in p.task_id):
            res.append(p)
        elif not p.metadata.get("job_id"):
            res.append(p)
    return res


async def clear_pending_approvals_for_job(job_id: str) -> None:
    """Clear all pending approvals associated with a specific job."""
    to_remove = [aid for aid, p in _pending_approvals.items() if p.metadata.get("job_id") == job_id or (p.task_id and job_id in p.task_id)]
    for aid in to_remove:
        await remove_pending_approval(aid)


async def reread_and_restage_approval(action_id: str) -> dict[str, Any] | None:
    """Non-auto-approving flow that invalidates old card and creates a fresh one (Phase 12.5.1 G2).

    1. Reads target file on disk.
    2. Updates bounds/anchor against current disk content.
    3. Re-stages the edit with relocated: False.
    4. Creates a fresh PendingApproval (requires fresh user approval).
    5. Invalidates and sets replaced_by on old approval.
    """
    import uuid
    from app.core.paths import ensure_within_workspace

    pending = _pending_approvals.get(action_id)
    if not pending:
        await load_pending_approvals_from_db()
        pending = _pending_approvals.get(action_id)
    if not pending:
        return None

    new_action_id = str(uuid.uuid4())
    ws = pending.workspace
    rel_p = pending.path

    start_line = pending.metadata.get("start_line")
    end_line = pending.metadata.get("end_line")
    reloc_evt = pending.relocation_event or pending.metadata.get("relocation_event")
    if reloc_evt and reloc_evt.get("new_range"):
        start_line, end_line = reloc_evt["new_range"]

    # Re-read file content from disk
    try:
        full_p = ensure_within_workspace(ws, rel_p)
        disk_content = full_p.read_text(encoding="utf-8", errors="replace")
        disk_lines = disk_content.splitlines()
        total_lines = len(disk_lines)
    except Exception as exc:
        logger.error("Failed to re-read file %s: %s", rel_p, exc)
        return None

    if start_line is not None:
        start_line = max(1, min(int(start_line), max(1, total_lines)))
        if end_line is not None:
            end_line = max(start_line, min(int(end_line), total_lines))

    new_meta = dict(pending.metadata or {})
    new_meta["start_line"] = start_line
    new_meta["end_line"] = end_line
    new_meta["status"] = "pending"
    new_meta["edit_type"] = "anchored"
    new_meta["anchor_state"] = "anchored"
    resolved_reloc = {
        "relocated": False,
        "old_range": [start_line, end_line] if start_line is not None and end_line is not None else None,
        "new_range": [start_line, end_line] if start_line is not None and end_line is not None else None,
        "reason": "reread_confirmed",
        "reason_text": f"Re-read against current disk at lines {start_line}-{end_line}" if start_line else "Re-read against current disk",
    }
    new_meta["relocation_event"] = resolved_reloc

    new_pending = PendingApproval(
        action_id=new_action_id,
        action_type=pending.action_type,
        detail=f"lines {start_line}-{end_line} of {rel_p}" if start_line and end_line else pending.detail,
        reason=f"Rony Agent wants to modify {rel_p} (re-read anchored)",
        proposal_id=pending.proposal_id,
        path=rel_p,
        diff_summary=pending.diff_summary,
        workspace=ws,
        command=pending.command,
        approved=False,
        status="pending",
        task_id=pending.task_id,
        agent_role=pending.agent_role,
        metadata=new_meta,
        integrity_status=pending.integrity_status,
        integrity_warning=pending.integrity_warning,
        relocation_event=resolved_reloc,
    )

    _pending_approvals[new_action_id] = new_pending
    pending.status = "invalidated"
    pending.replaced_by = new_action_id
    pending.approved = False
    pending.event.set()
    await remove_pending_approval(action_id)

    try:
        await save_pending_approval(new_pending, workspace=ws, task_id=pending.task_id)
    except Exception as s_err:
        logger.debug("Failed to persist re-read pending approval to db: %s", s_err)

    return {
        "status": "restaged",
        "old_action_id": action_id,
        "new_action_id": new_action_id,
        "approval": {
            "action_id": new_action_id,
            "action_type": new_pending.action_type,
            "detail": new_pending.detail,
            "reason": new_pending.reason,
            "proposal_id": new_pending.proposal_id,
            "path": new_pending.path,
            "diff_summary": new_pending.diff_summary,
            "start_line": start_line,
            "end_line": end_line,
            "edit_type": "anchored",
            "anchor_state": "anchored",
            "relocation_event": resolved_reloc,
            "metadata": new_meta,
            "integrity_status": new_pending.integrity_status,
            "integrity_warning": new_pending.integrity_warning,
        },
    }

