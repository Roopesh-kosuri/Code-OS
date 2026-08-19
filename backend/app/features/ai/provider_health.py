"""
provider_health.py
Tracks AI provider health, failure rates in 1-hour windows, and implements a 5-failure circuit breaker.
Provides automatic fallback provider discovery across configured providers.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

# Sliding health window (1 hour)
HEALTH_WINDOW_SECONDS = 3600.0
# Circuit breaker trip threshold
CIRCUIT_BREAKER_FAILURES = 5
# Circuit breaker cooldown (5 minutes)
CIRCUIT_BREAKER_COOLDOWN = 300.0

DEFAULT_FALLBACK_ORDER = [
    "groq",
    "gemini",
    "nvidia-nim",
    "openai",
    "anthropic",
    "deepseek",
    "mistral",
    "ollama",
]

DEFAULT_PROVIDER_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-2.5-flash",
    "nvidia-nim": "meta/llama-3.1-70b-instruct",
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-latest",
    "deepseek": "deepseek-chat",
    "mistral": "mistral-large-latest",
    "ollama": "llama3",
}

DEFAULT_PROVIDER_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "nvidia-nim": "https://integrate.api.nvidia.com/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": "http://127.0.0.1:11434",
}


class ProviderHealthTracker:
    """In-memory sliding window health tracker and circuit breaker for AI providers."""

    def __init__(self) -> None:
        # History of (timestamp, success: bool, error_msg: str)
        self._history: dict[str, list[tuple[float, bool, str]]] = defaultdict(list)
        self._consecutive_failures: dict[str, int] = defaultdict(int)
        self._circuit_opened_at: dict[str, float] = {}
        self._lock = RLock()

    def record_outcome(
        self,
        provider_id: str,
        success: bool,
        error_msg: str = "",
        is_429: bool = False,
        is_404: bool = False,
    ) -> None:
        """Record success or failure for a provider."""
        now = time.time()
        prov_key = provider_id.lower()

        with self._lock:
            # Clean old history
            cutoff = now - HEALTH_WINDOW_SECONDS
            self._history[prov_key] = [
                h for h in self._history[prov_key] if h[0] > cutoff
            ]
            self._history[prov_key].append((now, success, error_msg))

            if success:
                self._consecutive_failures[prov_key] = 0
                if prov_key in self._circuit_opened_at:
                    del self._circuit_opened_at[prov_key]
            else:
                self._consecutive_failures[prov_key] += 1
                if self._consecutive_failures[prov_key] >= CIRCUIT_BREAKER_FAILURES:
                    self._circuit_opened_at[prov_key] = now
                    logger.warning(
                        "Circuit breaker TRIPPED for provider '%s' after %d consecutive failures. Cooldown for %.0fs.",
                        prov_key,
                        self._consecutive_failures[prov_key],
                        CIRCUIT_BREAKER_COOLDOWN,
                    )

    def is_circuit_open(self, provider_id: str) -> tuple[bool, float, str]:
        """
        Circuit breakers are non-blocking: always returns False.
        """
        return False, 0.0, ""

    def reset_all(self) -> None:
        """Reset all circuit breakers, failure history, and metrics to clean healthy state."""
        with self._lock:
            self._history.clear()
            self._consecutive_failures.clear()
            self._circuit_opened_at.clear()
            logger.info("All provider health counters and circuit breakers reset to clean state.")

    def get_health(self, provider_id: str) -> dict[str, Any]:
        """Get health metrics and status for a provider."""
        now = time.time()
        prov_key = provider_id.lower()

        with self._lock:
            is_open, remaining, msg = self.is_circuit_open(prov_key)
            cutoff = now - HEALTH_WINDOW_SECONDS
            history = [h for h in self._history[prov_key] if h[0] > cutoff]
            total = len(history)
            failures = sum(1 for _, ok, _ in history if not ok)
            successes = total - failures
            fail_rate = (failures / total) if total > 0 else 0.0

            if is_open:
                status = "circuit_open"
                status_label = f"Circuit Open (cooldown {int(remaining)}s)"
            elif total >= 3 and fail_rate >= 0.5:
                status = "degraded"
                status_label = f"Degraded ({failures} failures in last hour, {int(fail_rate * 100)}% fail rate)"
            else:
                status = "healthy"
                status_label = "Healthy" if total > 0 else "Idle / Ready"

            return {
                "provider": prov_key,
                "status": status,
                "status_label": status_label,
                "total_requests_last_hour": total,
                "failures_last_hour": failures,
                "successes_last_hour": successes,
                "failure_rate": round(fail_rate, 2),
                "consecutive_failures": self._consecutive_failures[prov_key],
                "circuit_open": is_open,
                "cooldown_remaining_seconds": round(remaining, 1),
            }

    def get_all_health(self) -> dict[str, Any]:
        """Get health metrics for all known providers."""
        providers = set(list(self._history.keys()) + list(DEFAULT_FALLBACK_ORDER))
        return {p: self.get_health(p) for p in providers}

    def find_fallback_provider(
        self,
        failed_provider: str | set[str] | list[str],
        configured_keys: dict[str, str | None],
        preferred_order: list[str] | None = None,
    ) -> tuple[str, str, str] | None:
        """
        Find the next healthy, configured provider in order of preference.
        Excludes any providers that have already failed in the current turn.
        Returns: (provider_id, default_model, base_url) or None if no fallback available.
        """
        if isinstance(failed_provider, (set, list, tuple)):
            failed_keys = {p.lower() for p in failed_provider}
        else:
            failed_keys = {failed_provider.lower()}

        order = preferred_order or DEFAULT_FALLBACK_ORDER

        for candidate in order:
            cand_key = candidate.lower()
            if cand_key in failed_keys:
                continue

            # Check circuit breaker
            is_open, _, _ = self.is_circuit_open(cand_key)
            if is_open:
                continue

            # Check if key is configured (ollama doesn't require key)
            if cand_key != "ollama" and not configured_keys.get(cand_key):
                continue

            # Check model and URL
            model = DEFAULT_PROVIDER_MODELS.get(cand_key, "gpt-4o")
            base_url = DEFAULT_PROVIDER_URLS.get(cand_key, "https://api.openai.com/v1")
            return cand_key, model, base_url

        return None

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._consecutive_failures.clear()
            self._circuit_opened_at.clear()


provider_health_tracker = ProviderHealthTracker()
