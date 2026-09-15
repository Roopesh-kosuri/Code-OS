from __future__ import annotations

import logging
import re
from typing import Any, Optional, Tuple, Dict

logger = logging.getLogger(__name__)

LARGE_REWRITE_LINE_THRESHOLD = 60


def is_whole_file_rewrite_intent(query: str, tier: int = 1) -> bool:
    """Detect whole-file rewrite intent on Quick Task to suggest tier upgrade in UI."""
    if not query:
        return False
    return _is_whole_file_rewrite_query(query)


def _is_whole_file_rewrite_query(query: str) -> bool:
    q_lower = query.lower()
    patterns = [
        r"(?:rewrite|re-write|write|writing|implement|implementing|create|creating|build|building)\s+(?:.*?\s+)?(?:code\s+of\s+)?(?:login|auth|user|payment|dashboard|backend|frontend|api|crud|database)\s+system",
        r"(?:rewrite|re-write|replace)\s+(?:the\s+)?(?:entire|whole|all of)\s+[\w\-./\\]+",
        r"(?:write|writing)\s+(?:a\s+)?code\s+of\s+login\s+system",
        r"(?:implement|implementing)\s+(?:entire|complete|full)\s+(?:auth|login|system|module)",
    ]
    return any(bool(re.search(p, q_lower)) for p in patterns)


def check_rewrite_size_guard(
    path: str,
    updated: str,
    tier: int = 1,
    query: str = "",
    force_patch: bool = False,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Check if single edit_file payload exceeds output budget or ~60 lines.
    
    Returns:
      (is_exceeded, rejection_reason, tier_suggestion)
    """
    if not updated:
        return False, None, None

    line_count = len(updated.splitlines())
    if line_count > LARGE_REWRITE_LINE_THRESHOLD or force_patch:
        logger.info(
            "[large_rewrite_forced_patch] path=%s lines=%d tier=%d",
            path, line_count, tier
        )
        reason = (
            f"Large rewrite detected ({line_count} lines > {LARGE_REWRITE_LINE_THRESHOLD}). "
            "Large single-response rewrites risk output truncation. "
            "Please use patch-style mode: emit multiple small edit_file calls with short unique original snippets (3-15 lines) "
            "and updated replacements (<= ~40 lines)."
        )
        suggestion = None
        if tier == 1 or _is_whole_file_rewrite_query(query):
            suggestion = {
                "suggested_tier": 2,
                "tier_name": "Deep Task",
                "message": "This looks like a multi-part change — run as Deep Task?",
            }
        return True, reason, suggestion

    return False, None, None
