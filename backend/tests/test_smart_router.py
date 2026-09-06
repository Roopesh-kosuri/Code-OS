from __future__ import annotations

import pytest
from app.features.ai.smart_router.difficulty_classifier import classify_task_difficulty
from app.features.ai.smart_router.model_router import (
    MODEL_TIERS,
    route_model,
    get_model_tiers,
    reset_model_tiers_to_default,
)
from app.features.ai.team.team_schemas import (
    TeamConfig,
    TeamRole,
    TeamTask,
    HandoffArtifact,
)
from app.features.ai.team.orchestrator import TeamOrchestrator


def test_classify_hard_task():
    """Verify security, auth, crypto, and algorithmic tasks classify as HARD."""
    desc = "Implement JWT authentication with refresh token rotation and bcrypt password encryption"
    res = classify_task_difficulty(desc)
    assert res["difficulty"] == "HARD"
    assert res["confidence"] >= 0.70
    assert any("high-complexity" in r.lower() or "auth" in r.lower() for r in res["reasons"])


def test_classify_easy_task():
    """Verify boilerplate, tests, docs, and config tasks classify as EASY."""
    desc = "Write boilerplate unit tests and update README docs and config files"
    res = classify_task_difficulty(desc)
    assert res["difficulty"] == "EASY"
    assert res["confidence"] >= 0.70
    assert any("low-complexity" in r.lower() or "test" in r.lower() for r in res["reasons"])


def test_classify_medium_task():
    """Verify standard features, components, and CRUD endpoints classify as MEDIUM."""
    desc = "Create user profile settings component and CRUD API endpoint"
    res = classify_task_difficulty(desc)
    assert res["difficulty"] == "MEDIUM"
    assert res["confidence"] >= 0.60


def test_route_model_hard_to_smart_provider():
    """Verify HARD difficulty routes to smart/frontier models."""
    reset_model_tiers_to_default()
    route = route_model("HARD")
    assert route["tier"] == "HARD"
    full_model = f"{route['provider']}/{route['model']}"
    assert full_model in MODEL_TIERS["HARD"]
    assert len(route["fallback_models"]) > 0


def test_route_model_easy_to_cheap_provider():
    """Verify EASY difficulty routes to cheap/fast models."""
    reset_model_tiers_to_default()
    route = route_model("EASY")
    assert route["tier"] == "EASY"
    full_model = f"{route['provider']}/{route['model']}"
    assert full_model in MODEL_TIERS["EASY"]
    assert len(route["fallback_models"]) > 0


def test_route_model_fallback_on_unavailable():
    """Verify router falls back within tier or downgrades/cascades when providers are filtered."""
    reset_model_tiers_to_default()

    # 1. Fallback within same tier: GLM is excluded, Anthropic should be chosen for HARD
    route1 = route_model("HARD", available_providers=["anthropic", "openai"])
    assert route1["tier"] == "HARD"
    assert route1["provider"] == "anthropic"
    assert route1["model"] == "claude-opus-5"

    # 2. Fallback to adjacent tier: None of the HARD providers available, only Google is available
    route2 = route_model("HARD", available_providers=["google"])
    assert route2["provider"] == "google"
    assert route2["model"] == "gemini-3.1-pro"
    assert route2["tier"] == "MEDIUM"


@pytest.mark.asyncio
async def test_orchestrator_uses_smart_router_when_enabled(tmp_path):
    """Verify TeamOrchestrator classifies tasks and assigns smart models when enabled."""
    emitted_metrics: list[dict] = []

    async def mock_executor(task: TeamTask, prior_handoffs: list[HandoffArtifact]) -> dict:
        return {
            "role": task.role.value if hasattr(task.role, "value") else str(task.role),
            "status": "completed",
            "assigned_model": task.context.get("assigned_model") if task.context else None,
            "difficulty": task.context.get("difficulty") if task.context else None,
        }

    config = TeamConfig(
        workspace=str(tmp_path),
        smart_router_enabled=True,
        max_concurrency=2,
    )
    orchestrator = TeamOrchestrator(
        team_config=config,
        task_executor=mock_executor,
    )
    orchestrator.subscribe(
        lambda ev: emitted_metrics.append(ev.data) if ev.event == "team_metrics" else None
    )

    hard_task = TeamTask(
        task_id="task_hard_auth",
        job_id="job_smart_router",
        title="Implement cryptographic zero-knowledge authentication and security invariants",
        role=TeamRole.ARCHITECT,
        dependencies=[],
    )
    easy_task = TeamTask(
        task_id="task_easy_docs",
        job_id="job_smart_router",
        title="Add boilerplate comments and update documentation formatting",
        role=TeamRole.CODER,
        dependencies=["task_hard_auth"],
    )

    result = await orchestrator.execute_dag([hard_task, easy_task], job_id="job_smart_router")
    assert result["status"] == "completed"
    assert len(emitted_metrics) == 2

    # Check hard task metric
    hard_metric = next(m for m in emitted_metrics if m["task_id"] == "task_hard_auth")
    assert hard_metric["difficulty"] == "HARD"
    assert hard_metric["tier"] == "HARD"
    assert hard_metric["assigned_model"] in MODEL_TIERS["HARD"]

    # Check easy task metric
    easy_metric = next(m for m in emitted_metrics if m["task_id"] == "task_easy_docs")
    assert easy_metric["difficulty"] == "EASY"
    assert easy_metric["tier"] == "EASY"
    assert easy_metric["assigned_model"] in MODEL_TIERS["EASY"]

    # Verify task contexts retained smart router details
    assert hard_task.context["difficulty"] == "HARD"
    assert easy_task.context["difficulty"] == "EASY"
