from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task, get_job, resume_job
from app.features.ai.harness.tool_executor import execute_tool_idempotent, ToolResult


@pytest.mark.asyncio
async def test_disk_full_handling(tmp_path: Path):
    """Simulate disk full error during tool write, verify graceful pause and recovery."""
    db_file = tmp_path / "chaos_disk_full.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "disk_ws"))

    job_id = "job_disk_test"
    task_id = "task_disk_test"
    await create_job(job_id, str(tmp_path), "write_flow")
    await create_task(task_id, job_id, "Write Large File", "Coder Agent", dependencies=[])

    async def mock_disk_full_writer(name: str, args: dict):
        raise OSError(28, "No space left on device: /workspace/big_data.bin")

    # Execute step 1 which throws disk full
    with pytest.raises(OSError) as excinfo:
        await execute_tool_idempotent(
            task_id=task_id,
            job_id=job_id,
            step_num=1,
            tool_name="write_file",
            tool_args={"path": "big_data.bin"},
            executor_fn=mock_disk_full_writer,
        )
    assert "No space left on device" in str(excinfo.value)

    # Verify task and job status transitioned to paused
    job_data = await get_job(job_id)
    assert job_data["status"] == "paused"
    assert "Disk full" in job_data["pause_reason"]

    # Verify resumption once space is cleared
    resumed = await resume_job(job_id)
    assert resumed is True
    job_resumed = await get_job(job_id)
    assert job_resumed["status"] == "running"

    await close_db()
