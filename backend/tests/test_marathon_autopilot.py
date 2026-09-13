"""
Phase 8 — Marathon Autopilot: backend test suite.
All tests are pure unit / integration with mocks; no live server required.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path: Path) -> str:
    """Create a temporary workspace with a .code_os directory."""
    (tmp_path / ".code_os").mkdir()
    (tmp_path / ".git").mkdir()  # so git commands don't fail
    # Init a minimal git repo so commits work
    os.system(f'git -C "{tmp_path}" init -q')
    os.system(f'git -C "{tmp_path}" config user.email "test@test.com"')
    os.system(f'git -C "{tmp_path}" config user.name "Test"')
    os.system(f'git -C "{tmp_path}" commit --allow-empty -m "init" -q')
    return str(tmp_path)


@pytest.fixture
def sample_tasks_json() -> list[dict[str, Any]]:
    return [
        {
            "id": "t1",
            "title": "Set up project structure",
            "description": "Create base directories and config files",
            "dependencies": [],
            "complexity": "low",
            "target_files": ["setup.py"],
            "target_modules": [],
        },
        {
            "id": "t2",
            "title": "Implement core logic",
            "description": "Write the main business logic module",
            "dependencies": ["t1"],
            "complexity": "high",
            "target_files": ["core/logic.py"],
            "target_modules": ["core"],
        },
        {
            "id": "t3",
            "title": "Write integration tests",
            "description": "Comprehensive test suite for all modules",
            "dependencies": ["t2"],
            "complexity": "medium",
            "target_files": ["tests/test_core.py"],
            "target_modules": ["tests"],
        },
    ]


# ── Test A: Master Plan Decomposition generates valid DAG ─────────────────────

@pytest.mark.asyncio
async def test_master_plan_decomposition_generates_dag(
    tmp_workspace: str, sample_tasks_json: list[dict]
):
    """AI decomposition returns a valid DAG with proper IDs and dependency structure."""
    from app.features.ai.marathon.marathon_schemas import (
        MarathonState, MarathonStatus, BudgetConfig
    )
    from app.features.ai.marathon.marathon_planner import (
        decompose_goal, _topological_sort, _build_tasks_from_dicts
    )

    state = MarathonState(
        goal="Build a FastAPI service with CRUD endpoints and tests",
        workspace=tmp_workspace,
        budget=BudgetConfig(token_budget=500_000),
    )

    mock_ai_response = json.dumps(sample_tasks_json)

    with patch(
        "app.features.ai.marathon.marathon_planner._call_ai_planner",
        new_callable=AsyncMock,
        return_value=sample_tasks_json,
    ):
        result = await decompose_goal(state)

    # Basic structure checks
    assert result.status == MarathonStatus.RUNNING
    assert len(result.tasks) == 3
    assert result.clarifying_question is None

    # DAG validity: topological sort must succeed (no cycle)
    order = _topological_sort(result.tasks)
    assert order is not None, "DAG has a cycle"
    assert len(order) == 3

    # Dependency IDs must reference real task IDs
    task_ids = {t.id for t in result.tasks}
    for t in result.tasks:
        for dep in t.dependencies:
            assert dep in task_ids, f"Task {t.id} has unknown dependency {dep}"

    # Each task must have required fields
    for t in result.tasks:
        assert t.title
        assert t.complexity is not None
        assert t.status.value == "todo"


# ── Test B: Marathon state persists to disk ───────────────────────────────────

@pytest.mark.asyncio
async def test_marathon_state_persists_to_disk(tmp_workspace: str):
    """Starting a marathon writes a valid JSON state file to .code_os/."""
    from app.features.ai.marathon.marathon_schemas import (
        MarathonState, MarathonStatus, BudgetConfig
    )
    from app.features.ai.marathon.marathon_service import save_state, load_state

    state = MarathonState(
        goal="Create 3 hello world Python files with tests",
        workspace=tmp_workspace,
        budget=BudgetConfig(token_budget=100_000),
    )
    state.status = MarathonStatus.RUNNING

    # Save state
    save_state(state)

    # Check file exists
    state_file = Path(tmp_workspace) / ".code_os" / f"marathon_state_{state.marathon_id}.json"
    assert state_file.exists(), "State file was not created"

    # File is valid JSON with correct structure
    raw = json.loads(state_file.read_text(encoding="utf-8"))
    assert raw["marathon_id"] == state.marathon_id
    assert raw["goal"] == state.goal
    assert raw["status"] == "running"

    # Round-trip: load_state returns the same state
    loaded = load_state(state.marathon_id, tmp_workspace)
    assert loaded is not None
    assert loaded.marathon_id == state.marathon_id
    assert loaded.status == MarathonStatus.RUNNING
    assert loaded.goal == state.goal


# ── Test C: Context reset serializes and resumes ──────────────────────────────

@pytest.mark.asyncio
async def test_context_reset_serializes_and_resumes(tmp_workspace: str):
    """When tokens reach 80%, state is serialized with a valid resume context."""
    from app.features.ai.marathon.marathon_schemas import (
        MarathonState, BudgetConfig, BudgetUsage, MarathonSubTask, SubTaskStatus
    )

    budget = BudgetConfig(token_budget=100_000)
    usage = BudgetUsage(started_at=time.time())
    usage.tokens_used = 82_000  # 82% of 100k > 80% threshold

    state = MarathonState(
        goal="Migrate DB to Postgres and update all ORMs",
        workspace=tmp_workspace,
        budget=budget,
        usage=usage,
    )
    # Add some tasks
    t1 = MarathonSubTask(title="Set up Postgres", description="Install and configure")
    t1.status = SubTaskStatus.COMPLETED
    t2 = MarathonSubTask(title="Update ORM models", description="Convert SQLite to Postgres")
    state.tasks = [t1, t2]

    # Check 80% threshold
    assert state.usage.any_at_80pct_tokens(budget) is True, "Should trigger context reset at 82%"

    # Generate resume context
    resume_ctx = state.to_resume_context()
    assert state.marathon_id in resume_ctx
    assert state.goal in resume_ctx
    assert "1/2 tasks completed" in resume_ctx
    assert t2.title in resume_ctx, "Remaining task should appear in resume context"

    # State can be saved and loaded (simulating serialization for new session)
    from app.features.ai.marathon.marathon_service import save_state, load_state
    save_state(state)
    loaded = load_state(state.marathon_id, tmp_workspace)
    assert loaded is not None
    assert loaded.tasks[0].status == SubTaskStatus.COMPLETED
    assert loaded.tasks[1].status == SubTaskStatus.TODO


# ── Test D: Budget guard pauses at 90% ───────────────────────────────────────

@pytest.mark.asyncio
async def test_budget_guard_pauses_at_90_percent(tmp_workspace: str):
    """Budget guard triggers pause when any budget dimension hits 90%."""
    from app.features.ai.marathon.marathon_schemas import (
        MarathonState, BudgetConfig, BudgetUsage, MarathonSubTask
    )

    # Token budget at 92%
    budget = BudgetConfig(token_budget=100_000, cost_budget_usd=10.0, time_budget_seconds=3600)
    usage = BudgetUsage(started_at=time.time() - 100)
    usage.tokens_used = 92_000  # 92%
    usage.cost_usd = 0.5
    usage.elapsed_seconds = 100

    state = MarathonState(
        goal="Big refactor",
        workspace=tmp_workspace,
        budget=budget,
        usage=usage,
    )
    t1 = MarathonSubTask(title="Task 1", description="First task")
    state.tasks = [t1]

    should_pause, reason = state.usage.any_at_90pct(state.budget)
    assert should_pause is True
    assert "token" in reason.lower()

    # Cost budget at 95%
    usage2 = BudgetUsage(started_at=time.time() - 100)
    usage2.tokens_used = 1_000  # only 1%
    usage2.cost_usd = 9.6   # 96%
    usage2.elapsed_seconds = 100
    state.usage = usage2
    should_pause2, reason2 = state.usage.any_at_90pct(state.budget)
    assert should_pause2 is True
    assert "cost" in reason2.lower()

    # Time budget at 95%
    usage3 = BudgetUsage(started_at=time.time() - 3420)  # 95% of 3600s
    usage3.tokens_used = 100
    usage3.cost_usd = 0.01
    state.usage = usage3
    state.usage.update_elapsed()
    should_pause3, reason3 = state.usage.any_at_90pct(state.budget)
    assert should_pause3 is True
    assert "time" in reason3.lower()

    # Under threshold (all at 50%) — should NOT pause
    usage4 = BudgetUsage(started_at=time.time() - 1800)
    usage4.tokens_used = 50_000   # 50%
    usage4.cost_usd = 5.0          # 50%
    usage4.elapsed_seconds = 1800  # 50%
    state.usage = usage4
    should_pause4, _ = state.usage.any_at_90pct(state.budget)
    assert should_pause4 is False


# ── Test E: Blocked task is skipped, not halted ───────────────────────────────

@pytest.mark.asyncio
async def test_blocked_task_is_skipped_not_halted(tmp_workspace: str):
    """After 3 failed retries, a task is marked blocked and executor moves to next independent task."""
    from app.features.ai.marathon.marathon_schemas import (
        MarathonState, BudgetConfig, MarathonSubTask, SubTaskStatus
    )
    from app.features.ai.marathon.marathon_executor import MarathonExecutor

    # Build state with 2 independent tasks (no dependency between them)
    t1 = MarathonSubTask(title="Task A (will fail)", description="This fails", max_retries=3)
    t2 = MarathonSubTask(title="Task B (independent)", description="This succeeds", dependencies=[])
    state = MarathonState(
        goal="Test blocked skip",
        workspace=tmp_workspace,
        budget=BudgetConfig(token_budget=1_000_000),
    )
    state.tasks = [t1, t2]

    executor = MarathonExecutor(state)

    # Mock _dispatch_to_team to fail for t1 but succeed for t2
    async def mock_dispatch(task: MarathonSubTask) -> dict:
        if task.id == t1.id:
            return {"success": False, "error": "Simulated failure", "tokens_used": 100, "cost_usd": 0.01}
        return {"success": True, "error": "", "tokens_used": 200, "cost_usd": 0.02}

    # Mock git_commit to return a dummy hash
    async def mock_commit(task: MarathonSubTask) -> str:
        return "abc1234"

    with patch.object(executor, "_dispatch_to_team", side_effect=mock_dispatch):
        with patch.object(executor, "_git_commit", side_effect=mock_commit):
            with patch.object(executor, "_git_rollback", new_callable=AsyncMock):
                # Execute t1 — should exhaust retries and become blocked
                await executor._execute_subtask(t1)

    assert t1.status == SubTaskStatus.BLOCKED, f"Expected blocked, got {t1.status}"
    assert t1.retry_count == t1.max_retries

    # t2 should still be TODO (independent, not blocked)
    assert t2.status == SubTaskStatus.TODO, "Independent task should not be affected"

    # Verify ready_tasks still contains t2
    ready = state.ready_tasks
    assert any(t.id == t2.id for t in ready), "t2 should still be ready after t1 is blocked"


# ── Test F: Marathon resumes after backend restart ────────────────────────────

@pytest.mark.asyncio
async def test_marathon_resumes_after_backend_restart(tmp_workspace: str):
    """On backend boot, check_for_active_marathon detects paused state and offers resume."""
    from app.features.ai.marathon.marathon_schemas import (
        MarathonState, MarathonStatus, BudgetConfig, MarathonSubTask, SubTaskStatus
    )
    from app.features.ai.marathon.marathon_service import (
        save_state, check_for_active_marathon, load_state
    )

    # Simulate a paused marathon left from a previous session
    t1 = MarathonSubTask(title="Done task", description="Already done")
    t1.status = SubTaskStatus.COMPLETED
    t1.git_commit_hash = "abc1234"

    t2 = MarathonSubTask(title="Remaining task", description="Not yet done")

    state = MarathonState(
        goal="Create 5 dummy python files with hello world",
        workspace=tmp_workspace,
        budget=BudgetConfig(token_budget=50_000),
    )
    state.tasks = [t1, t2]
    state.status = MarathonStatus.PAUSED
    state.touch()
    save_state(state)

    # Simulate "backend restart" by calling boot-time check
    found = check_for_active_marathon(tmp_workspace)
    assert found is not None, "Should find the paused marathon on boot"
    assert found.marathon_id == state.marathon_id
    assert found.status == MarathonStatus.PAUSED

    # Verify tasks are intact after round-trip
    assert len(found.tasks) == 2
    completed = [t for t in found.tasks if t.status == SubTaskStatus.COMPLETED]
    todo = [t for t in found.tasks if t.status == SubTaskStatus.TODO]
    assert len(completed) == 1
    assert len(todo) == 1
    assert todo[0].title == "Remaining task"

    # ready_tasks should return the remaining task
    ready = found.ready_tasks
    assert any(t.id == t2.id for t in ready), "Remaining task should be ready to resume"
