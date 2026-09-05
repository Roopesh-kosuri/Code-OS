"""
test_phase4b_moonshot.py
Comprehensive test suite verifying Moonshot AI (Kimi) provider registration,
all Kimi models (8K, 32K, 128K, Vision, K2 series, Kimi-Thinking, K2.5 unreleased),
tier routing, REST endpoints, and settings persistence.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.auth import get_token
from app.features.ai.catalog import (
    PROVIDER_CATALOG,
    TIER_ROUTING,
    get_model_metadata,
    get_all_providers,
)
from app.features.ai.model_catalog_service import model_catalog_service
from app.features.ai.provider_health import (
    provider_health_tracker,
    DEFAULT_FALLBACK_ORDER,
    DEFAULT_PROVIDER_MODELS,
    DEFAULT_PROVIDER_URLS,
)
from app.features.settings.service import get_setting, set_setting, store_api_key, get_api_key


def test_moonshot_provider_registered():
    """Verify Moonshot AI is registered in PROVIDER_CATALOG and fallback urls."""
    assert "moonshot" in PROVIDER_CATALOG
    models = PROVIDER_CATALOG["moonshot"]
    assert len(models) >= 12
    assert "moonshot" in DEFAULT_PROVIDER_URLS
    assert DEFAULT_PROVIDER_URLS["moonshot"] == "https://api.moonshot.ai/v1"


def test_kimi_model_list():
    """Verify all Kimi models, context windows, pricing, and capabilities."""
    models_by_id = {m.id: m for m in PROVIDER_CATALOG["moonshot"]}

    # Moonshot v1 standard
    assert "moonshot-v1-8k" in models_by_id
    assert models_by_id["moonshot-v1-8k"].context_window == 8192
    assert models_by_id["moonshot-v1-8k"].tier == "low"
    assert models_by_id["moonshot-v1-8k"].available is True

    assert "moonshot-v1-32k" in models_by_id
    assert models_by_id["moonshot-v1-32k"].context_window == 32768
    assert models_by_id["moonshot-v1-32k"].tier == "medium"

    assert "moonshot-v1-128k" in models_by_id
    assert models_by_id["moonshot-v1-128k"].context_window == 128000
    assert models_by_id["moonshot-v1-128k"].tier == "high"

    # Vision variants
    assert "moonshot-v1-8k-vision-preview" in models_by_id
    assert models_by_id["moonshot-v1-8k-vision-preview"].vision is True

    assert "moonshot-v1-32k-vision-preview" in models_by_id
    assert models_by_id["moonshot-v1-32k-vision-preview"].vision is True

    assert "moonshot-v1-128k-vision-preview" in models_by_id
    assert models_by_id["moonshot-v1-128k-vision-preview"].vision is True

    # Kimi K2 series
    assert "kimi-k2-0711-preview" in models_by_id
    assert models_by_id["kimi-k2-0711-preview"].context_window == 128000
    assert models_by_id["kimi-k2-0711-preview"].tier == "medium"

    assert "kimi-k2-0905-preview" in models_by_id
    assert models_by_id["kimi-k2-0905-preview"].context_window == 128000

    assert "kimi-k2-turbo-preview" in models_by_id
    assert models_by_id["kimi-k2-turbo-preview"].tier == "high"

    assert "kimi-k2-thinking" in models_by_id
    assert models_by_id["kimi-k2-thinking"].reasoning is True
    assert models_by_id["kimi-k2-thinking"].tier == "high"

    # Unreleased model
    assert "kimi-k2.5" in models_by_id
    assert models_by_id["kimi-k2.5"].context_window == 256000
    assert models_by_id["kimi-k2.5"].available is False

    # Aliases
    assert "kimi-latest" in models_by_id
    assert "moonshot-v1-auto" in models_by_id


def test_kimi_tier_routing():
    """Verify Kimi models are routed to correct tiers."""
    assert "moonshot-v1-8k" in TIER_ROUTING["low"]
    assert "moonshot-v1-32k" in TIER_ROUTING["medium"]
    assert "kimi-k2-0711-preview" in TIER_ROUTING["medium"]
    assert "moonshot-v1-128k" in TIER_ROUTING["high"]
    assert "kimi-k2-thinking" in TIER_ROUTING["high"]
    assert "kimi-latest" in TIER_ROUTING["high"]


@pytest.mark.asyncio
async def test_kimi_settings_key():
    """Verify moonshot_api_key can be saved and retrieved securely."""
    await store_api_key("moonshot", "sk-moonshot-test-key-abc123xyz")
    stored_key = await get_api_key("moonshot")
    assert stored_key == "sk-moonshot-test-key-abc123xyz"


@pytest.mark.asyncio
async def test_moonshot_rest_endpoints():
    """Verify GET /api/ai/providers and GET /api/ai/providers/moonshot/models endpoints."""
    transport = ASGITransport(app=app)
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Check providers list
        res = await ac.get("/api/ai/providers", headers=headers)
        assert res.status_code == 200
        providers = res.json()
        moonshot_entry = next((p for p in providers if p["provider"] == "moonshot"), None)
        assert moonshot_entry is not None
        assert moonshot_entry["total_models"] >= 12

        # Check models endpoint
        res_models = await ac.get("/api/ai/providers/moonshot/models", headers=headers)
        assert res_models.status_code == 200
        models = res_models.json()
        model_ids = [m["id"] for m in models]
        assert "moonshot-v1-128k" in model_ids
        assert "kimi-k2-thinking" in model_ids


@pytest.mark.asyncio
async def test_moonshot_model_validation():
    """Verify ModelCatalogService validates Moonshot models."""
    is_valid, _, _ = await model_catalog_service.validate_model_for_provider("moonshot", "moonshot-v1-128k")
    assert is_valid is True

    is_valid, _, _ = await model_catalog_service.validate_model_for_provider("moonshot", "kimi-k2-thinking")
    assert is_valid is True

    is_invalid, err, _ = await model_catalog_service.validate_model_for_provider("moonshot", "nonexistent-kimi-xyz")
    assert is_invalid is False
    assert "not available on moonshot" in err
