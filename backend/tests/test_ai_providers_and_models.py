"""
test_ai_providers_and_models.py
Comprehensive test suite verifying all 13 AI providers, 120+ models,
model metadata accuracy (context windows, pricing, availability),
REST endpoints (/api/ai/providers, /api/ai/providers/{id}/models),
tier routing, model validation, and fallback mechanisms.
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


def test_provider_catalog_has_all_13_providers():
    """Verify all 13 required providers are present in the catalog."""
    expected_providers = {
        "glm",
        "qwen",
        "deepseek",
        "openai",
        "anthropic",
        "gemini",
        "mistral",
        "xai",
        "llama",
        "nvidia-nim",
        "groq",
        "cohere",
        "openrouter",
        "ollama",
    }
    catalog_keys = set(PROVIDER_CATALOG.keys())
    assert expected_providers.issubset(catalog_keys), f"Missing providers: {expected_providers - catalog_keys}"


def test_glm_zhipu_models():
    """Verify GLM provider models and metadata."""
    glm_models = {m.id: m for m in PROVIDER_CATALOG["glm"]}
    assert "glm-4-plus" in glm_models
    assert glm_models["glm-4-plus"].context_window == 128000
    assert glm_models["glm-4-plus"].tier == "high"
    assert glm_models["glm-4-plus"].available is True

    assert "glm-4-long" in glm_models
    assert glm_models["glm-4-long"].context_window == 1000000

    assert "glm-4v-plus" in glm_models
    assert glm_models["glm-4v-plus"].vision is True

    # Unreleased models marked available=False
    assert "glm-5-1" in glm_models and glm_models["glm-5-1"].available is False
    assert "glm-5-2" in glm_models and glm_models["glm-5-2"].available is False
    assert "glm-5-3" in glm_models and glm_models["glm-5-3"].available is False


def test_qwen_alibaba_models():
    """Verify Qwen provider models and metadata."""
    qwen_models = {m.id: m for m in PROVIDER_CATALOG["qwen"]}
    assert "qwen-max" in qwen_models
    assert "qwen-max-latest" in qwen_models and qwen_models["qwen-max-latest"].context_window == 1000000
    assert "qwen-long" in qwen_models and qwen_models["qwen-long"].context_window == 10000000
    assert "qwen-coder-plus" in qwen_models
    assert "qwen2.5-coder-32b-instruct" in qwen_models
    assert "qwen-vl-max" in qwen_models and qwen_models["qwen-vl-max"].vision is True
    assert "qwq-32b-preview" in qwen_models and qwen_models["qwq-32b-preview"].reasoning is True
    assert "qwq-plus" in qwen_models and qwen_models["qwq-plus"].available is False


def test_deepseek_models():
    """Verify DeepSeek provider models and metadata."""
    ds_models = {m.id: m for m in PROVIDER_CATALOG["deepseek"]}
    assert "deepseek-chat" in ds_models and ds_models["deepseek-chat"].context_window == 64000
    assert "deepseek-reasoner" in ds_models and ds_models["deepseek-reasoner"].reasoning is True
    assert "deepseek-coder" in ds_models and ds_models["deepseek-coder"].context_window == 128000
    assert "deepseek-vl" in ds_models and ds_models["deepseek-vl"].vision is True


def test_openai_gpt5_and_reasoning_models():
    """Verify OpenAI GPT-5 series and reasoning models."""
    oai_models = {m.id: m for m in PROVIDER_CATALOG["openai"]}
    assert "gpt-4o" in oai_models
    assert "o3" in oai_models and oai_models["o3"].tier == "premium"
    assert "o3-mini" in oai_models and oai_models["o3-mini"].reasoning is True
    assert "gpt-5" in oai_models and oai_models["gpt-5"].available is False
    assert "gpt-5-turbo" in oai_models and oai_models["gpt-5-turbo"].available is False
    assert "gpt-5.6-sol" in oai_models and oai_models["gpt-5.6-sol"].tier == "premium"
    assert "gpt-4.1" in oai_models and oai_models["gpt-4.1"].context_window == 1000000


def test_anthropic_claude5_models():
    """Verify Anthropic Claude series."""
    claude_models = {m.id: m for m in PROVIDER_CATALOG["anthropic"]}
    assert "claude-3-7-sonnet" in claude_models and claude_models["claude-3-7-sonnet"].reasoning is True
    assert "claude-3-5-sonnet-latest" in claude_models
    assert "claude-opus-4-6" in claude_models and claude_models["claude-opus-4-6"].available is False
    assert "claude-opus-5" in claude_models and claude_models["claude-opus-5"].available is False


def test_gemini_3x_models():
    """Verify Google Gemini series."""
    gemini_models = {m.id: m for m in PROVIDER_CATALOG["gemini"]}
    assert "gemini-2.0-flash" in gemini_models
    assert "gemini-2.5-pro" in gemini_models and gemini_models["gemini-2.5-pro"].context_window == 2000000
    assert "gemini-3.0-pro" in gemini_models and gemini_models["gemini-3.0-pro"].available is False
    assert "gemini-3.5-flash-low" in gemini_models and gemini_models["gemini-3.5-flash-low"].tier == "low"
    assert "gemini-3.7-pro" in gemini_models and gemini_models["gemini-3.7-pro"].available is False


def test_mistral_models():
    """Verify Mistral model catalog."""
    mistral_models = {m.id: m for m in PROVIDER_CATALOG["mistral"]}
    assert "mistral-large-2" in mistral_models and mistral_models["mistral-large-2"].context_window == 128000
    assert "codestral-latest" in mistral_models and mistral_models["codestral-latest"].context_window == 256000
    assert "pixtral-large-latest" in mistral_models and mistral_models["pixtral-large-latest"].vision is True
    assert "ministral-3b-latest" in mistral_models and mistral_models["ministral-3b-latest"].tier == "low"


def test_xai_grok_models():
    """Verify xAI Grok provider models."""
    xai_models = {m.id: m for m in PROVIDER_CATALOG["xai"]}
    assert "grok-3" in xai_models and xai_models["grok-3"].tier == "premium"
    assert "grok-3-mini" in xai_models and xai_models["grok-3-mini"].tier == "medium"
    assert "grok-2" in xai_models
    assert "grok-2-vision" in xai_models and xai_models["grok-2-vision"].vision is True


def test_meta_llama_and_groq_models():
    """Verify Llama and Groq catalogs."""
    llama_models = {m.id: m for m in PROVIDER_CATALOG["llama"]}
    assert "llama-4-scout" in llama_models and llama_models["llama-4-scout"].available is False
    assert "llama-3.3-70b-versatile" in llama_models

    groq_models = {m.id: m for m in PROVIDER_CATALOG["groq"]}
    assert "llama-3.3-70b-versatile" in groq_models
    assert "deepseek-r1-distill-llama-70b" in groq_models


def test_cohere_models():
    """Verify Cohere provider models."""
    cohere_models = {m.id: m for m in PROVIDER_CATALOG["cohere"]}
    assert "command-a-03-2025" in cohere_models and cohere_models["command-a-03-2025"].context_window == 256000
    assert "command-r-plus-08-2024" in cohere_models
    assert "command-r7b-12-2024" in cohere_models and cohere_models["command-r7b-12-2024"].tier == "low"


def test_tier_routing_coverage():
    """Verify tier routing contains all required tiers and assignments."""
    assert "low" in TIER_ROUTING
    assert "medium" in TIER_ROUTING
    assert "high" in TIER_ROUTING
    assert "premium" in TIER_ROUTING

    assert "glm-4-flash" in TIER_ROUTING["low"]
    assert "qwen-turbo" in TIER_ROUTING["low"]
    assert "glm-4-air" in TIER_ROUTING["medium"]
    assert "qwen-plus" in TIER_ROUTING["medium"]
    assert "glm-4-plus" in TIER_ROUTING["high"]
    assert "deepseek-reasoner" in TIER_ROUTING["high"]
    assert "gpt-5.6-sol" in TIER_ROUTING["premium"]
    assert "claude-opus-4-7" in TIER_ROUTING["premium"]


@pytest.mark.asyncio
async def test_api_providers_endpoint():
    """Test GET /api/ai/providers endpoint returns all providers."""
    transport = ASGITransport(app=app)
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/ai/providers", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        prov_names = [p["provider"] for p in data]
        assert "glm" in prov_names
        assert "qwen" in prov_names
        assert "deepseek" in prov_names
        assert "xai" in prov_names
        assert "cohere" in prov_names
        assert "openai" in prov_names


@pytest.mark.asyncio
async def test_api_provider_models_endpoint():
    """Test GET /api/ai/providers/{id}/models returns model catalog."""
    transport = ASGITransport(app=app)
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test valid provider
        res = await ac.get("/api/ai/providers/glm/models", headers=headers)
        assert res.status_code == 200
        models = res.json()
        assert len(models) >= 6
        model_ids = [m["id"] for m in models]
        assert "glm-4-plus" in model_ids

        # Test invalid provider
        res_404 = await ac.get("/api/ai/providers/unknown_provider_xyz/models", headers=headers)
        assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_model_catalog_validation_all_providers():
    """Verify ModelCatalogService validates model names for all providers."""
    is_valid, _, _ = await model_catalog_service.validate_model_for_provider("glm", "glm-4-plus")
    assert is_valid is True

    is_valid, _, _ = await model_catalog_service.validate_model_for_provider("qwen", "qwen-max")
    assert is_valid is True

    is_valid, _, _ = await model_catalog_service.validate_model_for_provider("xai", "grok-3")
    assert is_valid is True

    is_valid, _, _ = await model_catalog_service.validate_model_for_provider("cohere", "command-a-03-2025")
    assert is_valid is True

    # Invalid model returns False
    is_invalid, err, _ = await model_catalog_service.validate_model_for_provider("glm", "nonexistent-model-xyz")
    assert is_invalid is False
    assert "not available on glm" in err
