import pytest
import asyncio
from pathlib import Path
from app.features.workspaces.trust_service import set_workspace_trust

@pytest.mark.asyncio
async def test_agent_console_plan_endpoint_short_and_long_prompts(async_client, tmp_path, monkeypatch, temp_db):
    ws_dir = str(tmp_path / "trusted_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)

    from app.features.ai.agents.planner import PlannerAgent
    original_plan = PlannerAgent.plan_task
    async def mock_plan_task(self, user_request: str, workspace_context: str = ""):
        if "--quick" in user_request.lower() or "--quick" in workspace_context.lower():
            return await original_plan(self, user_request, workspace_context)
        return [
            {"id": "calc_setup", "title": "Create calculator.py", "agent_role": "Coding Agent", "dependencies": [], "estimated_effort": "15 mins"}
        ]
    monkeypatch.setattr(PlannerAgent, "plan_task", mock_plan_task)

    # Test short prompt (e.g. calculator.py)
    res_short = await async_client.post(
        "/api/agents/plan",
        json={
            "workspace": ws_dir,
            "user_request": "Create calculator.py with add and subtract functions"
        }
    )
    assert res_short.status_code == 200
    data_short = res_short.json()
    assert "tasks" in data_short
    assert len(data_short["tasks"]) > 0

    # Test quick mode flag
    res_quick = await async_client.post(
        "/api/agents/plan",
        json={
            "workspace": ws_dir,
            "user_request": "Refactor divide function --quick"
        }
    )
    assert res_quick.status_code == 200
    data_quick = res_quick.json()
    assert len(data_quick["tasks"]) == 1
    assert data_quick["tasks"][0]["agent_role"] == "Coding Agent"


@pytest.mark.asyncio
async def test_agent_console_e2e_job_execution(async_client, tmp_path, monkeypatch, temp_db):
    ws_dir = str(tmp_path / "trusted_job_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)

    from app.features.ai.agents.agent_factory import AgentFactory
    from app.features.ai.agents.agent_interface import AgentOutput

    class MockAgent:
        async def execute(self, job_id, task_id, task_title, context, workspace):
            return AgentOutput(
                agent_role="Coding Agent",
                task_id=task_id,
                status="success",
                confidence=1.0,
                reasoning_summary="Mock executed successfully",
                proposals=[]
            )

    monkeypatch.setattr(AgentFactory, "create_agent", lambda role, provider_config=None: MockAgent())

    # 1. Generate plan
    res_plan = await async_client.post(
        "/api/agents/plan",
        json={
            "workspace": ws_dir,
            "user_request": "Create calculator.py test module --quick"
        }
    )
    assert res_plan.status_code == 200
    tasks = res_plan.json()["tasks"]

    # 2. Start job
    res_job = await async_client.post(
        "/api/agents/jobs",
        json={
            "workspace": ws_dir,
            "workflow": "Feature Development",
            "tasks": tasks
        }
    )
    assert res_job.status_code == 200
    job_id = res_job.json()["job_id"]

    # 3. Poll job execution until complete (mock runs in <1s)
    for _ in range(20):
        await asyncio.sleep(0.1)
        res_status = await async_client.get(f"/api/agents/jobs/{job_id}")
        assert res_status.status_code == 200
        job_data = res_status.json()
        if job_data["status"] in ("completed", "failed", "cancelled"):
            break

    assert job_data["status"] == "completed"
    assert len(job_data["tasks"]) == 1
    assert job_data["tasks"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_no_regressions_coder_dual_coder_duo(async_client, tmp_path, monkeypatch, temp_db):
    ws_dir = str(tmp_path / "trusted_no_regr_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)

    import app.features.ai.coder_mode_service as cms
    import app.features.ai.agent_routes as ar
    async def mock_cms(payload):
        return {"status": "success", "applied": True}
    monkeypatch.setattr(cms, "execute_coder_mode", mock_cms)
    monkeypatch.setattr(ar, "execute_coder_mode", mock_cms)

    import app.features.ai.dual_coder_routes as dcr
    async def mock_dual_execute(payload):
        return {"session_id": "dual_test_123", "status": "completed", "proposals": []}
    monkeypatch.setattr(dcr, "execute_dual_coder", mock_dual_execute)

    # Verify Coder Mode endpoint
    res_coder = await async_client.post(
        "/api/agents/coder-mode/execute",
        json={
            "workspace": ws_dir,
            "user_request": "Create a dummy helper file"
        }
    )
    assert res_coder.status_code == 200

    # Verify Dual Coder endpoint
    res_dual = await async_client.post(
        "/api/dual-coder/execute",
        json={
            "workspace": ws_dir,
            "task_description": "Create a utility function",
            "model_a": {"provider": "ollama", "model": "llama3"},
            "model_b": {"provider": "ollama", "model": "llama3"}
        }
    )
    assert res_dual.status_code == 200

    # Verify Duo Loop list sessions endpoint
    res_duo = await async_client.get(f"/api/duo/sessions?workspace={ws_dir}")
    assert res_duo.status_code == 200
