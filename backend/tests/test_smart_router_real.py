"""
test_smart_router_real.py — Regression tests for the real LLM & intelligent task classifier.

Verifies:
1. test_classifier_uses_llm: verify LLM call made (mock provider/callable)
2. test_classifier_returns_valid_tier: tier in {HARD, MEDIUM, EASY}
3. test_classifier_explainable: reasoning field present and populated in response
4. test_context_window_awareness: large task (>100K tokens) routes to large-context model
5. test_price_awareness: budget-constrained task (>=80% spend guard) routes to cheaper tier
6. test_model_tiers_validated: all tier models exist in live catalog
"""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from app.features.ai.intelligence.task_classifier import (
    classify_task,
    set_llm_classifier_fn,
    reset_llm_classifier_fn,
)
from app.features.ai.smart_router.model_router import (
    validate_model_tiers_against_catalog,
    DEFAULT_MODEL_TIERS,
    reset_model_tiers_to_default,
)


def test_classifier_uses_llm():
    """Verify that classify_task invokes the LLM callable when provided."""
    mock_llm = MagicMock(return_value={"tier": "HARD", "reasoning": "Cryptographic architecture detected by LLM"})

    res = classify_task(
        "Design zero-knowledge rollup proofs for smart contracts",
        llm_fn=mock_llm,
        use_llm=True,
    )

    assert mock_llm.called
    assert res["method"] == "llm"
    assert res["tier"] == "HARD"
    assert "Cryptographic architecture" in res["reasoning"]


def test_classifier_returns_valid_tier():
    """Verify that classify_task always returns a valid tier in {HARD, MEDIUM, EASY}."""
    # Test HARD
    res_hard = classify_task("Implement OAuth2 authentication and JWT encryption with security policy")
    assert res_hard["tier"] in ("HARD", "MEDIUM", "EASY")
    assert res_hard["tier"] == "HARD"

    # Test EASY
    res_easy = classify_task("Fix typo in README documentation and bump version in package.json")
    assert res_easy["tier"] in ("HARD", "MEDIUM", "EASY")
    assert res_easy["tier"] == "EASY"

    # Test MEDIUM
    res_med = classify_task("Add user settings CRUD endpoint and frontend table component")
    assert res_med["tier"] in ("HARD", "MEDIUM", "EASY")
    assert res_med["tier"] == "MEDIUM"


def test_classifier_explainable():
    """Verify that reasoning field is populated and explainable in the response."""
    res = classify_task("Implement payment checkout with stripe webhook signature verification")
    assert "reasoning" in res
    assert isinstance(res["reasoning"], str)
    assert len(res["reasoning"]) > 0
    # Must explain the keywords or criteria
    assert any(k in res["reasoning"].lower() for k in ("payment", "stripe", "keywords", "complexity"))


def test_context_window_awareness():
    """Verify that tasks exceeding 100K tokens route to large-context models."""
    # Context with 30,000 LOC -> estimated ~120,000 tokens (>100K)
    res_large = classify_task(
        "Refactor global error handling across repository",
        context={"total_loc": 30000, "estimated_tokens": 120000},
    )
    assert res_large["context_window_tier"] == "large"
    assert "claude" in res_large["recommended_model"].lower() or "gemini" in res_large["recommended_model"].lower()
    assert "100K" in res_large["reasoning"]

    # Compact task (<10K tokens)
    res_compact = classify_task(
        "Fix single line typo",
        context={"total_loc": 20, "estimated_tokens": 150},
    )
    assert res_compact["context_window_tier"] == "compact"
    assert "groq" in res_compact["recommended_model"].lower() or "gemini" in res_compact["recommended_model"].lower()


def test_price_awareness():
    """Verify that tasks with >= 80% budget spend guard route to cheaper tiers to save cost."""
    # Normally a hard task
    res_normal = classify_task("Implement crypto encryption and security invariants", budget_percent=20.0)
    assert res_normal["tier"] == "HARD"
    assert res_normal["budget_downgraded"] is False

    # Same hard task with 85% budget guard
    res_budget = classify_task("Implement crypto encryption and security invariants", budget_percent=85.0)
    assert res_budget["tier"] == "EASY"
    assert res_budget["budget_downgraded"] is True
    assert "save budget" in res_budget["reasoning"].lower()


def test_model_tiers_validated():
    """Verify that model tiers in smart router are validated against live catalog."""
    reset_model_tiers_to_default()
    warnings = validate_model_tiers_against_catalog()
    assert isinstance(warnings, list)
    # Default verified tiers should produce zero unverified warnings
    assert len(warnings) == 0
