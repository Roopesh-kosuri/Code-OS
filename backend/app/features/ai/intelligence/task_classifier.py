"""
task_classifier.py — Unified Task Difficulty and Effort Classifier for CODE OS.

Unifies task difficulty classification across Smart Router, Chat Harness,
and Team Orchestrator with:
1. LLM-based classification with explainable reasoning (Option A)
2. Weighted feature heuristic fallback (Option B)
3. Context-window awareness (>100K tokens -> large-context model, <10K -> fast model)
4. Price awareness & budget guard (>=80% spend guard -> downgrade to EASY tier)
5. Live catalog validation
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.features.ai.smart_router.model_router import (
    DEFAULT_MODEL_TIERS,
    MODEL_TIERS,
    parse_model_string,
    _normalize_provider,
)
from app.features.ai.providers.catalog import get_verified_models

logger = logging.getLogger(__name__)

HARD_KEYWORDS = frozenset({
    "auth", "authentication", "encryption", "crypto", "payment", "stripe",
    "algorithm", "security", "parser", "compiler", "optimization", "jwt",
    "oauth", "concurrency", "deadlock", "distributed", "consensus", "sandbox",
    "vulnerability", "invariant", "microkernel", "zero-knowledge", "assembly"
})

EASY_KEYWORDS = frozenset({
    "boilerplate", "test", "tests", "unit test", "doc", "docs", "documentation",
    "readme", "comment", "config", "configuration", "css", "style", "styling",
    "scaffolding", "scaffold", "lint", "format", "typo", "bump", "version",
    "export", "import", "cleanup", "rename"
})

MEDIUM_KEYWORDS = frozenset({
    "component", "feature", "api", "endpoint", "crud", "controller", "handler",
    "route", "service", "model", "schema", "table", "migration", "filter",
    "view", "form", "dashboard", "panel", "state", "store", "selector"
})

GREETINGS = frozenset({
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "greetings", "sup", "howdy", "yo", "hi there", "hello there", "hey there",
})

REVIEW_KEYWORDS = frozenset({
    "review", "critique", "feedback", "evaluate", "what do you think", "how is my",
    "check my", "inspect my", "thoughts on", "how does this look", "summarize",
    "summarise", "summary", "read this", "go through", "overview", "tell me about",
    "what does this say", "explain my", "look at my", "break down",
})

_global_llm_classifier: Optional[Callable] = None


def set_llm_classifier_fn(fn: Optional[Callable]) -> None:
    """Set custom or mock LLM classifier callable."""
    global _global_llm_classifier
    _global_llm_classifier = fn


def reset_llm_classifier_fn() -> None:
    """Reset custom or mock LLM classifier callable."""
    global _global_llm_classifier
    _global_llm_classifier = None


def extract_task_features(
    task_description: str,
    file_list: Optional[list[str]] = None,
    context: Optional[dict] = None,
) -> dict[str, Any]:
    """Extract quantitative and qualitative features from task and codebase context."""
    text = task_description or ""
    clean_prompt = re.sub(r'<attached_files[\s\S]*?</attached_files>', '', text, flags=re.IGNORECASE)
    clean_prompt = re.sub(r'<untrusted_file_content[\s\S]*?</untrusted_file_content>', '', clean_prompt, flags=re.IGNORECASE)
    clean_prompt = re.sub(r'<file[\s\S]*?</file>', '', clean_prompt, flags=re.IGNORECASE)
    words = set(re.findall(r"\b\w+\b", clean_prompt.lower()))

    hard_matches = sorted(words.intersection(HARD_KEYWORDS))
    easy_matches = sorted(words.intersection(EASY_KEYWORDS))
    medium_matches = sorted(words.intersection(MEDIUM_KEYWORDS))

    total_loc = 0
    high_loc_files = []
    file_count = len(file_list) if file_list else 0
    cross_module_imports = set()

    if file_list:
        for fpath_str in file_list:
            try:
                p = Path(fpath_str)
                if p.is_file():
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()
                    loc = len(lines)
                    total_loc += loc
                    if loc > 500:
                        high_loc_files.append(f"{p.name} ({loc} LOC)")
                    for imp in re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", content, re.MULTILINE):
                        cross_module_imports.add(imp)
            except Exception:
                continue

    if context and isinstance(context, dict):
        if "total_loc" in context and not total_loc:
            total_loc = int(context["total_loc"])
        if "file_count" in context and not file_count:
            file_count = int(context["file_count"])
        if "estimated_tokens" in context:
            estimated_tokens = int(context["estimated_tokens"])
        else:
            estimated_tokens = (total_loc * 4) + (len(text.split()) * 2)
    else:
        estimated_tokens = (total_loc * 4) + (len(text.split()) * 2)

    return {
        "text": text,
        "clean_prompt": clean_prompt,
        "words": words,
        "hard_matches": hard_matches,
        "easy_matches": easy_matches,
        "medium_matches": medium_matches,
        "file_count": file_count,
        "total_loc": total_loc,
        "high_loc_files": high_loc_files,
        "deps_count": len(cross_module_imports),
        "estimated_tokens": estimated_tokens,
    }


def _heuristic_classify(features: dict[str, Any]) -> dict[str, Any]:
    """Option B: Weighted feature heuristic classifier."""
    text = features["clean_prompt"].lower().strip()
    words = features["words"]
    hard_matches = features["hard_matches"]
    easy_matches = features["easy_matches"]
    medium_matches = features["medium_matches"]
    file_count = features["file_count"]
    total_loc = features["total_loc"]
    high_loc_files = features["high_loc_files"]
    deps_count = features["deps_count"]

    clean_q = re.sub(r"[^\w\s]", "", text).strip()
    if clean_q in GREETINGS or (any(clean_q.startswith(g + " ") for g in GREETINGS) and len(clean_q.split()) <= 4):
        return {
            "tier": "EASY",
            "difficulty": "FAST",
            "effort_tier": 0,
            "confidence": 0.95,
            "score": 0.0,
            "reasons": ["Fast path: conversational greeting"],
        }

    # Document review inquiry
    if any(rk in clean_q for rk in REVIEW_KEYWORDS) and not any(w in clean_q for w in ("create", "build", "edit", "fix", "write", "modify")):
        return {
            "tier": "EASY",
            "difficulty": "FAST",
            "effort_tier": 0,
            "confidence": 0.90,
            "score": 0.5,
            "reasons": ["Fast path: document review inquiry"],
        }

    reasons: list[str] = []
    hard_score = len(hard_matches) * 3.0
    easy_score = len(easy_matches) * 2.0
    medium_score = len(medium_matches) * 1.5

    if hard_matches:
        reasons.append(f"Contains high-complexity keywords: {', '.join(hard_matches)}")
    if easy_matches:
        reasons.append(f"Contains low-complexity keywords: {', '.join(easy_matches)}")
    if medium_matches:
        reasons.append(f"Contains standard feature keywords: {', '.join(medium_matches)}")

    if file_count > 20:
        hard_score += 3.5
        reasons.append(f"Large multi-file modification ({file_count} files touched > 20)")
    elif file_count > 10:
        medium_score += 2.0
        reasons.append(f"Multi-file modification ({file_count} files touched > 10)")

    if high_loc_files:
        hard_score += len(high_loc_files) * 2.5
        reasons.append(f"Files exceeding 500 LOC: {', '.join(high_loc_files)}")

    if total_loc > 1500:
        hard_score += 2.5
        reasons.append(f"Large codebase context ({total_loc} LOC > 1500)")

    if deps_count > 5:
        hard_score += 2.0
        reasons.append(f"Cross-module dependencies ({deps_count} modules)")

    # Scope words in text
    if any(sw in text for sw in ("architecture", "refactor", "clone", "full stack", "fullstack", "entire codebase")):
        hard_score += 3.0
        reasons.append("Architectural/full-system scope keywords present")

    if hard_score > 0 and hard_score >= easy_score and hard_score >= medium_score:
        confidence = min(0.95, 0.70 + (hard_score * 0.05))
        return {
            "tier": "HARD",
            "difficulty": "HARD",
            "effort_tier": 2,
            "confidence": round(confidence, 2),
            "score": hard_score,
            "reasons": reasons,
        }

    if easy_score > 0 and easy_score >= hard_score and easy_score >= medium_score:
        confidence = min(0.95, 0.70 + (easy_score * 0.05))
        return {
            "tier": "EASY",
            "difficulty": "EASY",
            "effort_tier": 1,
            "confidence": round(confidence, 2),
            "score": easy_score,
            "reasons": reasons,
        }

    confidence = 0.80 if medium_matches else 0.65
    if not reasons:
        reasons.append("Standard feature complexity without extreme heuristics")
    return {
        "tier": "MEDIUM",
        "difficulty": "MEDIUM",
        "effort_tier": 1,
        "confidence": round(confidence, 2),
        "score": medium_score or 1.0,
        "reasons": reasons,
    }


def classify_task(
    task_description: str,
    context: Optional[dict] = None,
    file_list: Optional[list[str]] = None,
    use_llm: bool = True,
    budget_percent: Optional[float] = None,
    llm_fn: Optional[Callable] = None,
) -> dict[str, Any]:
    """
    Unified task difficulty classification entrypoint across CODE OS.

    Returns:
        {
            "tier": "HARD" | "MEDIUM" | "EASY",
            "difficulty": "HARD" | "MEDIUM" | "EASY" | "FAST",
            "effort_tier": int (0, 1, 2),
            "confidence": float,
            "score": float,
            "reasoning": str,
            "reasons": list[str],
            "features": dict,
            "recommended_model": str,
            "method": "llm" | "heuristic",
            "budget_downgraded": bool,
            "context_window_tier": "large" | "standard" | "compact",
        }
    """
    features = extract_task_features(task_description, file_list=file_list, context=context)
    tier = "MEDIUM"
    confidence = 0.70
    score = 1.0
    reasons: list[str] = []
    method = "heuristic"

    # 1. Try LLM classification (Option A) if requested or callable provided
    active_llm = llm_fn or _global_llm_classifier
    llm_success = False

    if use_llm and active_llm is not None:
        try:
            prompt_input = {
                "task": task_description,
                "file_count": features["file_count"],
                "total_loc": features["total_loc"],
                "deps_count": features["deps_count"],
            }
            res = active_llm(task_description, prompt_input)
            if isinstance(res, str):
                res_clean = res.strip()
                if "{" in res_clean and "}" in res_clean:
                    json_str = res_clean[res_clean.find("{"):res_clean.rfind("}") + 1]
                    res = json.loads(json_str)
                else:
                    res = {"tier": res_clean, "reasoning": f"LLM classified as {res_clean}"}

            if isinstance(res, dict) and "tier" in res:
                parsed_tier = str(res["tier"]).strip().upper()
                if parsed_tier in ("HARD", "MEDIUM", "EASY"):
                    tier = parsed_tier
                    confidence = float(res.get("confidence", 0.90))
                    score = float(res.get("score", 3.0 if tier == "HARD" else (1.0 if tier == "EASY" else 2.0)))
                    llm_reasoning = res.get("reasoning") or f"LLM classified task as {tier}"
                    reasons = [llm_reasoning]
                    method = "llm"
                    llm_success = True
        except Exception as exc:
            logger.debug("LLM classification failed, falling back to heuristic: %s", exc)

    # 2. Fall back to weighted feature heuristic (Option B)
    if not llm_success:
        h_res = _heuristic_classify(features)
        tier = h_res["tier"]
        confidence = h_res["confidence"]
        score = h_res["score"]
        reasons = h_res["reasons"]
        method = "heuristic"

    # Map effort tier
    if tier == "HARD":
        effort_tier = 2
    elif tier == "EASY":
        effort_tier = 1 if features["file_count"] > 0 or features["total_loc"] > 0 else 0
    else:
        effort_tier = 1

    # 3. Context-Window Awareness
    estimated_tokens = features["estimated_tokens"]
    context_window_tier = "standard"
    if estimated_tokens > 100_000:
        context_window_tier = "large"
        recommended_model = "anthropic/claude-sonnet-4-5"
        reasons.append(f"High context requirement ({estimated_tokens:,} tokens > 100K): routed to large-context model")
    elif estimated_tokens < 10_000:
        context_window_tier = "compact"
        recommended_model = "groq/openai/gpt-oss-120b"
        reasons.append(f"Compact task context ({estimated_tokens:,} tokens < 10K): routed to fast economical model")
    else:
        tier_models = MODEL_TIERS.get(tier, DEFAULT_MODEL_TIERS.get(tier, []))
        recommended_model = tier_models[0] if tier_models else "openai/gpt-4o"

    # 4. Price Awareness & Budget Guard
    budget_downgraded = False
    if budget_percent is not None and budget_percent >= 80.0:
        if tier != "EASY":
            tier = "EASY"
            effort_tier = 1
            recommended_model = "groq/openai/gpt-oss-120b"
            budget_downgraded = True
            reasons.append(f"Routing to EASY tier to save budget (spend guard at {budget_percent:.0f}% >= 80%)")

    # 5. Live Catalog Validation
    prov, m_name = parse_model_string(recommended_model)
    norm_p = _normalize_provider(prov)
    verified = get_verified_models(norm_p)
    if verified and m_name not in verified:
        # Fallback to verified model for provider or default tier
        fallback = verified[0] if verified else DEFAULT_MODEL_TIERS["EASY"][0]
        recommended_model = f"{norm_p}/{fallback}"

    reasoning_str = "; ".join(reasons)

    return {
        "tier": tier,
        "difficulty": tier,
        "effort_tier": effort_tier,
        "confidence": confidence,
        "score": score,
        "reasoning": reasoning_str,
        "reasons": reasons,
        "features": features,
        "recommended_model": recommended_model,
        "method": method,
        "budget_downgraded": budget_downgraded,
        "context_window_tier": context_window_tier,
    }
