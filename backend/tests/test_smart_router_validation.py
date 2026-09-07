import pytest
from app.features.ai.smart_router.model_router import (
    validate_model_tiers_against_catalog,
    route_model,
    reset_model_tiers_to_default,
    update_model_tiers,
)
from app.features.ai.smart_router.difficulty_classifier import classify_task_difficulty


def test_model_tiers_validated_against_catalog():
    # Calling validation returns structured warnings for any uncatalogued/unavailable models
    warnings = validate_model_tiers_against_catalog()
    assert isinstance(warnings, list)
    assert len(warnings) > 0
    # Confirm structure
    for w in warnings:
        assert "tier" in w
        assert "model" in w
        assert "warning" in w


def test_difficulty_classifier_documented_as_heuristic():
    doc = classify_task_difficulty.__doc__ or ""
    assert "heuristic" in doc.lower()
    res = classify_task_difficulty("Write unit tests for authentication")
    assert "difficulty" in res


def test_router_fallback_on_unavailable_model():
    reset_model_tiers_to_default()
    # Configure an unavailable primary provider
    res = route_model("HARD", available_providers=["openai"])
    assert res["provider"] == "openai"
    assert "model" in res
