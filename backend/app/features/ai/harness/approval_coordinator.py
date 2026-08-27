from __future__ import annotations

SENSITIVE_FILE_PATTERNS = (
    ".env", ".env.*", "*.env",
    "*.pem", "id_rsa", "id_rsa*", "*.key",
    ".aws", ".aws/*", ".ssh", ".ssh/*",
    "credentials.json", "serviceAccountKey.json",
    "*.sqlite", "*.sqlite3", "*.db"
)

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


def _is_sensitive_filename(path_str: str) -> tuple[bool, str]:
    """Check if a file path matches sensitive credential/secret patterns."""
    import fnmatch
    p = Path(path_str)
    name = p.name.lower()
    posix_str = path_str.replace("\\", "/").lower()
    for pat in SENSITIVE_FILE_PATTERNS:
        pat_lower = pat.lower()
        if fnmatch.fnmatch(name, pat_lower) or fnmatch.fnmatch(posix_str, pat_lower):
            return True, p.name
        if pat_lower.startswith(".") and name == pat_lower:
            return True, p.name
        if ".aws" in posix_str.split("/") or ".ssh" in posix_str.split("/"):
            return True, p.name
    return False, ""


def _ensure_git_checkpoint(
    workspace: str,
    turn_num: int,
    touched_files: list[str] | set[str] | None = None,
) -> tuple[bool, str, str]:
    """Ensure workspace is a git repo, and create a pre-turn checkpoint commit rony-turn-{N}-pre.
    
    Returns (new_repo_initialized: bool, commit_hash: str, error_message: str).
    """
    if not workspace:
        return False, "", "No workspace provided"
    
    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return False, "", "Workspace directory does not exist"

    # Validation: Abort if agent touched any sensitive file
    if touched_files:
        for tf in touched_files:
            is_sens, matched_name = _is_sensitive_filename(str(tf))
            if is_sens:
                err_msg = f"Agent touched sensitive file: {matched_name}. Add it to .gitignore or exclude it from the workspace."
                logger.error("chat_harness: %s", err_msg)
                return False, "", err_msg

    new_repo_initialized = False

    # 1. Check if git repo
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if res.returncode != 0:
            init_res = subprocess.run(
                ["git", "init"],
                cwd=str(ws_path),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if init_res.returncode == 0:
                new_repo_initialized = True
                gitignore = ws_path / ".gitignore"
                if not gitignore.exists():
                    gitignore_content = (
                        ".venv/\n"
                        "__pycache__/\n"
                        "node_modules/\n"
                        "*.pyc\n"
                        ".DS_Store\n"
                        ".code_os/\n"
                        ".env\n"
                        ".env.*\n"
                        "*.pem\n"
                        "id_rsa\n"
                        "id_rsa.pub\n"
                        ".aws/\n"
                        ".ssh/\n"
                        "*.key\n"
                        "credentials.json\n"
                        "serviceAccountKey.json\n"
                        "*.sqlite\n"
                        "*.sqlite3\n"
                        "*.db\n"
                    )
                    gitignore.write_text(gitignore_content, encoding="utf-8")
    except Exception as exc:
        logger.warning("chat_harness: git repo check/init failed: %s", exc)
        return False, "", str(exc)

    # 2. Stage ONLY touched files (never git add -A) and create pre-turn checkpoint commit
    commit_hash = ""
    try:
        if touched_files:
            rel_paths = []
            for f in touched_files:
                p = Path(f)
                try:
                    rel = p.relative_to(ws_path)
                    rel_paths.append(str(rel).replace("\\", "/"))
                except ValueError:
                    rel_paths.append(str(f).replace("\\", "/"))
            
            if rel_paths:
                subprocess.run(
                    ["git", "add", "--"] + rel_paths,
                    cwd=str(ws_path),
                    capture_output=True,
                    text=True,
                    timeout=10.0,
                )

        commit_msg = f"rony-turn-{turn_num}-pre"
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", commit_msg],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        hash_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if hash_res.returncode == 0:
            commit_hash = hash_res.stdout.strip()
    except Exception as exc:
        logger.warning("chat_harness: git checkpoint commit failed: %s", exc)
        return new_repo_initialized, "", str(exc)

    return new_repo_initialized, commit_hash, ""


def undo_turn_files(workspace: str, commit_hash: str, touched_files: list[str]) -> tuple[bool, str, list[str]]:
    """Restores ONLY the agent-touched files from the pre-turn commit hash.
    
    Uses `git checkout <commit_hash> -- <paths>` — never a blanket reset --hard,
    never touching user files the agent didn't modify.
    """
    if not workspace or not commit_hash or not touched_files:
        return False, "Missing workspace, commit_hash, or touched_files", []
    
    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return False, f"Workspace not found: {workspace}", []

    rel_paths = []
    for f in touched_files:
        p = Path(f)
        try:
            rel = p.relative_to(ws_path)
            rel_paths.append(str(rel).replace("\\", "/"))
        except ValueError:
            rel_paths.append(f.replace("\\", "/"))

    if not rel_paths:
        return False, "No valid files to restore", []

    try:
        cmd = ["git", "checkout", commit_hash, "--"] + rel_paths
        res = subprocess.run(
            cmd,
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=15.0,
        )
        if res.returncode == 0:
            restored = []
            for rf in rel_paths:
                fp = ws_path / rf
                if fp.exists():
                    restored.append(rf)
            return True, f"Successfully restored {len(restored)} file(s) to checkpoint {commit_hash[:7]}", restored
        else:
            return False, f"Git checkout error: {res.stderr.strip()}", []
    except Exception as exc:
        return False, f"Undo operation failed: {exc}", []


async def approve_action(action_id: str, always_allow: bool = False, trust_pattern: str | None = None) -> bool:
    """Approve a pending action, optionally recording command trust for the workspace."""
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
