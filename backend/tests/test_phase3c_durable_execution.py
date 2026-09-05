from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task, get_job
from app.features.ai.step_tracker import (
    log_step_pending,
    mark_step_running,
    mark_step_completed,
    mark_step_failed,
    get_task_progress,
    get_last_completed_step,
    recover_interrupted_tasks,
    get_interrupted_tasks,
)
from app.features.ai.harness.tool_executor import (
    ToolResult,
    execute_tool_idempotent,
)


@pytest.mark.asyncio
async def test_step_logging_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_lifecycle.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_life_1"
    task_id = "task_life_1"
    await create_job(job_id, str(tmp_path), "test_workflow")
    await create_task(task_id, job_id, "Test Lifecycle", "Coder Agent", dependencies=[])

    # 1. Log pending
    payload = {"tool": "read_file", "args": {"path": "main.py"}}
    step_id = await log_step_pending(task_id, job_id, 1, "tool_call", payload)
    assert step_id == f"step_{task_id}_1"

    rows = await pool.read_query("SELECT status, payload_hash FROM task_steps WHERE id = ?", (step_id,))
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["payload_hash"] is not None

    # 2. Mark running
    await mark_step_running(step_id)
    rows = await pool.read_query("SELECT status FROM task_steps WHERE id = ?", (step_id,))
    assert rows[0]["status"] == "running"

    # 3. Mark completed
    result_data = {"output": "File content loaded", "bytes": 42}
    await mark_step_completed(step_id, result_data)
    rows = await pool.read_query("SELECT status, result_json FROM task_steps WHERE id = ?", (step_id,))
    assert rows[0]["status"] == "completed"
    loaded = json.loads(rows[0]["result_json"])
    assert loaded["output"] == "File content loaded"

    last_step = await get_last_completed_step(task_id)
    assert last_step == 1

    await close_db()


@pytest.mark.asyncio
async def test_step_failure_recording(tmp_path: Path):
    db_file = tmp_path / "test_failure.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_fail_1"
    task_id = "task_fail_1"
    await create_job(job_id, str(tmp_path), "test_workflow")
    await create_task(task_id, job_id, "Test Failure", "Coder Agent", dependencies=[])

    step_id = await log_step_pending(task_id, job_id, 1, "tool_call", {"tool": "exec"})
    await mark_step_running(step_id)
    await mark_step_failed(step_id, "Command returned non-zero exit code: 127")

    rows = await pool.read_query("SELECT status, result_json FROM task_steps WHERE id = ?", (step_id,))
    assert rows[0]["status"] == "failed"
    loaded = json.loads(rows[0]["result_json"])
    assert "127" in loaded["error"]

    await close_db()


@pytest.mark.asyncio
async def test_task_progress_tracking(tmp_path: Path):
    db_file = tmp_path / "test_progress.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_prog_1"
    task_id = "task_prog_1"
    await create_job(job_id, str(tmp_path), "test_workflow")
    await create_task(task_id, job_id, "Test Progress", "Coder Agent", dependencies=[])

    # 3 completed
    for i in range(1, 4):
        s_id = await log_step_pending(task_id, job_id, i, "tool_call", {"step": i})
        await mark_step_completed(s_id, {"done": True})

    # 1 failed
    s_fail = await log_step_pending(task_id, job_id, 4, "tool_call", {"step": 4})
    await mark_step_failed(s_fail, "Syntax error")

    # 1 pending
    await log_step_pending(task_id, job_id, 5, "tool_call", {"step": 5})

    progress = await get_task_progress(task_id)
    assert progress["completed"] == 3
    assert progress["failed"] == 1
    assert progress["pending"] == 1
    assert progress["running"] == 0

    assert await get_last_completed_step(task_id) == 3

    await close_db()


@pytest.mark.asyncio
async def test_recover_interrupted_tasks(tmp_path: Path):
    db_file = tmp_path / "test_recover.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_rec_1"
    task_id = "task_rec_1"
    await create_job(job_id, str(tmp_path), "test_workflow")
    await create_task(task_id, job_id, "Crash Recovery Task", "Coder Agent", dependencies=[])

    # Add 1 completed step and 1 running step (which crashed)
    s1 = await log_step_pending(task_id, job_id, 1, "tool_call", {"op": "init"})
    await mark_step_completed(s1, {"status": "ok"})

    s2 = await log_step_pending(task_id, job_id, 2, "tool_call", {"op": "heavy_compute"})
    await mark_step_running(s2)

    # Run recovery (simulating backend reboot)
    recovered = await recover_interrupted_tasks()
    assert task_id in recovered

    # Check task status transitioned to 'interrupted'
    rows = await pool.read_query("SELECT status FROM agent_tasks WHERE id = ?", (task_id,))
    assert rows[0]["status"] == "interrupted"

    interrupted_list = await get_interrupted_tasks()
    assert any(item["task_id"] == task_id for item in interrupted_list)

    await close_db()


@pytest.mark.asyncio
async def test_running_steps_marked_failed(tmp_path: Path):
    db_file = tmp_path / "test_running_failed.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_run_fail_1"
    task_id = "task_run_fail_1"
    await create_job(job_id, str(tmp_path), "test_workflow")
    await create_task(task_id, job_id, "Crash Test", "Coder Agent", dependencies=[])

    s_run = await log_step_pending(task_id, job_id, 1, "tool_call", {"action": "write"})
    await mark_step_running(s_run)

    # Perform crash recovery
    await recover_interrupted_tasks()

    # Step should be marked failed with crash message
    rows = await pool.read_query("SELECT status, result_json FROM task_steps WHERE id = ?", (s_run,))
    assert rows[0]["status"] == "failed"
    loaded = json.loads(rows[0]["result_json"])
    assert "Backend crashed mid-execution" in loaded["error"]

    await close_db()


