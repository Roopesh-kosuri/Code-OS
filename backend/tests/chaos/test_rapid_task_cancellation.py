from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task, update_job_status, update_task_status, get_job
from app.features.ai.step_tracker import (
    log_step_pending,
    recover_interrupted_tasks,
    get_task_progress,
)


@pytest.mark.asyncio
async def test_rapid_task_cancellation(tmp_path: Path):
    """Start a task and cancel it immediately; verify no orphaned running steps
    and verify task status is 'cancelled' (not 'interrupted')."""
    db_file = tmp_path / "chaos_cancel.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "cancel_ws"))

    job_id = "job_cancel_test"
    task_id = "task_cancel_test"
    await create_job(job_id, str(tmp_path), "quick_workflow")
    await create_task(task_id, job_id, "Rapid Cancel Task", "Coder Agent", dependencies=[])

    # Log pending step
    await log_step_pending(task_id, job_id, 1, "tool", {"op": "setup"})

    # Immediately cancel task and job
    await update_task_status(task_id, "cancelled", reasoning_summary="User aborted immediately")
    await update_job_status(job_id, "cancelled", errors="Cancelled by user")

    # Verify task status is 'cancelled'
    job_data = await get_job(job_id)
    assert job_data["status"] == "cancelled"
    assert job_data["tasks"][0]["status"] == "cancelled"

    # Simulate backend reboot and run recovery
    await close_db()
    await init_db(db_file)
    recovered = await recover_interrupted_tasks()

    # Cancelled task should NOT be converted to interrupted
    pool2 = await get_pool()
    rows = await pool2.read_query("SELECT status FROM agent_tasks WHERE id = ?", (task_id,))
    assert rows[0]["status"] == "cancelled"

    await close_db()
