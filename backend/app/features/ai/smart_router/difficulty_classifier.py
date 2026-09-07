from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

HARD_KEYWORDS = {
    "auth", "authentication", "encryption", "crypto", "payment", "stripe",
    "algorithm", "security", "parser", "compiler", "optimization", "jwt",
    "oauth", "concurrency", "deadlock", "distributed", "consensus", "sandbox",
    "vulnerability", "invariant", "microkernel", "zero-knowledge", "assembly"
}

EASY_KEYWORDS = {
    "boilerplate", "test", "tests", "unit test", "doc", "docs", "documentation",
    "readme", "comment", "config", "configuration", "css", "style", "styling",
    "scaffolding", "scaffold", "lint", "format", "typo", "bump", "version",
    "export", "import", "cleanup", "rename"
}

MEDIUM_KEYWORDS = {
    "component", "feature", "api", "endpoint", "crud", "controller", "handler",
    "route", "service", "model", "schema", "table", "migration", "filter",
    "view", "form", "dashboard", "panel", "state", "store", "selector"
}


def _analyze_file_list(file_list: list[str]) -> tuple[int, list[str]]:
    """Analyze file list for line counts (>500 LOC) and complexity."""
    high_loc_files = []
    total_loc = 0
    for fpath_str in file_list:
        try:
            p = Path(fpath_str)
            if p.is_file():
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    lines = len(f.readlines())
                    total_loc += lines
                    if lines > 500:
                        high_loc_files.append(f"{p.name} ({lines} LOC)")
        except Exception:
            continue
    return total_loc, high_loc_files


def classify_task_difficulty(
    task_description: str,
    file_list: Optional[list[str]] = None,
    use_llm_fallback: bool = False,
) -> dict[str, Any]:
    """Experimental Difficulty Heuristic:
    Classifies task difficulty into HARD, MEDIUM, or EASY based on keyword
    matching and codebase complexity metrics (file count, LOC thresholds).

    Returns:
        {
            "difficulty": "HARD" | "MEDIUM" | "EASY",
            "confidence": float (0.0 to 1.0),
            "score": float,
            "reasons": list[str],
            "method": "heuristic"
        }
    """
    if not task_description:
        return {
            "difficulty": "EASY",
            "confidence": 0.5,
            "score": 0.0,
            "reasons": ["Empty task description defaults to EASY"],
        }

    text = task_description.lower()
    words = set(re.findall(r"\b\w+\b", text))

    hard_matches = words.intersection(HARD_KEYWORDS)
    easy_matches = words.intersection(EASY_KEYWORDS)
    medium_matches = words.intersection(MEDIUM_KEYWORDS)

    reasons: list[str] = []
    hard_score = len(hard_matches) * 3.0
    easy_score = len(easy_matches) * 2.0
    medium_score = len(medium_matches) * 1.5

    if hard_matches:
        reasons.append(f"Contains high-complexity keywords: {', '.join(sorted(hard_matches))}")
    if easy_matches:
        reasons.append(f"Contains low-complexity keywords: {', '.join(sorted(easy_matches))}")
    if medium_matches:
        reasons.append(f"Contains standard feature keywords: {', '.join(sorted(medium_matches))}")

    # Inspect file metrics if available
    if file_list:
        total_loc, high_loc_files = _analyze_file_list(file_list)
        if high_loc_files:
            hard_score += len(high_loc_files) * 2.5
            reasons.append(f"Files exceeding 500 LOC: {', '.join(high_loc_files)}")
        if total_loc > 1500:
            hard_score += 2.0
            reasons.append(f"Large total codebase context ({total_loc} LOC)")
        elif len(file_list) > 10:
            medium_score += 1.5
            reasons.append(f"Multi-file modification ({len(file_list)} files)")

    # Hard overrides take precedence
    if hard_score > 0 and hard_score >= easy_score and hard_score >= medium_score:
        confidence = min(0.95, 0.70 + (hard_score * 0.05))
        return {
            "difficulty": "HARD",
            "confidence": round(confidence, 2),
            "score": hard_score,
            "reasons": reasons,
        }

    # Easy tasks (boilerplate, tests, docs, config)
    if easy_score > 0 and easy_score >= hard_score and easy_score >= medium_score:
        confidence = min(0.95, 0.70 + (easy_score * 0.05))
        return {
            "difficulty": "EASY",
            "confidence": round(confidence, 2),
            "score": easy_score,
            "reasons": reasons,
        }

    # Medium tasks (features, endpoints, components)
    if medium_score > 0 or (not hard_matches and not easy_matches):
        confidence = 0.80 if medium_matches else 0.65
        if not reasons:
            reasons.append("Standard feature complexity without extreme heuristics")
        return {
            "difficulty": "MEDIUM",
            "confidence": round(confidence, 2),
            "score": medium_score or 1.0,
            "reasons": reasons,
        }

    # Fallback
    return {
        "difficulty": "MEDIUM",
        "confidence": 0.60,
        "score": 1.0,
        "reasons": ["Default medium classification"],
    }
