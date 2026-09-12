"""
test_prompt_enhancer.py - Regression tests for Phase 5 Prompt Enhancement Engine.
Verifies heuristic quality classification, cheap model selection, workspace context injection,
session caching, fail-open resilience, and intelligence API endpoints.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from app.features.ai.intelligence.prompt_enhancer import (
    classify_prompt_quality,
    enhance_prompt,
    get_enhancement_stats,
    record_enhancement_action,
    set_enhancer_llm_fn,
    reset_enhancer_llm_fn,
    clear_enhancer_session_cache,
    select_cheap_enhancement_model,
    HARD_TIER_MODELS,
)


@pytest.fixture(autouse=True)
def reset_enhancer_state():
    """Clear session cache and mock hooks before and after each test."""
    clear_enhancer_session_cache()
    reset_enhancer_llm_fn()
    yield
    clear_enhancer_session_cache()
    reset_enhancer_llm_fn()


def test_weak_prompt_detected():
    """Verify weak/vague prompts ('fix it', 'make better', etc.) are classified with defects."""
    weak_prompts = [
        "fix it",
        "make better",
        "help",
        "update it",
        "improve this",
        "clean up",
        "do the thing",
        "make it work",
    ]

    for p in weak_prompts:
        result = classify_prompt_quality(p)
        assert result["quality"] in ("weak", "vague"), f"Expected weak/vague for '{p}', got {result}"
        assert result["score"] < 0.70
        assert len(result["issues"]) > 0


def test_good_prompt_passes():
    """Verify detailed, specific prompts with targets and success criteria pass through untouched."""
    good_prompt = "Fix bcrypt cost factor in src/login/handler.py and add a test asserting 401 on bad creds"
    result = classify_prompt_quality(good_prompt)

    assert result["quality"] == "good"
    assert result["score"] >= 0.70
    assert len(result["issues"]) == 0


def test_active_file_rescues_pronoun():
    """Verify ambiguous pronouns ('fix this') are rescued to 'good' when an active file is open."""
    # Without active file -> weak/vague
    res_no_file = classify_prompt_quality("fix this", active_file=None)
    assert res_no_file["quality"] in ("weak", "vague")

    # With active file -> rescued to good
    res_with_file = classify_prompt_quality("fix this", active_file="src/login/handler.py")
    assert res_with_file["quality"] == "good"
    assert res_with_file["score"] >= 0.80
    assert len(res_with_file["issues"]) == 0

    # Pronoun with function reference
    res_func = classify_prompt_quality("debug this function", active_file="src/auth/tokens.py")
    assert res_func["quality"] == "good"


@pytest.mark.asyncio
async def test_enhance_uses_cheap_model():
    """Verify enhancement selects low-cost models and strictly avoids HARD-tier models."""
    prov, model = await select_cheap_enhancement_model()

    full_tag = f"{prov}/{model}"
    assert full_tag not in HARD_TIER_MODELS, f"Model {full_tag} must NOT be in HARD tier"
    assert model not in HARD_TIER_MODELS, f"Model {model} must NOT be in HARD tier"

    # Simulate enhancement with mock provider to inspect model_used
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "Refactor authentication handler in src/auth.py to validate password hashes using bcrypt."

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.service.provider_for", AsyncMock(return_value=mock_provider)):
        res = await enhance_prompt("fix it", quality={"quality": "weak", "issues": ["vague"], "score": 0.2})
        assert res["model_used"] != "fallback"
        assert res["model_used"] not in HARD_TIER_MODELS
        assert not any(hard in res["model_used"] for hard in ("claude-sonnet-4-5", "gpt-4o", "11b-vision"))


@pytest.mark.asyncio
async def test_enhance_fail_open():
    """Verify any provider error or timeout returns the original prompt unchanged."""
    # 1. Timeout simulation: mock hook that sleeps longer than 3s cap
    async def hanging_enhancer(prompt, ctx):
        await asyncio.sleep(5.0)
        return "Enhanced"

    set_enhancer_llm_fn(hanging_enhancer)
    orig_prompt = "fix it"
    res_timeout = await enhance_prompt(orig_prompt, quality={"quality": "weak", "issues": ["vague"], "score": 0.2})

    assert res_timeout["enhanced"] == orig_prompt
    assert res_timeout["original"] == orig_prompt
    assert res_timeout["model_used"] == "fallback"
    assert res_timeout["error"] is not None

    # 2. Exception simulation
    async def failing_enhancer(prompt, ctx):
        raise RuntimeError("API quota exceeded")

    set_enhancer_llm_fn(failing_enhancer)
    clear_enhancer_session_cache()
    res_err = await enhance_prompt(orig_prompt, quality={"quality": "weak", "issues": ["vague"], "score": 0.2})

    assert res_err["enhanced"] == orig_prompt
    assert res_err["original"] == orig_prompt
    assert res_err["model_used"] == "fallback"
    assert res_err["error"] is not None


@pytest.mark.asyncio
async def test_session_cache_no_reenhance():
    """Verify session cache prevents duplicate LLM calls for identical prompts in the same session."""
    call_count = 0

    async def counting_enhancer(prompt, ctx):
        nonlocal call_count
        call_count += 1
        return f"Enhanced: {prompt} with unit test"

    set_enhancer_llm_fn(counting_enhancer)

    # First call -> invokes enhancer
    res1 = await enhance_prompt("make it better", quality={"quality": "weak", "issues": ["vague"], "score": 0.3})
    assert call_count == 1
    assert "Enhanced: make it better" in res1["enhanced"]

    # Second call with same prompt -> hits cache, call_count remains 1
    res2 = await enhance_prompt("make it better", quality={"quality": "weak", "issues": ["vague"], "score": 0.3})
    assert call_count == 1
    assert res2["enhanced"] == res1["enhanced"]


@pytest.mark.asyncio
async def test_stats_endpoint_counts(async_client):
    """Verify stats tracking endpoints accurately record enhancements and actions."""
    # 1. Classify endpoint
    resp_classify = await async_client.post(
        "/api/intelligence/classify-prompt",
        json={"prompt": "fix it", "active_file": None},
    )
    assert resp_classify.status_code == 200
    data_classify = resp_classify.json()
    assert data_classify["quality"] in ("weak", "vague")

    # 2. Record actions
    await async_client.post("/api/intelligence/record-action", json={"action": "accept"})
    await async_client.post("/api/intelligence/record-action", json={"action": "accept"})
    await async_client.post("/api/intelligence/record-action", json={"action": "revert"})

    # 3. Retrieve stats
    resp_stats = await async_client.get("/api/intelligence/enhancement-stats")
    assert resp_stats.status_code == 200
    stats = resp_stats.json()

    assert stats["accepted_count"] >= 2
    assert stats["reverted_count"] >= 1
    assert stats["tokens_saved_estimate"] >= 900


@pytest.mark.asyncio
async def test_classify_prompt_route_registered(async_client):
    """Verify GET and POST routes for /api/intelligence/classify-prompt are registered and live."""
    # 1. GET request with query params
    res_get = await async_client.get("/api/intelligence/classify-prompt?prompt=fix+it")
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert data_get["quality"] in ("weak", "vague")

    # 2. POST request: "fix it" with active file "main.cpp" is NOT rescued (ambiguous pronoun 'it')
    res_post_weak = await async_client.post(
        "/api/intelligence/classify-prompt",
        json={"prompt": "fix it", "active_file": "main.cpp"},
    )
    assert res_post_weak.status_code == 200
    data_weak = res_post_weak.json()
    assert data_weak["quality"] in ("weak", "vague")
    assert data_weak["score"] < 0.70

    # 3. POST request: "fix this" with active file "src/login/handler.py" IS rescued
    res_post_good = await async_client.post(
        "/api/intelligence/classify-prompt",
        json={"prompt": "fix this", "active_file": "src/login/handler.py"},
    )
    assert res_post_good.status_code == 200
    data_good = res_post_good.json()
    assert data_good["quality"] == "good"
    assert data_good["score"] >= 0.80


def test_conversational_and_assistant_questions_classified_good():
    """Verify greetings, pleasantries, and questions directed at assistant are classified 'good' with zero defects."""
    conversational_inputs = [
        "hi",
        "hello",
        "hey there",
        "how are you?",
        "how are you doing today?",
        "who are you?",
        "what can you do?",
        "what models do you support?",
        "tell me about yourself",
        "good morning!",
        "thanks!",
    ]
    for inp in conversational_inputs:
        res = classify_prompt_quality(inp)
        assert res["quality"] == "good", f"Expected 'good' for conversational query '{inp}', got {res}"
        assert res["score"] == 1.0
        assert len(res["issues"]) == 0


@pytest.mark.asyncio
async def test_conversational_passes_through_enhancer_untouched():
    """Verify conversational inputs pass through enhance_prompt without calling LLM or modifying text."""
    conversational_inputs = ["hi", "how are you?", "who are you?"]
    for inp in conversational_inputs:
        res = await enhance_prompt(inp)
        assert res["enhanced"] == inp
        assert res["original"] == inp
        assert res["changes"] == []
        assert res["model_used"] == "pass-through"
        assert res["error"] is None


@pytest.mark.asyncio
async def test_enhance_endpoint_returns_valid_json(async_client):
    """Verify POST /api/intelligence/enhance-prompt returns valid JSON with all required fields in success and fail cases."""
    # 1. Success case (mocked model)
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "Investigate and fix bug in src/main.py, adding unit tests to verify."
    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.service.provider_for", AsyncMock(return_value=mock_provider)):
        res_success = await async_client.post(
            "/api/intelligence/enhance-prompt",
            json={"prompt": "fix it", "active_file": "src/main.py"},
        )
        assert res_success.status_code == 200
        data_success = res_success.json()
        assert "enhanced" in data_success
        assert "original" in data_success
        assert "changes" in data_success
        assert "model_used" in data_success
        assert "error" in data_success
        assert data_success["original"] == "fix it"
        assert "Investigate and fix bug in src/main.py" in data_success["enhanced"]
        assert data_success["error"] is None

    # 2. Fail case (exception thrown by provider)
    clear_enhancer_session_cache()
    with patch("app.features.ai.service.provider_for", AsyncMock(side_effect=RuntimeError("Provider connection failed"))):
        res_fail = await async_client.post(
            "/api/intelligence/enhance-prompt",
            json={"prompt": "make it better", "active_file": "src/main.py"},
        )
        assert res_fail.status_code == 200
        data_fail = res_fail.json()
        assert "enhanced" in data_fail
        assert "original" in data_fail
        assert "changes" in data_fail
        assert "model_used" in data_fail
        assert "error" in data_fail
        assert data_fail["enhanced"] == "make it better"
        assert data_fail["original"] == "make it better"
        assert data_fail["model_used"] == "fallback"
        assert "Enhancement unavailable" in data_fail["error"]


@pytest.mark.asyncio
async def test_enhance_model_unreachable_shows_clear_error(async_client):
    """Verify that when the model is unreachable, endpoint returns clear error and original prompt."""
    clear_enhancer_session_cache()
    with patch("app.features.ai.service.provider_for", AsyncMock(side_effect=ConnectionRefusedError("Connection refused by host"))):
        res = await async_client.post(
            "/api/intelligence/enhance-prompt",
            json={"prompt": "clean up", "active_file": "app.py"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["original"] == "clean up"
        assert data["enhanced"] == "clean up"
        assert data["model_used"] == "fallback"
        assert data["error"] is not None
        assert "unreachable" in data["error"].lower() or "connection" in data["error"].lower()



