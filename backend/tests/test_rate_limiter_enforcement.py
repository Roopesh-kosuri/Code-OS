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


def test_agent_iteration_limit_enforced():
    from app.core.rate_limiter import RateLimitExceeded
    limiter = RateLimiter(enforce=True)
    session = "test_session_1"
    # Execute 3 iterations with cap of 3
    for _ in range(3):
        res = limiter.check_agent_iteration(session, max_iterations=3, enforce=True)
        assert res["allowed"] is True

    # 4th iteration must be blocked
    blocked = limiter.check_agent_iteration(session, max_iterations=3, enforce=True)
    assert blocked["allowed"] is False

    # Raising mode raises 429 RateLimitExceeded
    with pytest.raises(RateLimitExceeded) as exc:
        limiter.check_agent_iteration(session, max_iterations=3, enforce=True, raise_on_exceed=True)
    assert exc.value.status_code == 429


def test_tool_call_limit_enforced():
    from app.core.rate_limiter import RateLimitExceeded
    limiter = RateLimiter(enforce=True)
    session = "test_session_tools"
    for _ in range(5):
        res = limiter.check_tool_call(session, max_calls=5, enforce=True)
        assert res["allowed"] is True

    blocked = limiter.check_tool_call(session, max_calls=5, enforce=True)
    assert blocked["allowed"] is False

    with pytest.raises(RateLimitExceeded) as exc:
        limiter.check_tool_call(session, max_calls=5, enforce=True, raise_on_exceed=True)
    assert exc.value.status_code == 429

