from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.features.ai.agents.agent_interface import BaseAgent, AgentOutput
from app.features.ai.team.team_schemas import (
    HandoffArtifact,
    HandoffType,
    TeamConfig,
    TeamRole,
    TeamTask,
)
from app.features.ai.team.orchestrator import TeamOrchestrator
from app.features.workspaces.trust_service import set_workspace_trust
from app.features.ai.team.team_routes import (
    SubmitTeamJobRequest,
    submit_team_job,
    stream_team_events,
    get_or_create_active_job,
    _active_jobs,
)


class DummyAgent(BaseAgent):
    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        return AgentOutput(
            agent_role=self.role,
            task_id=task_id,
            status="completed",
            confidence=1.0,
            reasoning_summary="dummy reasoning",
        )

    def get_system_prompt(self) -> str:
        return "Dummy prompt"


# ── Test 1: Stuck Role Times Out Bounded & Handles Fallback ───────────────────

@pytest.mark.asyncio
async def test_stuck_role_times_out_and_handles_fallback(monkeypatch, temp_db):
    """Permission and clarification requests must time out boundedly instead of hanging forever."""
    monkeypatch.setenv("CODE_OS_AGENT_WAIT_TIMEOUT", "0.05")

    agent = DummyAgent(role="coder")
    job_id = "test_timeout_job"
    task_id = "test_timeout_task"

    # 1. Permission request timeout -> Default denied
    t0 = time.time()
    res_perm = await agent.request_permission(job_id, task_id, "edit_file", "edit foo.py", "python")
    elapsed_perm = time.time() - t0
    assert res_perm is False
    assert elapsed_perm < 1.0, f"Permission wait took too long: {elapsed_perm}s"

    # 2. Clarification request timeout -> Default empty string / rejected
    t1 = time.time()
    res_clar = await agent.request_clarification(job_id, task_id, "Which framework to use?")
    elapsed_clar = time.time() - t1
    assert res_clar == ""
    assert elapsed_clar < 1.0, f"Clarification wait took too long: {elapsed_clar}s"

    # 3. LLM failure recovery timeout -> Default cancel
    t2 = time.time()
    res_fail = await agent.handle_llm_failure(job_id, task_id, RuntimeError("Simulated model rate limit"))
    elapsed_fail = time.time() - t2
    assert res_fail["action"] == "cancel"
    assert elapsed_fail < 1.0, f"LLM failure wait took too long: {elapsed_fail}s"


# ── Test 2: Role Receives Non-empty Plan & Artifacts Context ───────────────────

@pytest.mark.asyncio
async def test_role_receives_nonempty_plan_and_artifacts(temp_db, tmp_path: Path):
    """Submitted team tasks must carry the original prompt, workspace, and attached files in context."""
    ws = str(tmp_path)
    await set_workspace_trust(ws, True)
    req = SubmitTeamJobRequest(
        prompt="Refactor database layer to support postgres connection pooling",
        workspace=ws,
        file_ids=["db_pool.py"],
    )

    mock_file = {
        "id": "db_pool.py",
        "filename": "db_pool.py",
        "content": "class Pool: pass",
        "mime_type": "text/plain",
        "page_count": 1,
        "word_count": 3,
        "metadata": {},
    }
    with patch("app.features.ai.file_ingestion.service.get_uploaded_file", return_value=mock_file):
        res = await submit_team_job(req)

    job_id = res["job_id"]
    job = _active_jobs.get(job_id)
    assert job is not None
    tasks = job.tasks
    assert len(tasks) == 4

    # All pipeline tasks (arch, code, test, rev) must have non-empty workspace & original_prompt
    for task in tasks:
        ctx = task.context
        assert ctx is not None
        assert ctx.get("workspace") == ws
        assert ctx.get("original_prompt") == "Refactor database layer to support postgres connection pooling"
        assert "attached_files" in ctx
        assert ctx["file_ids"] == ["db_pool.py"]


# ── Test 3: Coder Output Gated by Tester Before Reviewer ───────────────────────

@pytest.mark.asyncio
async def test_coder_output_gated_by_tester_before_reviewer(tmp_path: Path):
    """Tester failures must loop back to Coder with test failure output, and block DAG if still failing."""
    coder_invocations = 0
    tester_invocations = 0
    reviewer_invoked = False
    events_emitted = []

    async def mock_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        nonlocal coder_invocations, tester_invocations, reviewer_invoked
        role = task.role
        if role == TeamRole.CODER:
            coder_invocations += 1
            return {
                "role": "coder",
                "status": "completed",
                "reasoning": f"Coder attempt {coder_invocations}",
                "proposals": [{"path": "solution.py"}],
            }
        elif role == TeamRole.TESTER:
            tester_invocations += 1
            # Simulate test failure on both attempts
            return {
                "role": "tester",
                "status": "completed",
                "reasoning": "AssertionError: 404 != 200 in test_api",
                "test_results": {
                    "passed": False,
                    "failed": 1,
                    "output": "FAILED tests/test_api.py::test_status - AssertionError: 404 != 200",
                },
            }
        elif role == TeamRole.REVIEWER:
            reviewer_invoked = True
            return {"role": "reviewer", "status": "completed"}
        return {"role": str(role), "status": "completed"}

    config = TeamConfig(workspace=str(tmp_path), max_concurrency=2, auto_verify=False)
    orchestrator = TeamOrchestrator(team_config=config, task_executor=mock_executor)
    orchestrator.subscribe(lambda ev: events_emitted.append(ev))

    tasks = [
        TeamTask(task_id="t_code", job_id="job_gate", title="Write code", role=TeamRole.CODER, dependencies=[]),
        TeamTask(task_id="t_test", job_id="job_gate", title="Run tests", role=TeamRole.TESTER, dependencies=["t_code"]),
        TeamTask(task_id="t_rev", job_id="job_gate", title="Review code", role=TeamRole.REVIEWER, dependencies=["t_test"]),
    ]

    result = await orchestrator.execute_dag(tasks, job_id="job_gate")

    # 1. Coder was called, then retried when Tester failed
    assert coder_invocations == 2, f"Expected 2 coder invocations, got {coder_invocations}"
    assert tester_invocations >= 1

    # 2. Reviewer must NEVER run because Tester failed and blocked the pipeline
    assert not reviewer_invoked, "Reviewer should not have been invoked when tester failed"
    assert "t_test" in orchestrator.failed_task_ids
    assert result["status"] == "failed"

    # 3. Blocked event was emitted
    blocked_events = [e for e in events_emitted if e.event == "team_step_update" and e.data.get("status") == "blocked"]
    assert len(blocked_events) > 0


# ── Test 4: Team SSE Heartbeat Emitted ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_team_sse_heartbeat_emitted():
    """SSE event generator must emit a heartbeat event every ~5s with job status."""
    job_id = "test_hb_job"
    active_job = get_or_create_active_job(job_id)
    active_job.status = "running"

    try:
        response = await stream_team_events(job_id, snapshot_only=False)
        collected_chunks = []
        start = time.time()
        async for chunk in response.body_iterator:
            collected_chunks.append(chunk)
            if "event: heartbeat" in chunk or (time.time() - start) > 7.0:
                break

        full_output = "".join(collected_chunks)
        assert "event: heartbeat" in full_output
        assert "job_id" in full_output
        assert "running" in full_output
    finally:
        _active_jobs.pop(job_id, None)
