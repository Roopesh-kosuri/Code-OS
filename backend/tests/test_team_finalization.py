from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from app.core.paths import normalize_path
from app.db.database import get_pool
from app.features.ai.job_service import (
    create_job,
    save_final_report,
    get_final_report,
    format_report_as_markdown,
    record_agent_token_usage,
    get_agent_metrics,
)
from app.features.ai.team.team_schemas import (
    TeamConfig,
    TeamRole,
    TeamTask,
    MODEL_PRICING,
    calculate_token_cost,
)
from app.features.ai.team.orchestrator import TeamOrchestrator
from app.features.ai.harness.approval_coordinator import (
    get_pending_approvals,
    clear_pending_approvals_for_job,
)


# ── Test 1: Approval Tagged with Agent Role & Task ID ─────────────────────────

@pytest.mark.asyncio
async def test_approval_tagged_with_agent_role(temp_db, tmp_path: Path):
    """Verify that approval requests in team mode are tagged with agent_role, task_id, and reason."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))

    job_id = "job_approval_tag_1"
    await create_job(job_id, ws_path, "team_mode", user_request="Approval tagging test")

    events: list[Any] = []

    def mock_emitter(event: Any):
        events.append(event)

    orchestrator = TeamOrchestrator(
        team_config=TeamConfig(workspace=ws_path),
        workspace=ws_path,
    )
    orchestrator.subscribe(mock_emitter)

    pending = await orchestrator.request_task_approval(
        task_id="step_code_deploy",
        role=TeamRole.DEVOPS,
        action_type="run_command",
        detail="npm run deploy:staging",
        reason="DevOps agent requires elevated shell execution for deployment",
        command="npm run deploy:staging",
    )

    assert pending.action_id.startswith("appr_")

    # 1. Verify coordinator registered with agent metadata
    approvals = get_pending_approvals(job_id)
    assert len(approvals) == 1
    p = approvals[0]
    assert p.agent_role == "devops"
    assert p.task_id == "step_code_deploy"
    assert p.action_type == "run_command"
    assert p.reason == "DevOps agent requires elevated shell execution for deployment"
    assert p.metadata.get("team_mode") is True
    assert p.metadata.get("agent_role") == "devops"
    assert p.metadata.get("task_id") == "step_code_deploy"

    # 2. Verify team_approval SSE event was emitted with required fields
    approval_events = [evt.data for evt in events if getattr(evt, "event", None) == "team_approval"]
    assert len(approval_events) == 1
    evt_data = approval_events[0]
    assert evt_data["action_id"] == pending.action_id
    assert evt_data["agent_role"] == "devops"
    assert evt_data["task_id"] == "step_code_deploy"
    assert evt_data["reason"] == "DevOps agent requires elevated shell execution for deployment"
    assert evt_data["action_type"] == "run_command"

    await clear_pending_approvals_for_job(job_id)


# ── Test 2: Cost Tracking Per Role ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_cost_tracking_per_role(temp_db, tmp_path: Path):
    """Verify live cost calculation and per-role token & cost aggregation."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))

    job_id = "job_cost_per_role_1"
    await create_job(job_id, ws_path, "team_mode", user_request="Cost tracking test")

    # 1. Test model pricing table rates
    # GPT-4o: $2.50/1M in, $10.00/1M out
    gpt4o_cost = calculate_token_cost("gpt-4o", input_tokens=1_000_000, output_tokens=1_000_000)
    assert gpt4o_cost == pytest.approx(12.50, rel=1e-3)

    # Claude 3.5 Sonnet: $3.00/1M in, $15.00/1M out
    claude_cost = calculate_token_cost("claude-3-5-sonnet-latest", input_tokens=1_000_000, output_tokens=1_000_000)
    assert claude_cost == pytest.approx(18.00, rel=1e-3)

    # Groq Llama 3.3: $0.59/1M in, $0.79/1M out
    groq_cost = calculate_token_cost("llama-3.3-70b-versatile", input_tokens=1_000_000, output_tokens=1_000_000)
    assert groq_cost == pytest.approx(1.38, rel=1e-3)

    # 2. Record token usages for multiple roles in the job
    # Architect: 20,000 in, 5,000 out with GPT-4o
    arch_cost = calculate_token_cost("gpt-4o", 20_000, 5_000)
    await record_agent_token_usage(
        job_id=job_id,
        task_id="task_arch_1",
        agent_role="architect",
        input_tokens=20_000,
        output_tokens=5_000,
        cost_usd=arch_cost,
    )

    # Coder: 50,000 in, 10,000 out with Claude 3.5 Sonnet
    coder_cost = calculate_token_cost("claude-3-5-sonnet-latest", 50_000, 10_000)
    await record_agent_token_usage(
        job_id=job_id,
        task_id="task_coder_1",
        agent_role="coder",
        input_tokens=50_000,
        output_tokens=10_000,
        cost_usd=coder_cost,
    )

    # Tester: 15,000 in, 3,000 out with Groq Llama 3.3
    tester_cost = calculate_token_cost("llama-3.3-70b-versatile", 15_000, 3_000)
    await record_agent_token_usage(
        job_id=job_id,
        task_id="task_tester_1",
        agent_role="tester",
        input_tokens=15_000,
        output_tokens=3_000,
        cost_usd=tester_cost,
    )

    # 3. Aggregate metrics per role
    metrics = await get_agent_metrics(job_id)
    assert "architect" in metrics
    assert "coder" in metrics
    assert "tester" in metrics

    assert metrics["architect"]["total_tokens"] == 25_000
    assert metrics["architect"]["input_tokens"] == 20_000
    assert metrics["architect"]["output_tokens"] == 5_000
    assert metrics["architect"]["total_cost"] == pytest.approx(arch_cost, rel=1e-3)

    assert metrics["coder"]["total_tokens"] == 60_000
    assert metrics["coder"]["input_tokens"] == 50_000
    assert metrics["coder"]["output_tokens"] == 10_000
    assert metrics["coder"]["total_cost"] == pytest.approx(coder_cost, rel=1e-3)

    assert metrics["tester"]["total_tokens"] == 18_000
    assert metrics["tester"]["input_tokens"] == 15_000
    assert metrics["tester"]["output_tokens"] == 3_000
    assert metrics["tester"]["total_cost"] == pytest.approx(tester_cost, rel=1e-3)


