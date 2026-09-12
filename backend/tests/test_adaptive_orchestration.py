"""
test_adaptive_orchestration.py - Regression test suite for Phase 7: Adaptive Orchestration.

Tests:
E1: test_escalation_classifier_detects_multifile_refactor
E2: test_escalation_classifier_skips_simple_task
E3: test_escalation_keywords_force_check
E4: test_escalation_pipeline_flags_complex_task
E5: test_escalation_handoff_creates_job
E6: test_escalation_stats_endpoint
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.features.ai.intelligence.task_classifier import (
    classify_task,
    escalation_classifier,
    ESCALATION_KEYWORDS,
)
from app.features.ai.intelligence.escalation_tracker import (
    reset_escalation_tracker,
    record_escalation_initiated,
    record_escalation_completed,
    record_escalation_declined,
    get_escalation_stats,
)


@pytest.fixture(autouse=True)
def clean_tracker():
    reset_escalation_tracker()
    yield
    reset_escalation_tracker()


def test_escalation_classifier_detects_multifile_refactor():
    """E1: Multi-file refactor across several components triggers escalation with confidence > 0.7."""
    task = "Refactor the authentication system across handler, validators, sessions, and rate_limiter"
    result = escalation_classifier(task)

    assert result["should_escalate"] is True
    assert result["confidence"] > 0.7
    assert len(result["triggers"]) >= 2
    assert "multi_file_refactor" in result["triggers"] or "security_hardening" in result["triggers"]


def test_escalation_classifier_skips_simple_task():
    """E2: Simple tasks do not trigger escalation and have low confidence (< 0.3)."""
    task = "Fix typo in README"
    result = escalation_classifier(task)

    assert result["should_escalate"] is False
    assert result["confidence"] < 0.3


def test_escalation_keywords_force_check():
    """E3: Keywords like 'team' or 'full-stack' force escalation check and trigger escalation."""
    task = "Build a full-stack feature with team approach"
    result = escalation_classifier(task)

    # Both cross_layer_feature and explicit_team_request should be triggered
    assert result["should_escalate"] is True
    assert result["confidence"] >= 0.5
    assert "explicit_team_request" in result["triggers"]
    assert "cross_layer_feature" in result["triggers"]


def test_escalation_pipeline_flags_complex_task():
    """E4: classify_task returns escalation_recommended: true and escalation_reasoning."""
    task = "Refactor the authentication system across handler, validators, sessions, and rate_limiter"
    classification = classify_task(task, use_llm=False)

    assert classification.get("escalation_recommended") is True
    assert "escalation_reasoning" in classification
    assert len(classification["escalation_reasoning"]) > 0
    assert classification.get("escalation_confidence", 0.0) > 0.7


@pytest.mark.asyncio
async def test_escalation_handoff_creates_job(async_client):
    """E5: POST /api/team/jobs/from-rony creates job with enriched context, priority=high."""
    payload = {
        "task": "Implement complete OAuth2 flow across auth, session, and db models",
        "conversation_context": [
            {"role": "user", "content": "I need help building OAuth2"},
            {"role": "assistant", "content": "This is a complex multi-file task"},
        ],
        "active_files": ["backend/app/auth.py", "backend/app/session.py"],
        "workspace": ".",
        "escalation_reason": "Task involves multi-file refactor and security hardening",
        "user_preferences": {"model": "claude-3-5-sonnet-latest"},
    }
    res = await async_client.post("/api/team/jobs/from-rony", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["priority"] == "high"
    assert data["job_id"].startswith("team_")
    assert f"/ws/team/jobs/{data['job_id']}" in data["ws_url"]
    assert data.get("task_count", 0) == 5


@pytest.mark.asyncio
async def test_escalation_stats_endpoint(async_client):
    """E6: GET /api/intelligence/escalation-stats returns counts and success rate."""
    # Seed tracker
    record_escalation_initiated("team_123", "Complex task", "multi-file refactor")
    record_escalation_completed("team_123", duration=42.5, success=True)
    record_escalation_declined("Smaller task", rony_succeeded=True)

    res = await async_client.get("/api/intelligence/escalation-stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_escalations"] == 2
    assert data["accepted"] == 1
    assert data["declined"] == 1
    assert data["success_rate"] == 1.0
    assert data["avg_duration"] == 42.5

