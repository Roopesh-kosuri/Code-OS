from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task
from app.features.ai.step_tracker import recover_interrupted_tasks
from app.features.ai.team.roles import (
    ArchitectRole,
    CoderRole,
    ReviewerRole,
    TesterRole,
    DevOpsRole,
)
from app.features.ai.team.team_schemas import (
    HandoffArtifact,
    HandoffType,
    TeamConfig,
    TeamRole,
    TeamTask,
)
from app.features.ai.team.orchestrator import TeamOrchestrator


# ── Test 1: Architect Cannot Edit Files ───────────────────────────────────────

def test_architect_cannot_edit_files(tmp_path: Path):
    """Architect Role must be strictly read-only: no edit_file, run_command, or run_test."""
    architect = ArchitectRole()

    # 1. edit_file must be rejected
    allowed, reason = architect.validate_tool_permission("edit_file", {"path": "src/main.py"})
    assert not allowed
    assert "disallowed for role 'architect'" in reason

    with pytest.raises(PermissionError) as exc_info:
        architect.execute_tool(
            "edit_file",
            {"path": "src/main.py", "updated": "x = 1", "original": ""},
            workspace=str(tmp_path),
            raise_on_disallowed=True,
        )
    assert "Permission denied" in str(exc_info.value)

    # With raise_on_disallowed=False, returns failed ToolResult
    result = architect.execute_tool(
        "edit_file",
        {"path": "src/main.py", "updated": "x = 1", "original": ""},
        workspace=str(tmp_path),
        raise_on_disallowed=False,
    )
    assert not result.success
    assert "disallowed" in result.error

    # 2. run_command and run_test must also be rejected
    assert not architect.validate_tool_permission("run_command")[0]
    assert not architect.validate_tool_permission("run_test")[0]

    # 3. Read-only tools must be permitted
    assert architect.validate_tool_permission("read_file")[0]
    assert architect.validate_tool_permission("list_directory")[0]
    assert architect.validate_tool_permission("search_code")[0]


# ── Test 2: Coder Can Edit and Run Tests ─────────────────────────────────────

def test_coder_can_edit_and_run_tests(tmp_path: Path):
    """Coder Role can edit files and run targeted tests, but cannot run arbitrary commands."""
    coder = CoderRole()

    # 1. edit_file and run_test are permitted
    assert coder.validate_tool_permission("edit_file")[0]
    assert coder.validate_tool_permission("run_test")[0]
    assert coder.validate_tool_permission("read_file")[0]
    assert coder.validate_tool_permission("search_code")[0]
    assert coder.validate_tool_permission("list_directory")[0]

    # 2. Arbitrary run_command is disallowed for Coder
    allowed, reason = coder.validate_tool_permission("run_command", {"command": "rm -rf /"})
    assert not allowed
    assert "disallowed for role 'coder'" in reason

    # 3. Executing edit_file stages changes successfully
    staged = []
    res = coder.execute_tool(
        "edit_file",
        {"path": "src/calculator.py", "original": "", "updated": "def add(a, b): return a + b\n"},
        workspace=str(tmp_path),
        staged_changes=staged,
    )
    assert res.success
    assert len(staged) == 1
    assert staged[0].path == "src/calculator.py"
    assert "def add" in staged[0].updated


# ── Test 3: Reviewer Cannot Modify Code ──────────────────────────────────────

def test_reviewer_cannot_modify_code(tmp_path: Path):
    """Reviewer Role is strictly read-only with git audit capabilities; cannot edit code."""
    reviewer = ReviewerRole()

    # 1. edit_file is strictly disallowed
    allowed, reason = reviewer.validate_tool_permission("edit_file", {"path": "src/calculator.py"})
    assert not allowed
    assert "disallowed for role 'reviewer'" in reason

    with pytest.raises(PermissionError):
        reviewer.execute_tool(
            "edit_file",
            {"path": "src/calculator.py", "original": "", "updated": "print(1)"},
            workspace=str(tmp_path),
        )

    # 2. run_command is disallowed
    assert not reviewer.validate_tool_permission("run_command")[0]

    # 3. git_diff, git_log, read_file, and search_code are permitted
    assert reviewer.validate_tool_permission("git_diff")[0]
    assert reviewer.validate_tool_permission("git_log")[0]
    assert reviewer.validate_tool_permission("read_file")[0]
    assert reviewer.validate_tool_permission("search_code")[0]


# ── Test 4: DAG Dependency Resolution ────────────────────────────────────────

