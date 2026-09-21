from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.ai.team.orchestrator import TeamOrchestrator
from app.features.ai.team.roles import CoderRole, TesterRole
from app.features.ai.team.team_schemas import TeamConfig, TeamRole, TeamTask, TeamTaskResult
from app.features.automation.computer_controller import ComputerController


# ── F-0008: Non-blocking Subprocess in ComputerController ────────────────────

@pytest.mark.asyncio
async def test_list_windows_does_not_block_event_loop(tmp_path: Path):
    """Assert that list_windows offloads subprocess to a thread and does not starve concurrent tasks."""
    controller = ComputerController(str(tmp_path))

    def slow_run(*args, **kwargs):
        time.sleep(0.3)
        mock_res = MagicMock()
        mock_res.stdout = "CodeOS Window\nEditor Window\n"
        mock_res.returncode = 0
        return mock_res

    with patch.object(controller, "_check_permission_and_safety", AsyncMock(return_value=None)), \
         patch.dict("sys.modules", {"pygetwindow": None}), \
         patch("subprocess.run", side_effect=slow_run):

        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.05)
                ticks += 1

        t0 = time.perf_counter()
        res, _ = await asyncio.gather(
            controller.list_windows(),
            ticker(),
        )
        elapsed = time.perf_counter() - t0

        assert res["success"] is True
        assert "CodeOS Window" in res["windows"]
        # If event loop were blocked by synchronous subprocess.run, ticker would not tick during slow_run
        assert ticks >= 3, f"Event loop was blocked; ticker only completed {ticks} ticks"
        assert elapsed >= 0.25


@pytest.mark.asyncio
async def test_focus_window_offloads_to_thread(tmp_path: Path):
    """Assert that focus_window offloads to a worker thread, allowing concurrent async execution."""
    controller = ComputerController(str(tmp_path))

    def slow_run(*args, **kwargs):
        time.sleep(0.5)
        mock_res = MagicMock()
        mock_res.returncode = 0
        return mock_res

    with patch.object(controller, "_check_permission_and_safety", AsyncMock(return_value=None)), \
         patch.dict("sys.modules", {"pygetwindow": None}), \
         patch("os.name", "nt"), \
         patch("subprocess.run", side_effect=slow_run):

        t0 = time.perf_counter()
        res, _ = await asyncio.gather(
            controller.focus_window("TestApp"),
            asyncio.sleep(0.5),
        )
        elapsed = time.perf_counter() - t0

        assert res["success"] is True
        # In parallel (offloaded to thread), subprocess(0.5s) + focus_window sleep(0.5s) completes in ~1.0s
        # If serialized (synchronous blocking on event loop), it would take >= 1.5s
        assert elapsed < 1.4, f"Execution appeared serialized instead of threaded: elapsed={elapsed:.3f}s"


# ── F-0012: Role Permissions Wired into Orchestrator ─────────────────────────

@pytest.mark.asyncio
async def test_role_permission_gate_blocks_denied_tasks(tmp_path: Path):
    """Tester role (read-only for production code) must be denied edit_file tasks and touch no files."""
    test_file = tmp_path / "app.py"
    test_file.write_text("production_code_v1", encoding="utf-8")

    config = TeamConfig(workspace=str(tmp_path))
    orchestrator = TeamOrchestrator(team_config=config)

    write_task = TeamTask(
        task_id="task_write_denied",
        job_id="job_perm_test",
        title="Modify production app",
        role=TeamRole.TESTER,
        context={
            "type": "edit_file",
            "path": str(test_file),
            "target_file": str(test_file),
        },
    )

    result = await orchestrator.execute_task(write_task)

    assert result.status == "denied"
    assert "lacks permission" in result.error
    assert test_file.read_text(encoding="utf-8") == "production_code_v1", "File was modified despite permission denial!"


@pytest.mark.asyncio
async def test_role_permission_gate_allows_permitted_tasks(tmp_path: Path):
    """Coder role (write permission) must be allowed to execute edit_file tasks."""
    test_file = tmp_path / "calculator.py"
    test_file.write_text("def add(a, b): pass", encoding="utf-8")

    config = TeamConfig(workspace=str(tmp_path))
    orchestrator = TeamOrchestrator(team_config=config)

    coder_task = TeamTask(
        task_id="task_write_allowed",
        job_id="job_perm_test",
        title="Implement add function",
        role=TeamRole.CODER,
        context={
            "type": "edit_file",
            "path": str(test_file),
            "target_file": str(test_file),
        },
    )

    mock_agent = MagicMock()
    async def fake_execute(*args, **kwargs):
        test_file.write_text("def add(a, b): return a + b", encoding="utf-8")
        out = MagicMock()
        out.status = "completed"
        out.reasoning = "Implemented add"
        out.proposals = []
        out.test_results = None
        return out
    mock_agent.execute = fake_execute

    with patch("app.features.ai.agents.agent_factory.AgentFactory.create_agent", return_value=mock_agent):
        result = await orchestrator.execute_task(coder_task)

    assert result.status == "completed"
    assert test_file.read_text(encoding="utf-8") == "def add(a, b): return a + b"
