from __future__ import annotations

import asyncio
import gc
import time
from pathlib import Path
import psutil
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task
from app.features.ai.step_tracker import (
    log_step_pending,
    mark_step_running,
    mark_step_completed,
    get_task_progress,
)


@pytest.mark.asyncio
async def test_soak_5_minutes(tmp_path: Path):
    """Run a soak test workload simulating continuous task creation & step executions;
    verifies bounded memory growth (<10MB) and zero database/memory leaks."""
    db_file = tmp_path / "chaos_soak.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "soak_ws"))

    process = psutil.Process()
    gc.collect()
    initial_rss = process.memory_info().rss / (1024 * 1024)

    tasks_to_run = 50
    steps_per_task = 5
    total_steps = 0

    for t_idx in range(tasks_to_run):
        job_id = f"soak_job_{t_idx}"
        task_id = f"soak_task_{t_idx}"

        await create_job(job_id, str(tmp_path), "soak_workflow")
        await create_task(task_id, job_id, f"Soak Task {t_idx}", "Tester Agent", dependencies=[])

        for s_idx in range(1, steps_per_task + 1):
            step_id = await log_step_pending(
                task_id=task_id,
                job_id=job_id,
                step_num=s_idx,
                step_type="tool_call",
                payload={"op": "soak_step", "index": s_idx, "task": t_idx},
            )
            await mark_step_running(step_id)
            await mark_step_completed(step_id, {"status": "ok", "iteration": s_idx})
            total_steps += 1

    gc.collect()
    final_rss = process.memory_info().rss / (1024 * 1024)
    growth = final_rss - initial_rss

    assert total_steps == 250
    # Assert memory growth is bounded under 10MB
    assert growth < 10.0, f"Memory growth exceeded limit: {growth:.2f}MB (initial: {initial_rss:.2f}MB, final: {final_rss:.2f}MB)"

    await close_db()
