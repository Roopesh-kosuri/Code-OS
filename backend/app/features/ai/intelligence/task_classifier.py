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

QUESTION_STARTERS = (
    "what does", "how does", "what is", "how do i", "explain", "why is",
    "where is", "can you explain", "tell me about", "describe", "summary of",
    "how to", "what are", "is there", "why does", "could you explain",
)

_global_llm_classifier: Optional[Callable] = None


def set_llm_classifier_fn(fn: Optional[Callable]) -> None:
    """Set custom or mock LLM classifier callable."""
    global _global_llm_classifier
    _global_llm_classifier = fn


def reset_llm_classifier_fn() -> None:
    """Reset custom or mock LLM classifier callable."""
    global _global_llm_classifier
    _global_llm_classifier = None


ESCALATION_KEYWORDS = frozenset({
    "team", "multi-agent", "5-agent", "full stack", "end-to-end", "architectural",
    "full-stack", "fullstack", "multi agent", "5 agent", "team approach",
})


def escalation_classifier(
    task_description: str,
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Classify whether a task exceeds single-agent capability and warrants
    escalation to the 5-agent DAG team (Planner, Coder, Tester, Reviewer, Documenter).

    Triggers (any 2+ = escalate):
    1. Multi-file refactor (>5 files, architectural change)
    2. New feature spanning multiple layers (DB + API + UI + tests)
    3. Performance optimization requiring profiling
    4. Security audit / hardening task
    5. Complex algorithm implementation (>500 LOC estimate)
    6. Migration (DB schema, API version, framework upgrade)
    7. User explicitly asks for "team" or "multi-agent" approach

    Confidence Scoring:
    - 0-1 triggers: confidence <0.3 -> no escalation
    - 2-3 triggers: confidence 0.5-0.75 -> suggest escalation
    - 4+ triggers: confidence >0.8 -> strongly recommend
    """
    text = (task_description or "").lower()
    ctx = context or {}
    matched_triggers: list[str] = []
    reasons: list[str] = []

    # 1. Multi-file refactor (>5 files, architectural change, or module-wide implementation)
    file_list = ctx.get("file_list") or ctx.get("files") or []
    file_count = len(file_list) if isinstance(file_list, (list, tuple)) else 0
    refactor_detected = bool(re.search(r"\b(?:refactor|restructure|redesign|rewrite|overhaul)\b", text))
    module_wide_implementation = bool(re.search(r"\b(?:implement|build|create|setup|develop)\b[\s\S]*?\b(?:across\s+(?:the\s+)?entire|throughout\s+(?:the\s+)?entire|across\s+all|across\s+multiple)\b", text))
    across_multiple = bool(re.search(r"across\s+[\w\s,]+(?:,|\band\b)[\w\s,]+", text)) or bool(re.search(r"\bacross\s+(?:the\s+)?entire\s+[\w\-]+\s+(?:module|system|package|codebase)\b", text))
    has_arch_kw = "architectural" in text or "architecture" in text

    # 2. New feature spanning multiple layers (DB + API + UI + tests)
    has_full_stack = bool(re.search(r"\b(?:full-stack|full\s+stack|fullstack|end-to-end|end\s+to\s+end|cross-cutting|all layers|multiple layers)\b", text))
    layers_detected = 0
    if re.search(r"\b(?:db|database|sql|sqlite|postgres|mongo|schema|migration|models|orm|tables?|session|sessions|cache|store|token|tokens|refresh)\b", text):
        layers_detected += 1
    if re.search(r"\b(?:api|endpoint|routes?|controller|handler|backend|rest|graphql|fastapi|providers?|oauth2?|auth\s+flow|login\s+module)\b", text):
        layers_detected += 1
    if re.search(r"\b(?:ui|frontend|react|view|component|css|html|dialog|modal|client|screen)\b", text):
        layers_detected += 1
    if re.search(r"\b(?:test|tests|testing|e2e|integration|unit\s+tests?|coverage|validators?|rate\s+limit(?:er|ing)?)\b", text):
        layers_detected += 1

    full_stack_multifile = (has_full_stack and layers_detected >= 2) or layers_detected >= 3
    if (
        (refactor_detected and (file_count > 5 or ">5 files" in text or "5+ files" in text or across_multiple or has_arch_kw))
        or (file_count > 5 and has_arch_kw)
        or (module_wide_implementation and across_multiple)
        or full_stack_multifile
    ):
        matched_triggers.append("multi_file_refactor")
        reasons.append("Multi-file refactor or full-stack implementation spanning multiple components/layers")

    if has_full_stack or layers_detected >= 2 or (refactor_detected and across_multiple) or (module_wide_implementation and layers_detected >= 2):
        matched_triggers.append("cross_layer_feature")
        reasons.append("Feature spans multiple codebase layers (data, API, UI, or test suite)")

    # 3. Performance optimization requiring profiling
    if re.search(r"\b(?:profiling|profiler|profile|benchmark|benchmarking|optimize\s+latency|latency\s+optimization|bottleneck|memory\s+leak|cpu\s+profiling|load\s+test|stress\s+test|throughput|p99)\b", text):
        matched_triggers.append("performance_profiling")
        reasons.append("Performance optimization requiring profiling or benchmarking")

    # 4. Security audit / hardening task
    if re.search(r"\b(?:security\s+audit|hardening|vulnerability|penetration\s+test|pen\s+test|cve|auth\s+hardening|security\s+review|threat\s+model|authentication\s+system|oauth2?|rate\s+limit(?:er|ing)|session\s+management|sanitiz(?:e|ation)|zero\s+trust)\b", text):
        matched_triggers.append("security_hardening")
        reasons.append("Security audit or system hardening across sensitive surfaces")

    # 5. Complex algorithm implementation (>500 LOC estimate)
    if re.search(r"\b(?:>500\s*loc|500\+\s*loc|500\s+lines\s+of\s+code|complex\s+algorithm|distributed\s+consensus|raft|paxos|compiler|ast\s+parser|bytecode|custom\s+parser|graph\s+algorithm|dynamic\s+programming|b-tree|red-black\s+tree)\b", text):
        matched_triggers.append("complex_algorithm")
        reasons.append("Complex algorithm implementation or high estimated LOC (>500)")

    # 6. Migration (DB schema, API version, framework upgrade)
    if re.search(r"\b(?:schema\s+migration|db\s+migration|database\s+migration|api\s+version|framework\s+upgrade|upgrade\s+from|v1\s+to\s+v2|breaking\s+changes\s+migration)\b", text) or ("migration" in text and ("schema" in text or "version" in text or "db" in text or "framework" in text)):
        matched_triggers.append("migration")
        reasons.append("Migration spanning database schemas, API versions, or frameworks")

    # 7. User explicitly asks for "team" or "multi-agent" approach
    if re.search(r"\b(?:team|multi-agent|multi\s+agent|5-agent|5\s+agent|agent\s+team|team\s+approach|swarm|orchestrator)\b", text):
        matched_triggers.append("explicit_team_request")
        reasons.append("User explicitly requested a team or multi-agent orchestration approach")

    count = len(matched_triggers)
    has_high_loc = bool(re.search(r"\b(?:>500\s*loc|500\+\s*loc|500\s+lines\s+of\s+code)\b", text))
    has_distributed_consensus = bool(re.search(r"\b(?:distributed\s+consensus|raft|paxos)\b", text))
    has_standalone_hard = (
        ("complex_algorithm" in matched_triggers and (has_high_loc or has_distributed_consensus))
        or ("explicit_team_request" in matched_triggers)
    )
    should_escalate = count >= 2 or has_standalone_hard

    # Confidence scoring per spec:
    # 0-1 triggers: <0.3 (unless standalone hard >500 LOC/distributed consensus/explicit team)
    # 2-3 triggers: 0.5-0.75
    # 4+ triggers: >0.8
    if count == 0:
        confidence = 0.10
    elif count == 1:
        confidence = 0.70 if has_standalone_hard else 0.25
    elif count == 2:
        confidence = 0.65
    elif count == 3:
        confidence = 0.75
    elif count == 4:
        confidence = 0.85
    else:
        confidence = min(0.95, 0.85 + (count - 4) * 0.03)

    # Adaptive modifier from feedback loop
    try:
        from app.features.ai.intelligence.escalation_tracker import get_confidence_modifier
        confidence = max(0.05, min(0.99, confidence + get_confidence_modifier()))
    except Exception:
        pass

    confidence = round(confidence, 2)
    reasoning = "; ".join(reasons) if reasons else "Task is within single-agent capability scope"

    return {
        "should_escalate": should_escalate,
        "reasoning": reasoning,
        "confidence": confidence,
        "triggers": matched_triggers,
    }


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
    clean_prompt = re.sub(r'<untrusted_web_content[\s\S]*?</untrusted_web_content>', '', clean_prompt, flags=re.IGNORECASE)
    clean_prompt = re.sub(r'\[web content context\]:[\s\S]*', '', clean_prompt, flags=re.IGNORECASE)
    clean_prompt = re.sub(r'\[attached image visual findings\][\s\S]*?\[end attached image visual findings\]', '', clean_prompt, flags=re.IGNORECASE)
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

    # Conceptual inquiry / question
    if any(clean_q.startswith(qs) or f" {qs}" in clean_q for qs in QUESTION_STARTERS) and not any(w in clean_q for w in ("create", "build", "edit", "fix", "write", "modify", "refactor", "architect")):
        from app.features.ai.harness.prompt_builder import _is_codebase_inquiry
        if _is_codebase_inquiry(clean_q):
            return {
                "tier": "EASY",
                "difficulty": "EASY",
                "effort_tier": 1,
                "confidence": 0.85,
                "score": 0.5,
                "reasons": ["Fast path: codebase conceptual inquiry (promoted to Tier 1 for semantic RAG)"],
            }
        return {
            "tier": "EASY",
            "difficulty": "FAST",
            "effort_tier": 0,
            "confidence": 0.85,
            "score": 0.5,
            "reasons": ["Fast path: conceptual inquiry / question"],
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

    # Deep compound project creation with tests / readme
    creation_verbs = ("build", "create", "scaffold", "implement", "setup", "make", "generate", "write")
    compound_test_markers = (
        "with test", "and test", "with tests", "and tests", "with unit test", "with readme",
        "and readme", "test suite", "tests and", "tests &", "tests +", "including test",
    )
    if any(v in text for v in creation_verbs) and any(t in text for t in compound_test_markers):
        hard_score += 6.0
        reasons.append("Deep think: project creation with tests/readme detected")

    # Explicit size patterns: "1000 lines", "1000+ lines", "500 lines", "full stack", "fullstack"
    if re.search(r"\b\d+\+?\s*lines?\b", text) or "full stack" in text or "fullstack" in text:
        hard_score += 5.0
        reasons.append("Deep think: explicit size / full-stack scope detected")

    # Multi-feature join patterns
    if re.search(r"\b(with|including|having)\s+[\w\s-]+,\s*[\w\s-]+(\s+(and|&)\s+[\w\s-]+)?", text):
        hard_score += 5.0
        reasons.append("Deep think: multi-feature architecture detected")

    # Scope words in text
    tier2_scope_words = (
        "clone", "entire", "full", "complete", "website", "dashboard",
        "portfolio", "from scratch", "architecture", "entire codebase", "all files",
        "across the project", "full system", "redesign", "port to", "migrate",
        "rewrite", "debug and fix all", "refactor",
    )
    for word in tier2_scope_words:
        if re.search(rf"\b{re.escape(word)}\b", text):
            hard_score += 3.5
            reasons.append(f"Deep think: scope keyword '{word}' detected")

    # Quick action verbs (single-target actions)
    quick_task_verbs = (
        "add", "fix", "change", "rename", "update", "run", "edit",
        "modify", "replace", "delete", "remove", "insert", "append",
        "set", "format", "lint",
    )
    matched_quick_verb = None
    for verb in quick_task_verbs:
        if re.search(rf"\b{re.escape(verb)}\b", text):
            matched_quick_verb = verb
            break

    if matched_quick_verb and hard_score == 0:
        easy_score += 3.0
        reasons.append(f"Quick task: single-target action '{matched_quick_verb}'")

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

    difficulty = "MEDIUM"
    effort_tier = 1

    # 2. Fall back to weighted feature heuristic (Option B)
    if not llm_success:
        h_res = _heuristic_classify(features)
        tier = h_res["tier"]
        difficulty = h_res.get("difficulty", tier)
        effort_tier = h_res.get("effort_tier", 1 if tier == "MEDIUM" else (2 if tier == "HARD" else 0))
        confidence = h_res["confidence"]
        score = h_res["score"]
        reasons = h_res["reasons"]
        method = "heuristic"
    else:
        difficulty = tier
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
    from app.features.ai.smart_router.model_router import (
        parse_model_string,
        _normalize_provider,
        DEFAULT_MODEL_TIERS,
    )
    prov, m_name = parse_model_string(recommended_model)
    norm_p = _normalize_provider(prov)
    verified = get_verified_models(norm_p)
    if verified and m_name not in verified:
        # Fallback to verified model for provider or default tier
        fallback = verified[0] if verified else DEFAULT_MODEL_TIERS["EASY"][0]
        recommended_model = f"{norm_p}/{fallback}"

    # 6. Adaptive Escalation Classifier
    esc_res = escalation_classifier(task_description, context=context)
    escalation_recommended = bool(esc_res["should_escalate"] and esc_res["confidence"] > 0.6)
    escalation_reasoning = esc_res["reasoning"] if escalation_recommended else esc_res.get("reasoning", "")

    reasoning_str = "; ".join(reasons)

    return {
        "tier": tier,
        "difficulty": difficulty,
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
        "escalation_recommended": escalation_recommended,
        "escalation_reasoning": escalation_reasoning,
        "escalation_confidence": esc_res.get("confidence", 0.0),
        "escalation_triggers": esc_res.get("triggers", []),
    }

