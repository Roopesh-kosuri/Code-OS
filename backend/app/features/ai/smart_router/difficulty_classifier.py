from __future__ import annotations

import logging
from typing import Any, Optional

from app.features.ai.intelligence.task_classifier import classify_task, HARD_KEYWORDS, EASY_KEYWORDS, MEDIUM_KEYWORDS

logger = logging.getLogger(__name__)


def classify_task_difficulty(
    task_description: str,
    file_list: Optional[list[str]] = None,
    use_llm_fallback: bool = False,
) -> dict[str, Any]:
    """Difficulty heuristic classifier:
    Classifies task difficulty into HARD, MEDIUM, or EASY by delegating
    to the unified task_classifier engine.

    Returns:
        {
            "difficulty": "HARD" | "MEDIUM" | "EASY",
            "confidence": float (0.0 to 1.0),
            "score": float,
            "reasons": list[str],
            "method": "llm" | "heuristic"
        }
    """
    res = classify_task(
        task_description=task_description,
        file_list=file_list,
        use_llm=use_llm_fallback,
    )
    return {
        "difficulty": res["tier"],
        "confidence": res["confidence"],
        "score": res["score"],
        "reasons": res["reasons"],
        "method": res["method"],
    }

