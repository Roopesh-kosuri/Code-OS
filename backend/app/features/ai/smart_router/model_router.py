from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default Model Tiers as specified
DEFAULT_MODEL_TIERS: dict[str, list[str]] = {
    "HARD": [
        "glm/glm-5.2",
        "anthropic/claude-opus-5",
        "openai/gpt-5.6",
    ],
    "MEDIUM": [
        "anthropic/claude-sonnet-5",
        "openai/gpt-5",
        "google/gemini-3.1-pro",
        "nvidia/llama-3.3-70b",
    ],
    "EASY": [
        "groq/llama-3.3-70b",
        "google/gemini-3.5-flash",
        "glm/glm-air",
        "groq/llama-3.1-8b",
    ],
}

# Active working copy of model tiers (configurable at runtime via admin API)
MODEL_TIERS: dict[str, list[str]] = {
    k: list(v) for k, v in DEFAULT_MODEL_TIERS.items()
}

TIER_ORDER = ["HARD", "MEDIUM", "EASY"]


def parse_model_string(model_str: str) -> tuple[str, str]:
    """Parse 'provider/model' or default provider."""
    if "/" in model_str:
        parts = model_str.split("/", 1)
        return parts[0].strip().lower(), parts[1].strip()
    return "openai", model_str.strip()


def get_model_tiers() -> dict[str, list[str]]:
    """Return a copy of the current model tiers configuration."""
    return {k: list(v) for k, v in MODEL_TIERS.items()}


def update_model_tiers(tiers: dict[str, list[str]]) -> dict[str, list[str]]:
    """Update active model tiers configuration."""
    global MODEL_TIERS
    for tier_name in ["HARD", "MEDIUM", "EASY"]:
        if tier_name in tiers and isinstance(tiers[tier_name], list):
            MODEL_TIERS[tier_name] = [str(m).strip() for m in tiers[tier_name] if str(m).strip()]
    return get_model_tiers()


def reset_model_tiers_to_default() -> dict[str, list[str]]:
    """Reset model tiers to default configuration."""
    global MODEL_TIERS
    MODEL_TIERS = {k: list(v) for k, v in DEFAULT_MODEL_TIERS.items()}
    return get_model_tiers()


def validate_model_tiers_against_catalog() -> list[dict[str, Any]]:
    """
    Validate active model tiers against known provider models in PROVIDER_CATALOG.
    Returns list of warnings for uncatalogued or unavailable models.
    """
    from ..catalog import PROVIDER_CATALOG
    warnings = []
    for tier, models in MODEL_TIERS.items():
        for m_str in models:
            provider, model_id = parse_model_string(m_str)
            catalog_models = PROVIDER_CATALOG.get(provider, [])
            match = next((m for m in catalog_models if m.id == model_id or m.name.lower() == model_id.lower()), None)
            if match is None:
                msg = f"Configured model '{m_str}' in tier '{tier}' is not in provider catalog."
                logger.warning("smart_router: %s", msg)
                warnings.append({"tier": tier, "model": m_str, "warning": msg, "type": "missing"})
            elif not match.available:
                msg = f"Configured model '{m_str}' in tier '{tier}' is marked unavailable in catalog."
                logger.warning("smart_router: %s", msg)
                warnings.append({"tier": tier, "model": m_str, "warning": msg, "type": "unavailable"})
    return warnings


def route_model(
    task_difficulty: str,
    available_providers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Route a task of given difficulty to the optimal model and provider.

    Fallback logic:
    1. Look in the target difficulty tier.
    2. If provider is unavailable or filtered, try subsequent models in the same tier.
    3. If all models in the tier are unavailable, cascade to adjacent tiers
       (HARD -> MEDIUM -> EASY, EASY -> MEDIUM -> HARD).

    Returns:
        {
            "provider": str,
            "model": str,
            "tier": str,
            "fallback_models": list[str]
        }
    """
    diff_upper = str(task_difficulty).upper().strip()
    if diff_upper not in MODEL_TIERS:
        diff_upper = "MEDIUM"

    normalized_providers: Optional[set[str]] = None
    if available_providers is not None:
        normalized_providers = {str(p).lower().strip() for p in available_providers}

    # Define tier evaluation sequence based on starting tier
    if diff_upper == "HARD":
        tier_sequence = ["HARD", "MEDIUM", "EASY"]
    elif diff_upper == "EASY":
        tier_sequence = ["EASY", "MEDIUM", "HARD"]
    else:
        tier_sequence = ["MEDIUM", "EASY", "HARD"]

    candidate_models: list[tuple[str, str, str]] = []  # (tier, provider, model)

    for tier in tier_sequence:
        models_in_tier = MODEL_TIERS.get(tier, [])
        for m_str in models_in_tier:
            p, m = parse_model_string(m_str)
            if normalized_providers is None or p in normalized_providers:
                candidate_models.append((tier, p, m))

    if not candidate_models:
        # Extreme fallback if all providers filtered out
        default_model = MODEL_TIERS.get(diff_upper, ["openai/gpt-4o"])[0]
        p, m = parse_model_string(default_model)
        return {
            "provider": p,
            "model": m,
            "tier": diff_upper,
            "fallback_models": [],
        }

    # Selected primary model is the top candidate
    selected_tier, selected_provider, selected_model = candidate_models[0]

    # Collect fallback models (remaining candidates)
    fallback_models = [f"{p}/{m}" for _, p, m in candidate_models[1:]]

    return {
        "provider": selected_provider,
        "model": selected_model,
        "tier": selected_tier,
        "fallback_models": fallback_models,
    }
