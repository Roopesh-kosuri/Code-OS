from __future__ import annotations

import logging
from typing import Any, Optional

from ..providers.catalog import get_verified_models

logger = logging.getLogger(__name__)

# Default Model Tiers with verified presets only
DEFAULT_MODEL_TIERS: dict[str, list[str]] = {
    "HARD": [
        "anthropic/claude-sonnet-4-5",
        "openai/gpt-4o",
        "nvidia-nim/meta/llama-3.2-11b-vision-instruct",
    ],
    "MEDIUM": [
        "deepseek/deepseek-chat",
        "mistral/mistral-large-latest",
        "gemini/gemini-2.5-flash",
    ],
    "EASY": [
        "groq/openai/gpt-oss-120b",
        "gemini/gemini-2.5-flash",
    ],
}

# Active working copy of model tiers (configurable at runtime via admin API)
MODEL_TIERS: dict[str, list[str]] = {
    k: list(v) for k, v in DEFAULT_MODEL_TIERS.items()
}

TIER_ORDER = ["HARD", "MEDIUM", "EASY"]

# Global store for the most recent routing decision
LAST_ROUTING_DECISION: dict[str, Any] = {
    "provider": "openai",
    "model": "gpt-4o",
    "tier": "HARD",
    "requested_tier": "HARD",
    "fallback_models": [],
    "skipped": [],
    "reason": "Default initialized",
}


def _normalize_provider(prov: str) -> str:
    """Normalize provider name across aliases."""
    p = prov.lower().strip()
    if p in ("google", "gemini"):
        return "gemini"
    if p in ("nvidia", "nvidia-nim"):
        return "nvidia-nim"
    return p


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


def get_last_routing_decision() -> dict[str, Any]:
    """Return a copy of the most recent routing decision."""
    return dict(LAST_ROUTING_DECISION)


def validate_model_tiers_against_catalog() -> list[dict[str, Any]]:
    """Validate active model tiers against live verified models.

    Returns list of warnings for uncatalogued or unavailable models.
    """
    warnings = []
    for tier, models in MODEL_TIERS.items():
        for m_str in models:
            provider, model_id = parse_model_string(m_str)
            norm_p = _normalize_provider(provider)
            verified = get_verified_models(provider) or get_verified_models(norm_p)
            model_lower = model_id.lower()
            match = any(
                v.lower() == model_lower
                or v.lower().endswith("/" + model_lower)
                or model_lower.endswith("/" + v.lower())
                for v in verified
            )
            if not match:
                msg = f"Configured model '{m_str}' in tier '{tier}' is not currently verified on provider '{provider}'."
                logger.warning("smart_router: %s", msg)
                warnings.append({"tier": tier, "model": m_str, "warning": msg, "type": "unverified"})
    return warnings


def route_model(
    task_difficulty: str,
    available_providers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Route a task of given difficulty to the optimal verified model and provider.

    Catalog-aware routing logic:
    1. Filter each tier list against get_verified_models(provider).
    2. Skip unverified or filtered models (recording reasons).
    3. Cascade: HARD -> MEDIUM -> EASY (or EASY -> MEDIUM -> HARD).
    4. If ALL tiers empty, fall back to provider default preset.
    5. Record and return routing decision event with skipped list and reason.
    """
    global LAST_ROUTING_DECISION

    diff_upper = str(task_difficulty).upper().strip()
    if diff_upper not in MODEL_TIERS:
        diff_upper = "MEDIUM"

    normalized_providers: Optional[set[str]] = None
    if available_providers is not None:
        normalized_providers = set()
        for p in available_providers:
            clean = str(p).lower().strip()
            normalized_providers.add(clean)
            normalized_providers.add(_normalize_provider(clean))

    # Define tier evaluation sequence based on starting tier
    if diff_upper == "HARD":
        tier_sequence = ["HARD", "MEDIUM", "EASY"]
    elif diff_upper == "EASY":
        tier_sequence = ["EASY", "MEDIUM", "HARD"]
    else:
        tier_sequence = ["MEDIUM", "EASY", "HARD"]

    candidate_models: list[tuple[str, str, str]] = []  # (tier, provider, model)
    skipped: list[dict[str, str]] = []

    for tier in tier_sequence:
        models_in_tier = MODEL_TIERS.get(tier, [])
        for m_str in models_in_tier:
            p, m = parse_model_string(m_str)
            norm_p = _normalize_provider(p)

            # Check if provider is available / allowed
            if normalized_providers is not None:
                if p not in normalized_providers and norm_p not in normalized_providers:
                    skipped.append({
                        "model": m_str,
                        "reason": f"Provider '{p}' not in available providers list",
                    })
                    continue

            # Catalog verification check
            verified_list = get_verified_models(p)
            if not verified_list:
                verified_list = get_verified_models(norm_p)

            m_lower = m.lower()
            is_verified = any(
                v.lower() == m_lower
                or v.lower().endswith("/" + m_lower)
                or m_lower.endswith("/" + v.lower())
                for v in verified_list
            )

            if not is_verified:
                reason = f"Model '{m}' unavailable or unverified on provider '{p}'"
                logger.warning("smart_router: skipping %s: %s", m_str, reason)
                skipped.append({"model": m_str, "reason": reason})
                continue

            candidate_models.append((tier, p, m))

    # Determine selection and fallback
    if not candidate_models:
        # Fallback to provider default preset
        selected_provider = "openai"
        selected_model = "gpt-4o"
        selected_tier = diff_upper
        fallback_models: list[str] = []
        reason = (
            f"All tiers empty or unverified; fell back to default preset "
            f"{selected_provider}/{selected_model}"
        )
    else:
        selected_tier, selected_provider, selected_model = candidate_models[0]
        fallback_models = [f"{cp}/{cm}" for _, cp, cm in candidate_models[1:]]
        if selected_tier == diff_upper:
            reason = f"Routed {diff_upper} task to verified model {selected_provider}/{selected_model}"
        else:
            reason = (
                f"{diff_upper} tier unavailable ({len(skipped)} models skipped); "
                f"cascaded to {selected_tier} tier: {selected_provider}/{selected_model}"
            )

    decision = {
        "provider": selected_provider,
        "model": selected_model,
        "tier": selected_tier,
        "requested_tier": diff_upper,
        "fallback_models": fallback_models,
        "skipped": skipped,
        "reason": reason,
    }

    LAST_ROUTING_DECISION = dict(decision)
    return decision