@pytest.mark.asyncio
async def test_dag_dependency_resolution(tmp_path: Path):
    """Independent tasks run in parallel; dependent task executes only after all dependencies complete."""
    start_times: dict[str, float] = {}
    end_times: dict[str, float] = {}
    handoffs_received: dict[str, list[HandoffArtifact]] = {}

    async def mock_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        start_times[task.task_id] = time.time()
        handoffs_received[task.task_id] = prior_handoffs
        await asyncio.sleep(0.08)  # Simulate non-trivial async work
        end_times[task.task_id] = time.time()
        return {
            "role": task.role.value,
            "status": "completed",
            "reasoning": f"Work completed for {task.task_id}",
            "proposals": [{"path": "src/foo.py"}] if task.role == TeamRole.CODER else [],
        }

    config = TeamConfig(workspace=str(tmp_path), max_concurrency=4)
    orchestrator = TeamOrchestrator(team_config=config, task_executor=mock_executor)

    tasks = [
        TeamTask(
            task_id="task_coder",
            job_id="job_dag_1",
            title="Implement Core Logic",
            role=TeamRole.CODER,
            dependencies=[],
        ),
        TeamTask(
            task_id="task_tester",
            job_id="job_dag_1",
            title="Prepare Test Harness",
            role=TeamRole.TESTER,
            dependencies=[],
        ),
        TeamTask(
            task_id="task_reviewer",
            job_id="job_dag_1",
            title="Audit Changes and Test Results",
            role=TeamRole.REVIEWER,
            dependencies=["task_coder", "task_tester"],
        ),
    ]

    result = await orchestrator.execute_dag(tasks, job_id="job_dag_1")

    assert result["status"] == "completed"
    assert result["completed_count"] == 3
    assert result["failed_count"] == 0

    # Task 1 (Coder) and Task 2 (Tester) started near-simultaneously in parallel
    time_diff_parallel = abs(start_times["task_coder"] - start_times["task_tester"])
    assert time_diff_parallel < 0.05, f"Independent tasks did not start concurrently: diff={time_diff_parallel}"

    # Task 3 (Reviewer) started ONLY AFTER both Coder and Tester finished
    assert start_times["task_reviewer"] >= end_times["task_coder"]
    assert start_times["task_reviewer"] >= end_times["task_tester"]

    # Reviewer received handoffs from both completed dependencies
    rev_handoffs = handoffs_received["task_reviewer"]
    assert len(rev_handoffs) == 2
    from_roles = {h.from_role for h in rev_handoffs}
    assert TeamRole.CODER in from_roles
    assert TeamRole.TESTER in from_roles


# ── Test 5: Step Tracker Durability ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_step_tracker_durability(tmp_path: Path):
    """Crash mid-execution durably records failed step state in task_steps table."""
    db_file = tmp_path / "test_durability.sqlite3"
    await init_db(db_file)
    pool = await get_pool()

    # Insert workspace and test job
    ws_path = str(tmp_path)
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))
    job_id = "job_crash_test"
    task_id = "task_crash_coder"
    await create_job(job_id, ws_path, "team_mode")
    await create_task(task_id, job_id, "Crash Task", "Coder Agent", dependencies=[])

    async def crashing_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        # Simulate an unexpected process fault or exception mid-execution
        raise RuntimeError("Fatal unhandled exception inside agent execution")

    config = TeamConfig(workspace=ws_path, max_concurrency=2)
    orchestrator = TeamOrchestrator(team_config=config, task_executor=crashing_executor)

    tasks = [
        TeamTask(
            task_id=task_id,
            job_id=job_id,
            title="Crash Task",
            role=TeamRole.CODER,
            dependencies=[],
        ),
    ]

    result = await orchestrator.execute_dag(tasks, job_id=job_id)
    assert result["status"] == "failed"
    assert task_id in orchestrator.failed_task_ids

    # Verify durability directly in task_steps database table
    step_id = f"step_{task_id}_1"
    rows = await pool.read_query(
        "SELECT id, task_id, status, step_type, result_json FROM task_steps WHERE id = ?",
        (step_id,),
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["task_id"] == task_id
    assert rows[0]["step_type"] == "team_role_coder"
    error_payload = json.loads(rows[0]["result_json"])
    assert "Fatal unhandled exception" in error_payload["error"]

    await close_db()


# ── Test 6: Concurrency Bounded ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrency_bounded(tmp_path: Path):
    """Semaphore strictly caps the number of active tasks at team_config.max_concurrency."""
    max_concurrency_limit = 2
    active_now = 0
    max_seen_active = 0
    lock = asyncio.Lock()

    async def sleep_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        nonlocal active_now, max_seen_active
        async with lock:
            active_now += 1
            if active_now > max_seen_active:
                max_seen_active = active_now

        await asyncio.sleep(0.06)

        async with lock:
            active_now -= 1

        return {"role": task.role.value, "status": "completed"}

    config = TeamConfig(workspace=str(tmp_path), max_concurrency=max_concurrency_limit)
    orchestrator = TeamOrchestrator(team_config=config, task_executor=sleep_executor)

    # Submit 5 parallel independent tasks
    tasks = [
        TeamTask(
            task_id=f"concurrent_task_{i}",
            job_id="job_concurrency",
            title=f"Task {i}",
            role=TeamRole.CODER,
            dependencies=[],
        )
        for i in range(5)
    ]

    result = await orchestrator.execute_dag(tasks, job_id="job_concurrency")

    assert result["status"] == "completed"
    assert result["completed_count"] == 5
    assert max_seen_active <= max_concurrency_limit
    assert max_seen_active == max_concurrency_limit
    assert orchestrator.peak_concurrency <= max_concurrency_limit
