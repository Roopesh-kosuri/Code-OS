import pytest
from app.core.rate_limiter import RateLimiter, LIMITS


def test_rate_limit_blocks_after_threshold():
    limiter = RateLimiter(enforce=True)
    # Threshold = 3
    for _ in range(3):
        res = limiter.check("test_key", max_requests=3, window_seconds=60.0)
        assert res["allowed"] is True

    # 4th request must be blocked
    blocked = limiter.check("test_key", max_requests=3, window_seconds=60.0)
    assert blocked["allowed"] is False
    assert blocked["remaining"] == 0


def test_rate_limit_returns_retry_after():
    limiter = RateLimiter(enforce=True)
    for _ in range(3):
        limiter.check("retry_key", max_requests=2, window_seconds=60.0)

    blocked = limiter.check("retry_key", max_requests=2, window_seconds=60.0)
    assert blocked["allowed"] is False
    assert "retry_after" in blocked
    assert blocked["retry_after"] > 0
    assert blocked["retry_after"] <= 60


def test_token_budget_enforced():
    limiter = RateLimiter(enforce=True)
    limiter.record_provider_tokens("openai", 195_000)

    # Request of 10,000 tokens when limit is 200,000 should exceed budget
    res = limiter.check_token_budget("openai", estimated_tokens=10_000, daily_limit=200_000)
    assert res["allowed"] is False
    assert res["used_tokens"] == 195_000


def test_default_unenforced_preserves_backward_compatibility():
    limiter = RateLimiter(enforce=False)
    for _ in range(10):
        res = limiter.check("compat_key", max_requests=2, window_seconds=60.0)
        assert res["allowed"] is True
