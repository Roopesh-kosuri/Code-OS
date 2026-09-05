from __future__ import annotations

from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task
from app.features.ai.harness.tool_executor import execute_tool_idempotent, ToolResult


@pytest.mark.asyncio
async def test_step_hash_collision(tmp_path: Path):
    """Create two tasks with identical tool payloads; verify separate step_ids
    and verify idempotency caching is strictly scoped per-task (no cross-task pollution)."""
    db_file = tmp_path / "chaos_collision.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "collision_ws"))

    job_id = "job_collision_test"
    task_id_a = "task_collision_A"
    task_id_b = "task_collision_B"
    await create_job(job_id, str(tmp_path), "test_flow")
    await create_task(task_id_a, job_id, "Task A", "Coder Agent", dependencies=[])
    await create_task(task_id_b, job_id, "Task B", "Coder Agent", dependencies=[])

    execution_calls_a = 0
    execution_calls_b = 0

    async def mock_exec_a(name: str, args: dict):
        nonlocal execution_calls_a
        execution_calls_a += 1
        return ToolResult(success=True, output=f"Task A Result: {args.get('code')}")

    async def mock_exec_b(name: str, args: dict):
        nonlocal execution_calls_b
        execution_calls_b += 1
        return ToolResult(success=True, output=f"Task B Result: {args.get('code')}")

    identical_payload = {"code": "print('hello world')", "mode": "eval"}

    # 1. Execute step 1 for Task A
    res_a1 = await execute_tool_idempotent(
        task_id=task_id_a,
        job_id=job_id,
        step_num=1,
        tool_name="eval_code",
        tool_args=identical_payload,
        executor_fn=mock_exec_a,
    )
    assert res_a1.output == "Task A Result: print('hello world')"
    assert execution_calls_a == 1

    # 2. Execute step 1 for Task B with identical tool_name and payload
    # Task B MUST NOT reuse Task A's cached result!
    res_b1 = await execute_tool_idempotent(
        task_id=task_id_b,
        job_id=job_id,
        step_num=1,
        tool_name="eval_code",
        tool_args=identical_payload,
        executor_fn=mock_exec_b,
    )
    assert res_b1.output == "Task B Result: print('hello world')"
    assert execution_calls_b == 1

    # 3. Verify step_ids in database are distinct
    rows = await pool.read_query("SELECT id, task_id FROM task_steps ORDER BY task_id")
    assert len(rows) == 2
    assert rows[0]["id"] == f"step_{task_id_a}_1"
    assert rows[1]["id"] == f"step_{task_id_b}_1"
    assert rows[0]["id"] != rows[1]["id"]

    # 4. Verify re-executing Task A step 1 is properly cached for Task A
    res_a2 = await execute_tool_idempotent(
        task_id=task_id_a,
        job_id=job_id,
        step_num=1,
        tool_name="eval_code",
        tool_args=identical_payload,
        executor_fn=mock_exec_a,
    )
    assert res_a2.output == "Task A Result: print('hello world')"
    assert execution_calls_a == 1  # Still 1, cached

    await close_db()
