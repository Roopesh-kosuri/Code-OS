import pytest
from app.features.ai.provider_health import ProviderHealthTracker


def test_circuit_breaker_non_blocking_tracking():
    tracker = ProviderHealthTracker()

    for i in range(4):
        tracker.record_outcome("groq", success=False, error_msg=f"Error {i}")
        is_open, _, _ = tracker.is_circuit_open("groq")
        assert is_open is False

    # 5th failure records metrics but stays non-blocking
    tracker.record_outcome("groq", success=False, error_msg="Error 5")
    is_open, remaining, msg = tracker.is_circuit_open("groq")
    assert is_open is False

    health = tracker.get_health("groq")
    assert health["consecutive_failures"] == 5


def test_fallback_provider_selection_skips_failed_and_unconfigured():
    tracker = ProviderHealthTracker()
    for _ in range(5):
        tracker.record_outcome("groq", success=False, error_msg="429 Rate Limit")

    configured_keys = {
        "groq": "gsk_123",
        "gemini": None,  # Not configured
        "nvidia-nim": "nvapi-456",  # Configured & healthy
        "openai": "sk-789",
    }

    fallback = tracker.find_fallback_provider("groq", configured_keys)
    assert fallback is not None
    prov_id, model, base_url = fallback
    assert prov_id == "nvidia-nim"
    assert "llama" in model or "minimax" in model


def test_success_resets_consecutive_failures():
    tracker = ProviderHealthTracker()
    for _ in range(3):
        tracker.record_outcome("openai", success=False, error_msg="500 Server Error")

    assert tracker.get_health("openai")["consecutive_failures"] == 3

    # Success immediately resets consecutive failures
    tracker.record_outcome("openai", success=True)
    assert tracker.get_health("openai")["consecutive_failures"] == 0

    # Additional successes bring 1-hour fail rate below 50%
    for _ in range(4):
        tracker.record_outcome("openai", success=True)
    assert tracker.get_health("openai")["status"] == "healthy"
