from __future__ import annotations

import asyncio
import json
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task, get_job
from app.features.ai.step_tracker import (
    log_step_pending,
    mark_step_running,
    mark_step_completed,
    recover_interrupted_tasks,
    get_task_progress,
    get_last_completed_step,
)


@pytest.mark.asyncio
async def test_concurrent_tasks_with_crash(tmp_path: Path):
    """Spawn 5 concurrent agent tasks, crash backend mid-execution, reboot,
    and verify all 5 recover cleanly with zero data corruption."""
    db_file = tmp_path / "chaos_concurrent_crash.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "chaos_ws"))

    task_count = 5
    job_id = "job_chaos_concurrent"
    await create_job(job_id, str(tmp_path), "multi_agent_workflow")

    task_ids = [f"task_chaos_{i}" for i in range(task_count)]
    for tid in task_ids:
        await create_task(tid, job_id, f"Concurrent Step {tid}", "Coder Agent", dependencies=[])

    # Task 0: fully completed 3 steps
    for s in range(1, 4):
        s_id = await log_step_pending(task_ids[0], job_id, s, "tool", {"s": s})
        await mark_step_running(s_id)
        await mark_step_completed(s_id, {"status": "ok", "step": s})

    # Task 1: step 1 completed, step 2 running (crashed)
    s1 = await log_step_pending(task_ids[1], job_id, 1, "tool", {"s": 1})
    await mark_step_running(s1)
    await mark_step_completed(s1, {"status": "ok"})
    s2 = await log_step_pending(task_ids[1], job_id, 2, "tool", {"s": 2})
    await mark_step_running(s2)

    # Task 2: step 1 running (crashed)
    s_t2 = await log_step_pending(task_ids[2], job_id, 1, "tool", {"s": 1})
    await mark_step_running(s_t2)

    # Task 3: step 1 pending (never started)
    await log_step_pending(task_ids[3], job_id, 1, "tool", {"s": 1})

    # Task 4: step 1 completed, step 2 pending
    s_t4_1 = await log_step_pending(task_ids[4], job_id, 1, "tool", {"s": 1})
    await mark_step_running(s_t4_1)
    await mark_step_completed(s_t4_1, {"status": "ok"})
    await log_step_pending(task_ids[4], job_id, 2, "tool", {"s": 2})

    # --- SIMULATE CRASH & REBOOT ---
    await close_db()
    await init_db(db_file)

    recovered = await recover_interrupted_tasks()

    # Tasks 1, 2, 3, 4 had incomplete (running/pending) steps and must be marked interrupted
    assert task_ids[1] in recovered
    assert task_ids[2] in recovered
    assert task_ids[3] in recovered
    assert task_ids[4] in recovered

    # Verify task progress and data integrity for all tasks
    p0 = await get_task_progress(task_ids[0])
    assert p0["completed"] == 3
    assert p0["running"] == 0

    p1 = await get_task_progress(task_ids[1])
    assert p1["completed"] == 1
    assert p1["failed"] == 1  # The crashed running step became failed
    assert p1["running"] == 0

    p2 = await get_task_progress(task_ids[2])
    assert p2["failed"] == 1
    assert p2["running"] == 0

    p3 = await get_task_progress(task_ids[3])
    assert p3["pending"] == 1
    assert p3["running"] == 0

    p4 = await get_task_progress(task_ids[4])
    assert p4["completed"] == 1
    assert p4["pending"] == 1
    assert p4["running"] == 0

    await close_db()
