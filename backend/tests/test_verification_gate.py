from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task
from app.features.ai.team.team_schemas import (
    HandoffArtifact,
    HandoffType,
    TeamConfig,
    TeamRole,
    TeamTask,
)
from app.features.ai.team.verifier import VerificationGate, parse_test_output, audit_code_files
from app.features.ai.team.orchestrator import TeamOrchestrator


# ── Test 1: Verification Passes When Tests Green (Happy Path) ────────────────

@pytest.mark.asyncio
async def test_verification_passes_when_tests_green(tmp_path: Path):
    """Happy path: test suite reports green tests and code review has zero blockers."""
    events_captured: list[tuple[str, dict]] = []

    def mock_emitter(event: str, data: dict):
        events_captured.append((event, data))

    async def mock_test_runner(ws: str):
        return {
            "success": True,
            "passed": 8,
            "failed": 0,
            "errors": 0,
            "failed_tests": [],
            "output": "8 passed in 0.12s",
        }

    # Clean file with no stubs or security issues
    clean_file = tmp_path / "solution.py"
    clean_file.write_text("def solve():\n    return 42\n", encoding="utf-8")

    gate = VerificationGate(
        event_emitter=mock_emitter,
        test_runner=mock_test_runner,
    )

    result = await gate.verify_job(
        job_id="job_green_1",
        workspace=str(tmp_path),
        team_config=TeamConfig(workspace=str(tmp_path), max_repair_rounds=3),
        modified_files=["solution.py"],
    )

    assert result["verified"] is True
    assert result["rounds_used"] == 1
    assert "clean" in result["reason"].lower() or "passed" in result["reason"].lower()
    assert result["metrics"]["tests_passed"] == 8
    assert result["metrics"]["tests_failed"] == 0
    assert result["metrics"]["review_notes"] == 0

    # Ensure verified status event was emitted
    status_events = [data for evt, data in events_captured if evt == "team_status"]
    assert any(s.get("status") == "verified" for s in status_events)


# ── Test 2: Verification Triggers Repair on Test Failure (1 Round) ───────────

@pytest.mark.asyncio
async def test_verification_triggers_repair_on_test_failure(tmp_path: Path):
    """Round 1 has test failures; repair task runs Coder; Round 2 tests pass."""
    repair_tasks_run: list[TeamTask] = []
    received_handoffs: list[list[HandoffArtifact]] = []
    call_count = 0

    async def mock_test_runner(ws: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "success": False,
                "passed": 2,
                "failed": 1,
                "errors": 0,
                "failed_tests": ["test_divide_by_zero"],
                "output": "FAILED test_divide_by_zero - ZeroDivisionError\n1 failed, 2 passed",
            }
        else:
            return {
                "success": True,
                "passed": 3,
                "failed": 0,
                "errors": 0,
                "failed_tests": [],
                "output": "3 passed in 0.05s",
            }

    async def mock_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        repair_tasks_run.append(task)
        received_handoffs.append(prior_handoffs)
        return {"status": "completed", "role": "coder", "reasoning": "Fixed ZeroDivisionError bug"}

    gate = VerificationGate(
        task_executor=mock_executor,
        test_runner=mock_test_runner,
    )

    result = await gate.verify_job(
        job_id="job_repair_1",
        workspace=str(tmp_path),
        team_config=TeamConfig(workspace=str(tmp_path), max_repair_rounds=3),
        modified_files=[],
    )

    assert result["verified"] is True
    assert result["rounds_used"] == 2
    assert len(repair_tasks_run) == 1
    assert repair_tasks_run[0].role == TeamRole.CODER
    assert repair_tasks_run[0].metadata.get("repair_round") == 1
    assert len(received_handoffs[0]) == 1
    assert received_handoffs[0][0].type == HandoffType.TEST_OUTPUT


# ── Test 3: Verification Repair Loop Max Rounds (3 Rounds then Pause) ────────

@pytest.mark.asyncio
async def test_verification_repair_loop_max_rounds(tmp_path: Path):
    """Persistent failures exhaust max_repair_rounds (3 rounds) and return verified=False."""
    repair_rounds_observed: list[int] = []

    async def mock_failing_test_runner(ws: str):
        return {
            "success": False,
            "passed": 1,
            "failed": 2,
            "errors": 0,
            "failed_tests": ["test_auth_token", "test_refresh"],
            "output": "FAILED test_auth_token\nFAILED test_refresh\n2 failed, 1 passed",
        }

    async def mock_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        round_val = task.metadata.get("repair_round", 0)
        repair_rounds_observed.append(round_val)
        return {"status": "completed", "role": "coder", "reasoning": f"Attempted fix round {round_val}"}

    gate = VerificationGate(
        task_executor=mock_executor,
        test_runner=mock_failing_test_runner,
    )

    result = await gate.verify_job(
        job_id="job_max_rounds",
        workspace=str(tmp_path),
        team_config=TeamConfig(workspace=str(tmp_path), max_repair_rounds=3),
    )

    assert result["verified"] is False
    assert result["rounds_used"] == 3
    assert "remain after 3 round(s)" in result["reason"] or "failed" in result["reason"].lower()
    assert repair_rounds_observed == [1, 2]


