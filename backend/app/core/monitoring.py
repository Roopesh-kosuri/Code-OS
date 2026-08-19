"""
monitoring.py
Production error monitoring, sanitized exception tracking, and performance profiling.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Patterns to scrub from error traces and reports
SECRET_SCRUB_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9_\-]{20,}'), '[REDACTED_API_KEY]'),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), '[REDACTED_GITHUB_TOKEN]'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '[REDACTED_AWS_KEY]'),
    (re.compile(r'glpat-[a-zA-Z0-9_\-]{20,}'), '[REDACTED_GITLAB_TOKEN]'),
    (re.compile(r'xox[baprs]-[0-9a-zA-Z\-]{10,}'), '[REDACTED_SLACK_TOKEN]'),
    (re.compile(r'AIza[0-9A-Za-z\-_]{35}'), '[REDACTED_GOOGLE_KEY]'),
    (re.compile(r'(?i)(password|secret|token|api_key)\s*[:=]\s*["\']?[^\s"\',]+["\']?'), r'\1=[REDACTED]'),
]


def sanitize_text(text: str) -> str:
    """Scrub potential credentials, tokens, and sensitive strings from text."""
    if not text:
        return ""
    cleaned = text
    for pattern, replacement in SECRET_SCRUB_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


@dataclass
class ErrorReportEntry:
    id: str
    timestamp: float
    error_type: str
    message: str
    sanitized_traceback: str
    context: dict[str, Any] = field(default_factory=dict)
    user_reported: bool = False


class ErrorMonitor:
    """In-memory circular buffer of sanitized error events and performance metrics."""

    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self._errors: deque[ErrorReportEntry] = deque(maxlen=max_entries)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = Lock()
        self._sentry_initialized = False

    def init_sentry(self, dsn: str | None = None) -> bool:
        """Initialize Sentry SDK if available and DSN is configured."""
        sentry_dsn = dsn or os.environ.get("SENTRY_DSN")
        if not sentry_dsn:
            return False
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=sentry_dsn,
                traces_sample_rate=1.0,
                send_default_pii=False,
            )
            self._sentry_initialized = True
            logger.info("monitoring: Sentry SDK initialized successfully")
            return True
        except ImportError:
            logger.info("monitoring: sentry_sdk not installed, using built-in error monitor")
            return False
        except Exception as exc:
            logger.warning("monitoring: Failed to initialize Sentry: %s", exc)
            return False

    def capture_exception(
        self,
        exc: Exception,
        context: dict[str, Any] | None = None,
        user_reported: bool = False,
    ) -> str:
        """Capture and record a sanitized exception report."""
        import uuid
        report_id = f"err_{uuid.uuid4().hex[:12]}"
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        sanitized_tb = sanitize_text(tb_str)
        sanitized_msg = sanitize_text(str(exc))
        
        safe_ctx = {}
        if context:
            for k, v in context.items():
                if k.lower() in ("api_key", "secret", "password", "token"):
                    continue
                safe_ctx[k] = sanitize_text(str(v)) if isinstance(v, str) else v

        entry = ErrorReportEntry(
            id=report_id,
            timestamp=time.time(),
            error_type=exc.__class__.__name__,
            message=sanitized_msg,
            sanitized_traceback=sanitized_tb,
            context=safe_ctx,
            user_reported=user_reported,
        )

        with self._lock:
            self._errors.appendleft(entry)
            self._counts[exc.__class__.__name__] += 1

        if self._sentry_initialized:
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    for k, v in safe_ctx.items():
                        scope.set_extra(k, v)
                    sentry_sdk.capture_exception(exc)
            except Exception:
                pass

        logger.error("monitoring.capture_exception id=%s type=%s msg=%s", report_id, entry.error_type, entry.message)
        return report_id

    def record_metric(self, name: str, duration_ms: float) -> None:
        """Record an operation latency measurement."""
        with self._lock:
            measurements = self._latencies[name]
            measurements.append(duration_ms)
            if len(measurements) > 1000:
                self._latencies[name] = measurements[-500:]

    def get_metrics_summary(self) -> dict[str, Any]:
        """Compute p50, p95, p99 latencies for all tracked operations."""
        import math
        summary: dict[str, Any] = {}
        with self._lock:
            for name, vals in self._latencies.items():
                if not vals:
                    continue
                sorted_v = sorted(vals)
                n = len(sorted_v)
                p50 = sorted_v[int(math.ceil(0.50 * n)) - 1]
                p95 = sorted_v[int(math.ceil(0.95 * n)) - 1]
                p99 = sorted_v[int(math.ceil(0.99 * n)) - 1]
                summary[name] = {
                    "count": n,
                    "avg_ms": round(sum(sorted_v) / n, 2),
                    "p50_ms": round(p50, 2),
                    "p95_ms": round(p95, 2),
                    "p99_ms": round(p99, 2),
                    "min_ms": round(sorted_v[0], 2),
                    "max_ms": round(sorted_v[-1], 2),
                }
        return summary

    def get_recent_errors(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent sanitized error reports."""
        with self._lock:
            return [
                {
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "error_type": e.error_type,
                    "message": e.message,
                    "sanitized_traceback": e.sanitized_traceback,
                    "context": e.context,
                    "user_reported": e.user_reported,
                }
                for e in list(self._errors)[:limit]
            ]


monitor = ErrorMonitor()
