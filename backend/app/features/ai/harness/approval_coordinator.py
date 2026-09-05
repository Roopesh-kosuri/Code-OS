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

def _get_trusted_commands_path(workspace: str) -> Path:
    base = Path(workspace) if workspace else Path.cwd()
    os_dir = base / ".code_os"
    os_dir.mkdir(parents=True, exist_ok=True)
    return os_dir / "trusted_commands.json"


def _load_trusted_commands(workspace: str) -> list[str]:
    try:
        p = _get_trusted_commands_path(workspace)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
    except Exception as exc:
        logger.warning("chat_harness: failed to load trusted commands: %s", exc)
    return []


def _save_trusted_command(workspace: str, pattern: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    try:
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


def _is_command_trusted(workspace: str, cmd: str) -> bool:
    """Check if command matches any workspace trusted command pattern."""
    if not workspace or not cmd:
        return False
    trusted = _load_trusted_commands(workspace)
    cmd_clean = cmd.strip()
    for pattern in trusted:
        if pattern == cmd_clean:
            return True
        if pattern.endswith("*"):
            prefix = pattern[:-1].strip()
            if cmd_clean.startswith(prefix):
                return True
        if pattern in ("pytest", "npm test", "python -m pytest") and (cmd_clean == pattern or cmd_clean.startswith(pattern + " ")):
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
) -> PendingApproval:
    """Create, register and persist a pending approval."""
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
    """Clear and reject all pending approvals and user responses when run is cancelled."""
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
    return cleared
