import time
from collections import defaultdict
from threading import Lock
from fastapi import HTTPException


class SimpleRateLimiter:
    """In-memory sliding window rate limiter for protecting sensitive API routes."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str, max_requests: int, window_seconds: float) -> None:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = [t for t in self._requests[key] if t > cutoff]
            if len(timestamps) >= max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: max {max_requests} requests per {int(window_seconds)}s."
                )
            timestamps.append(now)
            self._requests[key] = timestamps

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()


rate_limiter = SimpleRateLimiter()