@pytest.mark.asyncio
async def test_idempotent_execution(tmp_path: Path):
    db_file = tmp_path / "test_idempotent.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_idem_1"
    task_id = "task_idem_1"
    await create_job(job_id, str(tmp_path), "test_workflow")
    await create_task(task_id, job_id, "Idempotent Task", "Coder Agent", dependencies=[])

    execution_count = 0

    async def mock_tool(name: str, args: dict):
        nonlocal execution_count
        execution_count += 1
        return ToolResult(success=True, output=f"Processed {args.get('val')}")

    # 1. Execute step 1
    res1 = await execute_tool_idempotent(
        task_id=task_id,
        job_id=job_id,
        step_num=1,
        tool_name="process_data",
        tool_args={"val": 100},
        executor_fn=mock_tool
    )
    assert res1.success is True
    assert execution_count == 1
    assert res1.output == "Processed 100"

    # 2. Simulate resume/re-execution of step 1 with same payload
    res2 = await execute_tool_idempotent(
        task_id=task_id,
        job_id=job_id,
        step_num=1,
        tool_name="process_data",
        tool_args={"val": 100},
        executor_fn=mock_tool
    )
    assert res2.success is True
    assert execution_count == 1  # Not executed again! Cached result returned!
    assert res2.output == "Processed 100"

    await close_db()


@pytest.mark.asyncio
async def test_different_payload_re_executes(tmp_path: Path):
    db_file = tmp_path / "test_diff_payload.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_diff_1"
    task_id = "task_diff_1"
    await create_job(job_id, str(tmp_path), "test_workflow")
    await create_task(task_id, job_id, "Diff Payload Task", "Coder Agent", dependencies=[])

    execution_count = 0

    async def mock_tool(name: str, args: dict):
        nonlocal execution_count
        execution_count += 1
        return ToolResult(success=True, output=f"Output {args.get('num')}")

    # Execute step 1 with num=1
    await execute_tool_idempotent(task_id, job_id, 1, "tool_calc", {"num": 1}, executor_fn=mock_tool)
    assert execution_count == 1

    # Execute step 2 with different payload num=2
    await execute_tool_idempotent(task_id, job_id, 2, "tool_calc", {"num": 2}, executor_fn=mock_tool)
    assert execution_count == 2

    await close_db()


@pytest.mark.asyncio
async def test_chaos_mid_step_crash(tmp_path: Path):
    """Chaos test: Simulates a hard crash while executing step 2 of a 3-step pipeline,
    recovers cleanly, and resumes to completion without re-running step 1."""
    db_file = tmp_path / "test_chaos.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))

    job_id = "job_chaos_1"
    task_id = "task_chaos_1"
    await create_job(job_id, str(tmp_path), "pipeline")
    await create_task(task_id, job_id, "Pipeline Task", "Coder Agent", dependencies=[])

    step1_executed = 0
    step2_executed = 0
    step3_executed = 0

    # 1. Step 1 completes
    await execute_tool_idempotent(
        task_id, job_id, 1, "step_1", {"data": "A"},
        executor_fn=lambda n, a: ToolResult(success=True, output="Step 1 Done")
    )

    # 2. Step 2 starts and crashes mid-execution (simulated by logging pending & running, but no completion)
    s2 = await log_step_pending(task_id, job_id, 2, "tool_call", {"tool": "step_2", "args": {"data": "B"}})
    await mark_step_running(s2)

    # --- SIMULATE CRASH & REBOOT ---
    await close_db()
    await init_db(db_file)

    # Startup recovery runs
    recovered = await recover_interrupted_tasks()
    assert task_id in recovered

    # Verify task state is interrupted and step 1 is recorded as last completed
    last_step = await get_last_completed_step(task_id)
    assert last_step == 1

    # --- RESUME EXECUTION ---
    # Step 1 should be cached and not re-executed
    def mock_step1(n, a):
        nonlocal step1_executed
        step1_executed += 1
        return ToolResult(success=True, output="Step 1 Rerun")

    res1 = await execute_tool_idempotent(task_id, job_id, 1, "step_1", {"data": "A"}, executor_fn=mock_step1)
    assert res1.output == "Step 1 Done"
    assert step1_executed == 0  # Re-execution skipped!

    # Step 2 re-runs and succeeds
    res2 = await execute_tool_idempotent(
        task_id, job_id, 2, "step_2", {"data": "B"},
        executor_fn=lambda n, a: ToolResult(success=True, output="Step 2 Done")
    )
    assert res2.output == "Step 2 Done"

    # Step 3 runs
    res3 = await execute_tool_idempotent(
        task_id, job_id, 3, "step_3", {"data": "C"},
        executor_fn=lambda n, a: ToolResult(success=True, output="Step 3 Done")
    )
    assert res3.output == "Step 3 Done"

    progress = await get_task_progress(task_id)
    assert progress["completed"] == 3
    assert progress["running"] == 0

    await close_db()