# ── Test 3: Final Report Persists to DB ───────────────────────────────────────

@pytest.mark.asyncio
async def test_final_report_persists_to_db(temp_db, tmp_path: Path):
    """Verify save_final_report and get_final_report properly persist and retrieve JSON."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))

    job_id = "job_report_persist_1"
    await create_job(job_id, ws_path, "team_mode", user_request="Report persist test")

    initial = await get_final_report(job_id)
    assert initial is None

    report_payload = {
        "files_changed": 4,
        "tests_run": 14,
        "tests_passed": 14,
        "tests_failed": 0,
        "review_notes": 0,
        "repair_rounds": 1,
        "total_cost": 0.0842,
        "details": {
            "verifier": "autonomous_gate",
            "passed_tests": ["test_auth", "test_api", "test_db"],
        },
    }

    await save_final_report(job_id, report_payload)

    retrieved = await get_final_report(job_id)
    assert retrieved is not None
    assert retrieved["files_changed"] == 4
    assert retrieved["tests_run"] == 14
    assert retrieved["tests_passed"] == 14
    assert retrieved["tests_failed"] == 0
    assert retrieved["repair_rounds"] == 1
    assert retrieved["total_cost"] == pytest.approx(0.0842, rel=1e-3)
    assert retrieved["details"]["passed_tests"] == ["test_auth", "test_api", "test_db"]


# ── Test 4: Export Report as Markdown ────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_report_as_markdown():
    """Verify format_report_as_markdown renders all verification details in clean markdown."""
    report_data = {
        "files_changed": 3,
        "tests_run": 10,
        "tests_passed": 9,
        "tests_failed": 1,
        "review_notes": 1,
        "repair_rounds": 2,
        "total_cost": 0.05432,
    }

    md = format_report_as_markdown("job_export_99", report_data)

    assert "Verification Report" in md
    assert "job_export_99" in md
    assert "- **Files Changed:** 3" in md
    assert "- **Tests Run:** 10 (Passed: 9, Failed: 1)" in md
    assert "- **Review Notes:** 1 blockers found" in md
    assert "- **Repair Rounds:** 2" in md
    assert "$0.05" in md
