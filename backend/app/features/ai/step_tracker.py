from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

from app.db.database import get_db, get_pool

logger = logging.getLogger(__name__)


async def log_step_pending(
    task_id: str,
    job_id: str,
    step_num: int,
    step_type: str,
    payload: dict,
) -> str:
    """Log a step as pending BEFORE execution (write-ahead)."""
    step_id = f"step_{task_id}_{step_num}"
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    
    pool = await get_pool()
    now = time.time()
    await pool.write_execute(
        """
        INSERT OR REPLACE INTO task_steps
        (id, task_id, job_id, step_num, step_type, status, payload_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (step_id, task_id, job_id, step_num, step_type, payload_hash, now, now)
    )
    return step_id


async def mark_step_running(step_id: str) -> None:
    """Mark a step as running (called just before execution)."""
    pool = await get_pool()
    await pool.write_execute(
        "UPDATE task_steps SET status = 'running', updated_at = ? WHERE id = ?",
        (time.time(), step_id)
    )


async def mark_step_completed(step_id: str, result: Optional[dict] = None) -> None:
    """Mark a step as completed AFTER successful execution."""
    pool = await get_pool()
    await pool.write_execute(
        """
        UPDATE task_steps
        SET status = 'completed', result_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(result) if result is not None else None, time.time(), step_id)
    )


async def mark_step_failed(step_id: str, error: str) -> None:
    """Mark a step as failed."""
    pool = await get_pool()
    await pool.write_execute(
        "UPDATE task_steps SET status = 'failed', result_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps({"error": error}), time.time(), step_id)
    )


async def get_task_progress(task_id: str) -> dict:
    """Get the progress of a task (how many steps completed, failed, pending, running)."""
    pool = await get_pool()
    rows = await pool.read_query(
        "SELECT status, COUNT(*) as count FROM task_steps WHERE task_id = ? GROUP BY status",
        (task_id,)
    )
    progress = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for row in rows:
        st = row["status"]
        if st in progress:
            progress[st] = row["count"]
    return progress


async def get_last_completed_step(task_id: str) -> int:
    """Get the step number of the last completed step (for resume)."""
    pool = await get_pool()
    rows = await pool.read_query(
        "SELECT MAX(step_num) as last_step FROM task_steps WHERE task_id = ? AND status = 'completed'",
        (task_id,)
    )
    if rows and rows[0]["last_step"] is not None:
        return int(rows[0]["last_step"])
    return 0


async def recover_interrupted_tasks() -> list[str]:
    """On startup, find tasks with pending/running steps and mark as interrupted."""
    pool = await get_pool()
    
    now = time.time()
    # 1. Cancel orphan steps on already cancelled tasks
    await pool.write_execute(
        """
        UPDATE task_steps
        SET status = 'failed', result_json = '{"error": "Task was cancelled"}', updated_at = ?
        WHERE status IN ('pending', 'running')
          AND task_id IN (SELECT id FROM agent_tasks WHERE status = 'cancelled')
        """,
        (now,)
    )

    # 2. Find uncompleted active tasks with pending or running steps
    rows = await pool.read_query(
        """
        SELECT DISTINCT ts.task_id, ts.job_id
        FROM task_steps ts
        JOIN agent_tasks t ON ts.task_id = t.id
        WHERE ts.status IN ('pending', 'running')
          AND t.status NOT IN ('cancelled', 'completed', 'skipped')
        """
    )
    if not rows:
        return []

    interrupted_tasks = []
    for row in rows:
        task_id = row["task_id"]
        job_id = row["job_id"]
        
        # Mark the task as interrupted (not failed - user can resume)
        await pool.write_execute(
            "UPDATE agent_tasks SET status = 'interrupted' WHERE id = ? AND status NOT IN ('cancelled', 'completed')",
            (task_id,)
        )
        if job_id:
            await pool.write_execute(
                "UPDATE agent_jobs SET status = 'interrupted' WHERE id = ? AND status IN ('running', 'queued', 'pending')",
                (job_id,)
            )
        
        # Mark any 'running' steps as 'failed' (they didn't complete due to crash)
        await pool.write_execute(
            """
            UPDATE task_steps
            SET status = 'failed', result_json = '{"error": "Backend crashed mid-execution"}', updated_at = ?
            WHERE task_id = ? AND status = 'running'
            """,
            (now, task_id)
        )
        
        interrupted_tasks.append(task_id)
    
    logger.info("Recovered %d interrupted tasks: %s", len(interrupted_tasks), interrupted_tasks)
    return interrupted_tasks


async def get_interrupted_tasks() -> list[dict]:
    """Retrieve all currently interrupted tasks."""
    pool = await get_pool()
    rows = await pool.read_query(
        """
        SELECT t.id, t.job_id, t.title, t.agent_role, t.status, j.workspace
        FROM agent_tasks t
        LEFT JOIN agent_jobs j ON t.job_id = j.id
        WHERE t.status = 'interrupted'
        """
    )
    results = []
    for r in rows:
        last_step = await get_last_completed_step(r["id"])
        progress = await get_task_progress(r["id"])
        results.append({
            "task_id": r["id"],
            "job_id": r["job_id"],
            "title": r["title"],
            "agent_role": r["agent_role"],
            "status": r["status"],
            "workspace": r["workspace"] or "",
            "last_completed_step": last_step,
            "progress": progress,
        })
    return results


async def get_task_progress_by_role(job_id: str) -> dict[str, dict[str, int]]:
    """Get the progress of task steps grouped by agent role for a given job."""
    pool = await get_pool()
    rows = await pool.read_query(
        """
        SELECT COALESCE(t.agent_role, ts.step_type) as role, ts.status, COUNT(*) as count
        FROM task_steps ts
        LEFT JOIN agent_tasks t ON ts.task_id = t.id
        WHERE ts.job_id = ?
        GROUP BY role, ts.status
        """,
        (job_id,)
    )
    progress_by_role: dict[str, dict[str, int]] = {}
    for row in rows:
        raw_role = row["role"] or "unknown"
        role = raw_role[len("team_role_"):] if raw_role.startswith("team_role_") else raw_role
        if role not in progress_by_role:
            progress_by_role[role] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        st = row["status"]
        if st in progress_by_role[role]:
            progress_by_role[role][st] = int(row["count"])
    return progress_by_role


async def get_last_completed_step_by_role(job_id: str, agent_role: str) -> int:
    """Get the last completed step number for a specific agent role within a job."""
    pool = await get_pool()
    clean_role = agent_role.lower().strip()
    step_type_prefix = f"team_role_{clean_role}"
    rows = await pool.read_query(
        """
        SELECT MAX(ts.step_num) as last_step
        FROM task_steps ts
        LEFT JOIN agent_tasks t ON ts.task_id = t.id
        WHERE ts.job_id = ?
          AND (LOWER(COALESCE(t.agent_role, '')) = ? OR ts.step_type = ? OR ts.step_type = ?)
          AND ts.status = 'completed'
        """,
        (job_id, clean_role, clean_role, step_type_prefix)
    )
    if rows and rows[0]["last_step"] is not None:
        return int(rows[0]["last_step"])
    return 0
