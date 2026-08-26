"""
activity_logger.py - Searchable agent activity timeline and interrupted state persistence.

Provides:
- Append structured JSONL events with rotation
- Fast backward seeking for tail pagination and filtering
- Interrupted state saving and resumption
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_ACTIVITY_LOG_FILES = 3


def _rotate_activity_log(log_path: Path | str, max_size_mb: float = 2.0, max_files: int = 3) -> None:
    """Rotate activity log when size exceeds max_size_mb."""
    p = Path(log_path)
    if p.is_dir():
        p = p / ".code_os" / "activity_log.jsonl"
    elif p.name != "activity_log.jsonl" and not p.suffix:
        p = p / ".code_os" / "activity_log.jsonl"

    if not p.is_file():
        return

    try:
        if p.stat().st_size > max_size_mb * 1024 * 1024:
            for i in range(max_files - 1, 0, -1):
                old = p.parent / f"activity_log.{i}.jsonl"
                new = p.parent / f"activity_log.{i+1}.jsonl"
                if old.exists():
                    if i == max_files - 1:
                        try:
                            old.unlink()
                        except Exception:
                            pass
                    else:
                        try:
                            if new.exists():
                                new.unlink()
                            old.rename(new)
                        except Exception:
                            pass
            try:
                target_1 = p.parent / "activity_log.1.jsonl"
                if target_1.exists():
                    target_1.unlink()
                p.rename(target_1)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("activity_logger: error rotating activity log: %s", exc)


def _append_activity_log(workspace: str, entry: dict[str, Any]) -> None:
    """Append a structured JSONL entry to <workspace>/.code_os/activity_log.jsonl with automatic log rotation."""
    if not workspace:
        return
    try:
        os_dir = Path(workspace) / ".code_os"
        os_dir.mkdir(parents=True, exist_ok=True)
        p = os_dir / "activity_log.jsonl"

        _rotate_activity_log(p, max_size_mb=10, max_files=MAX_ACTIVITY_LOG_FILES)

        entry.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        entry.setdefault("action_type", "general")
        entry.setdefault("target", "")
        entry.setdefault("outcome", "success")
        entry.setdefault("token_count", 0)
        entry.setdefault("tier", 1)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("activity_logger: failed to append to activity log: %s", exc)


def _load_activity_log_tail(
    log_path: Path,
    limit: int = 100,
    offset: int = 0,
    search: str = "",
    filter_type: str = "all",
) -> tuple[list[dict[str, Any]], int, bool]:
    """Read activity log from end with backward seeking, supporting offset, limit, search, and filtering."""
    if not log_path.is_file():
        return [], 0, False

    search_lower = search.lower().strip()
    entries: list[dict[str, Any]] = []
    total_matched = 0
    skipped = 0

    try:
        with log_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            block_size = 8192
            buffer = b""
            position = file_size

            while position > 0:
                read_size = min(block_size, position)
                position -= read_size
                f.seek(position, os.SEEK_SET)
                buffer = f.read(read_size) + buffer

                lines = buffer.split(b"\n")
                buffer = lines[0]

                for raw_line in reversed(lines[1:]):
                    line_str = raw_line.strip().decode("utf-8", errors="replace")
                    if not line_str:
                        continue
                    try:
                        e = json.loads(line_str)
                    except Exception:
                        continue

                    act_type = str(e.get("action_type", "")).lower()
                    outcome = str(e.get("outcome", "")).lower()
                    target = str(e.get("target", "")).lower()
                    details = str(e.get("details", "")).lower()

                    if filter_type == "edits" and act_type not in ("edit_proposal", "edit_file", "append_file", "undo_turn"):
                        continue
                    if filter_type == "commands" and act_type not in ("command_run", "run_command", "run_test", "security_policy_blocked"):
                        continue
                    if filter_type == "failures" and outcome not in ("failed", "rejected", "error", "regression_detected", "timed_out", "blocked"):
                        continue

                    if search_lower:
                        combined = f"{act_type} {outcome} {target} {details}"
                        if search_lower not in combined:
                            continue

                    total_matched += 1

                    if skipped < offset:
                        skipped += 1
                        continue

                    if len(entries) < limit:
                        entries.append(e)

            if buffer.strip():
                try:
                    e = json.loads(buffer.strip().decode("utf-8", errors="replace"))
                    act_type = str(e.get("action_type", "")).lower()
                    outcome = str(e.get("outcome", "")).lower()
                    target = str(e.get("target", "")).lower()
                    details = str(e.get("details", "")).lower()
                    match = True
                    if filter_type == "edits" and act_type not in ("edit_proposal", "edit_file", "append_file", "undo_turn"):
                        match = False
                    elif filter_type == "commands" and act_type not in ("command_run", "run_command", "run_test", "security_policy_blocked"):
                        match = False
                    elif filter_type == "failures" and outcome not in ("failed", "rejected", "error", "regression_detected", "timed_out", "blocked"):
                        match = False
                    if match and search_lower:
                        combined = f"{act_type} {outcome} {target} {details}"
                        if search_lower not in combined:
                            match = False
                    if match:
                        total_matched += 1
                        if skipped < offset:
                            skipped += 1
                        elif len(entries) < limit:
                            entries.append(e)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("activity_logger: failed reading activity log tail: %s", exc)

    has_more = (offset + len(entries)) < total_matched
    return entries, total_matched, has_more


def _load_activity_log(
    workspace: str,
    search: str = "",
    filter_type: str = "all",
    limit: int = 100,
    offset: int = 0,
    return_metadata: bool = False,
):
    """Load and filter entries from <workspace>/.code_os/activity_log.jsonl in reverse chronological order."""
    if not workspace:
        return {"entries": [], "total": 0, "has_more": False} if return_metadata else []
    p = Path(workspace) / ".code_os" / "activity_log.jsonl"
    if not p.is_file():
        return {"entries": [], "total": 0, "has_more": False} if return_metadata else []

    limit = min(max(1, limit), 1000)
    offset = max(0, offset)
    entries, total, has_more = _load_activity_log_tail(p, limit=limit, offset=offset, search=search, filter_type=filter_type)

    if return_metadata:
        return {"entries": entries, "total": total, "has_more": has_more}
    return entries


def _get_interrupted_state_path(workspace: str) -> Path:
    base = Path(workspace) if workspace else Path.cwd()
    os_dir = base / ".code_os"
    os_dir.mkdir(parents=True, exist_ok=True)
    return os_dir / "agent_state.json"


def _save_interrupted_state(
    workspace: str,
    user_query: str,
    tier: int,
    iteration: int,
    max_iterations: int,
    messages: list[Any],
    dag_plan_steps: list[Any] | None,
    staged_changes: list[Any],
    tokens_used: int,
    tools_executed: int,
) -> bool:
    """Persist loop state to <workspace>/.code_os/agent_state.json on every iteration."""
    if not workspace:
        return False
    try:
        p = _get_interrupted_state_path(workspace)
        state = {
            "user_query": user_query,
            "tier": tier,
            "iteration": iteration,
            "max_iterations": max_iterations,
            "messages": [{"role": getattr(m, "role", ""), "content": getattr(m, "content", "")} for m in messages],
            "dag_plan_steps": [s.to_dict() if hasattr(s, "to_dict") else s for s in dag_plan_steps] if dag_plan_steps else [],
            "staged_changes": [
                {"path": getattr(c, "path", ""), "original": getattr(c, "original", ""), "updated": getattr(c, "updated", "")}
                for c in staged_changes
            ],
            "tokens_used": tokens_used,
            "tools_executed": tools_executed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("activity_logger: failed to save interrupted state: %s", exc)
        return False


def _load_interrupted_state(workspace: str) -> dict[str, Any] | None:
    """Load interrupted state from <workspace>/.code_os/agent_state.json if available."""
    if not workspace:
        return None
    try:
        p = _get_interrupted_state_path(workspace)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("user_query"):
                return data
    except Exception as exc:
        logger.warning("activity_logger: failed to load interrupted state: %s", exc)
    return None


def _clear_interrupted_state(workspace: str) -> bool:
    """Remove interrupted state on successful completion."""
    if not workspace:
        return False
    try:
        p = _get_interrupted_state_path(workspace)
        if p.is_file():
            p.unlink()
            return True
    except Exception as exc:
        logger.warning("activity_logger: failed to clear interrupted state: %s", exc)
    return False


class ActivityLogger:
    """Class wrapper providing unified activity logging and replay capabilities."""

    @staticmethod
    def append(workspace: str, entry: dict[str, Any]) -> None:
        _append_activity_log(workspace, entry)

    @staticmethod
    def load(workspace: str, **kwargs: Any):
        return _load_activity_log(workspace, **kwargs)

    @staticmethod
    def save_state(workspace: str, **kwargs: Any) -> bool:
        return _save_interrupted_state(workspace, **kwargs)

    @staticmethod
    def load_state(workspace: str) -> dict[str, Any] | None:
        return _load_interrupted_state(workspace)

    @staticmethod
    def clear_state(workspace: str) -> bool:
        return _clear_interrupted_state(workspace)