# ── Test 4: Verification Blocks on Review Issues (Reviewer Finds Stubs) ───────

@pytest.mark.asyncio
async def test_verification_blocks_on_review_issues(tmp_path: Path):
    """Green tests, but Reviewer detects TODO/NotImplementedError stubs; triggers Coder repair."""
    stub_file = tmp_path / "handler.py"
    stub_file.write_text("def process():\n    # TODO: implement authentication\n    raise NotImplementedError\n", encoding="utf-8")

    repair_invoked = False

    async def mock_test_runner(ws: str):
        return {"success": True, "passed": 4, "failed": 0, "errors": 0, "failed_tests": [], "output": "4 passed"}

    async def mock_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        nonlocal repair_invoked
        repair_invoked = True
        # Coder replaces stub file with real implementation
        stub_file.write_text("def process():\n    return {'status': 'authenticated'}\n", encoding="utf-8")
        return {"status": "completed", "role": "coder", "reasoning": "Removed stubs and implemented process()"}

    gate = VerificationGate(
        task_executor=mock_executor,
        test_runner=mock_test_runner,
    )

    result = await gate.verify_job(
        job_id="job_stub_audit",
        workspace=str(tmp_path),
        team_config=TeamConfig(workspace=str(tmp_path), max_repair_rounds=3),
        modified_files=["handler.py"],
    )

    assert repair_invoked is True
    assert result["verified"] is True
    assert result["rounds_used"] == 2


# ── Test 5: Verification Emits Team Repair Events (SSE Events) ────────────────

@pytest.mark.asyncio
async def test_verification_emits_team_repair_events(tmp_path: Path):
    """VerificationGate emits 'team_repair' SSE events with round and failure details."""
    captured_repair_events: list[dict] = []
    captured_messages: list[dict] = []

    def mock_emitter(event: str, data: dict):
        if event == "team_repair":
            captured_repair_events.append(data)
        elif event == "team_message":
            captured_messages.append(data)

    call_num = 0

    async def mock_test_runner(ws: str):
        nonlocal call_num
        call_num += 1
        if call_num == 1:
            return {
                "success": False,
                "passed": 0,
                "failed": 2,
                "errors": 0,
                "failed_tests": ["test_database_lock", "test_retry"],
                "output": "2 failed",
            }
        return {"success": True, "passed": 2, "failed": 0, "errors": 0, "failed_tests": [], "output": "2 passed"}

    async def mock_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        return {"status": "completed", "role": "coder"}

    gate = VerificationGate(
        event_emitter=mock_emitter,
        task_executor=mock_executor,
        test_runner=mock_test_runner,
    )

    await gate.verify_job(
        job_id="job_sse_repair",
        workspace=str(tmp_path),
        team_config=TeamConfig(workspace=str(tmp_path), max_repair_rounds=3),
    )

    assert len(captured_repair_events) == 1
    ev = captured_repair_events[0]
    assert ev["round"] == 1
    assert ev["max_rounds"] == 3
    assert "test_database_lock" in ev["failures"]

    # Verify repair message banner
    repair_msgs = [m for m in captured_messages if m.get("message_type") == "repair"]
    assert len(repair_msgs) == 1
    assert "Repair Round 1/3" in repair_msgs[0]["content"]


# ── Test 6: Final Report Includes Metrics (Files/Tests/Cost) ──────────────────

@pytest.mark.asyncio
async def test_final_report_includes_metrics(tmp_path: Path):
    """Final report card compiled upon verification completion contains all expected metrics."""
    f1 = tmp_path / "module1.py"
    f2 = tmp_path / "module2.py"
    f1.write_text("x = 10\n", encoding="utf-8")
    f2.write_text("y = 20\n", encoding="utf-8")

    async def mock_test_runner(ws: str):
        return {"success": True, "passed": 12, "failed": 0, "errors": 0, "failed_tests": [], "output": "12 passed"}

    gate = VerificationGate(
        test_runner=mock_test_runner,
    )

    result = await gate.verify_job(
        job_id="job_metrics_report",
        workspace=str(tmp_path),
        team_config=TeamConfig(workspace=str(tmp_path)),
        modified_files=["module1.py", "module2.py"],
    )

    assert result["verified"] is True
    report = result["final_report"]
    assert report is not None
    assert report["files_changed"] == 2
    assert report["tests_run"] == 12
    assert report["tests_passed"] == 12
    assert report["tests_failed"] == 0
    assert report["review_notes"] == 0
    assert report["repair_rounds"] == 1
    assert "total_cost" in report
    assert isinstance(report["total_cost"], (int, float))
