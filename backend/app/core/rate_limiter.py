"""
rate_limiter.py
Sliding window rate limiter and token budget tracker for CODE OS.
"""
from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any
from fastapi import HTTPException

# Default limits
DEFAULT_API_LIMIT = 100  # requests per minute
DEFAULT_API_WINDOW = 60.0  # seconds
DEFAULT_AGENT_RUN_LIMIT = 10  # runs per hour
DEFAULT_AGENT_RUN_WINDOW = 3600.0  # seconds
DEFAULT_MONTHLY_TOKEN_BUDGET = 1_000_000  # 1M tokens/month
DEFAULT_DAILY_PROVIDER_TOKEN_BUDGET = 200_000  # 200k tokens/day per provider


class RateLimiter:
    """In-memory sliding window rate limiter and token budget tracker."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._token_usage: dict[str, int] = defaultdict(int)
        self._token_month: dict[str, str] = {}
        self._provider_token_usage: dict[str, int] = defaultdict(int)
        self._provider_token_day: dict[str, str] = {}
        self._lock = Lock()

    def check(self, key: str, max_requests: int = DEFAULT_API_LIMIT, window_seconds: float = DEFAULT_API_WINDOW) -> dict[str, Any]:
        """Track rate limit for a key. NEVER blocks or raises 429."""
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = [t for t in self._requests[key] if t > cutoff]
            timestamps.append(now)
            self._requests[key] = timestamps
            remaining = max(0, max_requests - len(timestamps))
            return {
                "allowed": True,
                "limit": max_requests,
                "remaining": remaining,
                "window": window_seconds,
            }

    def check_agent_run(self, key: str, max_runs: int = DEFAULT_AGENT_RUN_LIMIT, window_seconds: float = DEFAULT_AGENT_RUN_WINDOW) -> None:
        """Track agent run limit."""
        run_key = f"agent_run:{key}"
        self.check(run_key, max_requests=max_runs, window_seconds=window_seconds)

    def record_tokens(self, key: str, token_count: int) -> int:
        """Record token consumption against workspace/user monthly budget."""
        import datetime
        current_month = datetime.datetime.utcnow().strftime("%Y-%m")
        with self._lock:
            if self._token_month.get(key) != current_month:
                self._token_month[key] = current_month
                self._token_usage[key] = 0
            self._token_usage[key] += token_count
            return self._token_usage[key]

    def record_provider_tokens(self, provider: str, token_count: int) -> int:
        """Record token consumption against a specific AI provider's daily quota."""
        import datetime
        prov_key = provider.lower()
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            if self._provider_token_day.get(prov_key) != today:
                self._provider_token_day[prov_key] = today
                self._provider_token_usage[prov_key] = 0
            self._provider_token_usage[prov_key] += max(0, int(token_count))
            return self._provider_token_usage[prov_key]

    def check_token_budget(
        self,
        provider: str,
        estimated_tokens: int = 500,
        daily_limit: int = DEFAULT_DAILY_PROVIDER_TOKEN_BUDGET,
    ) -> dict[str, Any]:
        """
        Track daily token usage. NEVER blocks or raises 429.
        Always returns allowed=True.
        """
        import datetime
        prov_key = provider.lower()
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            if self._provider_token_day.get(prov_key) != today:
                self._provider_token_day[prov_key] = today
                self._provider_token_usage[prov_key] = 0

            used = self._provider_token_usage[prov_key]
            remaining = max(0, daily_limit - used)
            return {
                "allowed": True,
                "provider": prov_key,
                "used_tokens": used,
                "daily_limit": daily_limit,
                "remaining_tokens": remaining,
                "percent_used": round((used / daily_limit) * 100, 1) if daily_limit > 0 else 0.0,
            }

    def get_daily_provider_status(self, provider: str | None = None, daily_limit: int = DEFAULT_DAILY_PROVIDER_TOKEN_BUDGET) -> dict[str, Any]:
        """Get current day token usage for one or all providers."""
        import datetime
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            if provider:
                prov_key = provider.lower()
                if self._provider_token_day.get(prov_key) != today:
                    self._provider_token_day[prov_key] = today
                    self._provider_token_usage[prov_key] = 0
                used = self._provider_token_usage[prov_key]
                remaining = max(0, daily_limit - used)
                return {
                    "provider": prov_key,
                    "date": today,
                    "used_tokens": used,
                    "daily_limit": daily_limit,
                    "remaining_tokens": remaining,
                    "percent_used": round((used / daily_limit) * 100, 1) if daily_limit > 0 else 0.0,
                    "allowed": True,
                }
            else:
                all_providers = set(list(self._provider_token_usage.keys()) + ["groq", "gemini", "nvidia-nim", "openai", "anthropic", "deepseek"])
                result: dict[str, Any] = {}
                for p in all_providers:
                    if self._provider_token_day.get(p) != today:
                        self._provider_token_day[p] = today
                        self._provider_token_usage[p] = 0
                    used = self._provider_token_usage[p]
                    result[p] = {
                        "provider": p,
                        "date": today,
                        "used_tokens": used,
                        "daily_limit": daily_limit,
                        "remaining_tokens": max(0, daily_limit - used),
                        "percent_used": round((used / daily_limit) * 100, 1) if daily_limit > 0 else 0.0,
                        "allowed": True,
                    }
                return result


    def get_token_status(self, key: str, budget: int = DEFAULT_MONTHLY_TOKEN_BUDGET) -> dict[str, Any]:
        """Get current month token usage and remaining budget."""
        import datetime
        current_month = datetime.datetime.utcnow().strftime("%Y-%m")
        with self._lock:
            if self._token_month.get(key) != current_month:
                self._token_month[key] = current_month
                self._token_usage[key] = 0
            used = self._token_usage[key]
            remaining = max(0, budget - used)
            return {
                "month": current_month,
                "used_tokens": used,
                "budget_tokens": budget,
                "remaining_tokens": remaining,
                "percent_used": round((used / budget) * 100, 2) if budget > 0 else 0.0,
            }

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._token_usage.clear()
            self._token_month.clear()
            self._provider_token_usage.clear()
            self._provider_token_day.clear()


rate_limiter = RateLimiter()
SimpleRateLimiter = RateLimiter
