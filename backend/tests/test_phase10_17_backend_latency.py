import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
import httpx

from app.features.ai.chat_harness import run_chat_agent, _get_cached_settings, _settings_cache
from app.features.ai.schemas import ChatRequest, ChatMessage
from app.features.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.features.ai.providers.anthropic import AnthropicProvider
from app.features.ai.provider_health import provider_health_tracker, CIRCUIT_BREAKER_COOLDOWN_BASE
from app.features.ai.providers.base import ProviderRequestError


@pytest.mark.asyncio
async def test_tier0_skips_rag_embedding_reconcile():
    """Verify that a simple greeting like 'hi' skips all RAG/embedding calls."""
    req = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        provider="mock",
        model="mock-model",
        workspace=".",
    )

    with patch("app.features.ai.chat_harness.rag_semantic_search") as mock_rag, \
         patch("app.features.ai.chat_harness._gather_budgeted_rag_context") as mock_gather, \
         patch("app.features.ai.chat_harness.provider_for") as mock_pfor:
        mock_prov = AsyncMock()
        async def fake_stream(*args, **kwargs):
            yield MagicMock(type="text", content="Hello!")
            yield MagicMock(type="finish", finish_reason="stop")
        mock_prov.stream_agent = fake_stream
        mock_pfor.return_value = mock_prov

        events = []
        async for evt in run_chat_agent(req):
            events.append(evt)

        # Neither rag_semantic_search nor _gather_budgeted_rag_context should be called
        assert not mock_rag.called
        assert not mock_gather.called
        # Check tier routing event was tier 0
        tier_events = [e for e in events if "tier_routing" in e]
        assert len(tier_events) >= 1
        assert '"tier": 0' in tier_events[0]


@pytest.mark.asyncio
async def test_provider_connect_timeout_bounded_to_3s():
    """Verify provider connect timeout is bounded to <= 3s per attempt."""
    prov = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:9999",  # unreachable local port
        api_key="sk-fake",
    )
    t0 = time.monotonic()
    with pytest.raises(ProviderRequestError):
        async for _ in prov.stream_agent("model", [ChatMessage(role="user", content="hi")], 0.2):
            pass
    duration = time.monotonic() - t0
    # Connect timeout is 3.0s per attempt (3 attempts * 3s + backoffs = ~13s vs 50s+ previously)
    assert duration < 16.0
    assert prov.timeout_seconds == 180.0
    # Verify anthropic provider timeout config as well
    anth = AnthropicProvider(api_key="sk-fake", timeout_seconds=120.0)
    assert anth.timeout_seconds == 120.0


def test_circuit_breaker_60s_cooldown():
    """Verify circuit breaker trips and applies 60s cooldown base."""
    assert CIRCUIT_BREAKER_COOLDOWN_BASE == 60.0
    provider_health_tracker.reset_all()

    test_id = "test-flaky"
    for _ in range(5):
        provider_health_tracker.record_outcome(test_id, False, "Connection failed")

    is_open, remaining, msg = provider_health_tracker.is_circuit_open(test_id)
    assert is_open is True
    assert 55.0 <= remaining <= 60.0
    assert "Circuit open" in msg

    provider_health_tracker.reset_all()


@pytest.mark.asyncio
async def test_settings_cache_avoids_repeated_db_calls():
    """Verify _get_cached_settings caches results across turns within TTL."""
    with patch("app.features.ai.chat_harness.list_settings", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = {"ai.allow_link_fetch": "true"}

        # Reset cache
        import app.features.ai.chat_harness as ch
        ch._settings_cache = None
        ch._settings_cache_time = 0.0

        res1 = await _get_cached_settings()
        assert res1 == {"ai.allow_link_fetch": "true"}
        assert mock_list.call_count == 1

        res2 = await _get_cached_settings()
        assert res2 == {"ai.allow_link_fetch": "true"}
        assert mock_list.call_count == 1  # Not called again
