import pytest
from app.features.ai.model_catalog_service import ModelCatalogService, model_catalog_service


@pytest.mark.asyncio
async def test_groq_valid_models_pass_validation():
    service = ModelCatalogService()
    # Inject known catalog into cache for isolated unit testing
    service._cache["groq"] = {
        "timestamp": 9999999999.0,
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3.6-27b", "mixtral-8x7b-32768"],
    }
    valid, msg, models = await service.validate_model_for_provider("groq", "llama-3.3-70b-versatile")
    assert valid is True
    assert msg == ""


@pytest.mark.asyncio
async def test_groq_invalid_model_rejected_with_available_list():
    service = ModelCatalogService()
    # Inject known catalog into cache
    service._cache["groq"] = {
        "timestamp": 9999999999.0,
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    }
    valid, msg, models = await service.validate_model_for_provider("groq", "invalid-model-xyz")
    assert valid is False
    assert "Model 'invalid-model-xyz' not available on groq" in msg
    assert "Available models:" in msg
    assert "llama-3.3-70b-versatile" in msg


@pytest.mark.asyncio
async def test_openai_and_gemini_model_validation():
    service = ModelCatalogService()
    service._cache["openai"] = {
        "timestamp": 9999999999.0,
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    }
    service._cache["gemini"] = {
        "timestamp": 9999999999.0,
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    }
    valid_openai, _, _ = await service.validate_model_for_provider("openai", "gpt-4o")
    assert valid_openai is True

    valid_gemini, _, _ = await service.validate_model_for_provider("gemini", "gemini-2.5-flash")
    assert valid_gemini is True

    invalid_openai, err_msg, _ = await service.validate_model_for_provider("openai", "non-existent-super-gpt-99")
    assert invalid_openai is False
    assert "not available on openai" in err_msg


@pytest.mark.asyncio
async def test_catalog_24h_caching():
    service = ModelCatalogService()
    models1 = await service.get_available_models("groq")
    assert len(models1) > 0
    assert "groq" in service._cache
    cached_timestamp = service._cache["groq"]["timestamp"]

    # Second call should use cache immediately
    models2 = await service.get_available_models("groq")
    assert models1 == models2
    assert service._cache["groq"]["timestamp"] == cached_timestamp
