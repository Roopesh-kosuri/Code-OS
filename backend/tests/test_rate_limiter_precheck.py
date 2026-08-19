import pytest
from fastapi import HTTPException
from app.core.rate_limiter import RateLimiter


def test_daily_provider_token_tracking():
    rl = RateLimiter()
    used = rl.record_provider_tokens("groq", 1500)
    assert used == 1500

    used = rl.record_provider_tokens("groq", 2500)
    assert used == 4000

    status = rl.get_daily_provider_status("groq")
    assert status["provider"] == "groq"
    assert status["used_tokens"] == 4000
    assert status["daily_limit"] == 200000
    assert status["remaining_tokens"] == 196000
    assert status["percent_used"] == 2.0


def test_pre_request_budget_check_allows_under_limit():
    rl = RateLimiter()
    rl.record_provider_tokens("openai", 50000)
    res = rl.check_token_budget("openai", estimated_tokens=1000, daily_limit=200000)
    assert res["allowed"] is True
    assert res["remaining_tokens"] == 150000


def test_pre_request_budget_check_non_blocking_when_high():
    rl = RateLimiter()
    # Consume 199,500 tokens
    rl.record_provider_tokens("groq", 199500)

    # Attempting a request with estimated 1000 tokens — should track usage without throwing 429
    res = rl.check_token_budget("groq", estimated_tokens=1000, daily_limit=200000)
    assert res["allowed"] is True
    assert res["used_tokens"] == 199500
    assert res["remaining_tokens"] == 500
    assert res["percent_used"] == 99.8
