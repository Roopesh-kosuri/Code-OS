"""
prompt_enhancer.py - Prompt Enhancement Engine for CODE OS.
Classifies prompt quality via deterministic heuristics and enhances weak/vague
prompts using low-cost AI models before they reach the agent loop.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
from typing import Any, Callable, Coroutine, Optional

import httpx

from ..smart_router.model_router import DEFAULT_MODEL_TIERS
from app.features.settings.service import list_settings

logger = logging.getLogger(__name__)

# ── Session Cache & Metrics ───────────────────────────────────────────────────

_SESSION_ENHANCE_CACHE: dict[str, dict[str, Any]] = {}

_STATS: dict[str, int] = {
    "enhanced_count": 0,
    "accepted_count": 0,
    "reverted_count": 0,
    "tokens_saved_estimate": 0,
}

# Optional custom mock hook for unit tests
_custom_enhancer_fn: Optional[Callable[[str, dict[str, Any]], Coroutine[Any, Any, str]]] = None


def set_enhancer_llm_fn(fn: Optional[Callable[[str, dict[str, Any]], Coroutine[Any, Any, str]]]) -> None:
    """Set custom enhancer LLM hook for testing."""
    global _custom_enhancer_fn
    _custom_enhancer_fn = fn


def reset_enhancer_llm_fn() -> None:
    """Reset custom enhancer LLM hook."""
    global _custom_enhancer_fn
    _custom_enhancer_fn = None


def get_enhancement_stats() -> dict[str, int]:
    """Return prompt enhancement statistics."""
    return dict(_STATS)


def record_enhancement_action(action: str) -> None:
    """Record user interaction with enhanced prompt (accept, revert, dismiss)."""
    action_clean = action.lower().strip()
    if action_clean == "accept":
        _STATS["accepted_count"] += 1
        # Estimated tokens saved by avoiding ambiguous turn iterations (~450 tokens/turn)
        _STATS["tokens_saved_estimate"] += 450
    elif action_clean in ("revert", "keep_original", "reject"):
        _STATS["reverted_count"] += 1


def clear_enhancer_session_cache() -> None:
    """Clear session enhancement cache."""
    _SESSION_ENHANCE_CACHE.clear()


# ── Quality Classifier Heuristics ─────────────────────────────────────────────

VAGUE_VERB_PATTERNS = [
    re.compile(r"^\s*(?:please\s+)?(?:fix\s+it|fix\s+this|make\s+better|make\s+it\s+better|help|update\s+it|improve\s+this|improve\s+it|clean\s+up|do\s+the\s+thing|make\s+it\s+work|debug\s+this|debug\s+it|check\s+this|check\s+it|fix\s+bug|help\s+me)\s*$", re.IGNORECASE),
    re.compile(r"\b(fix it|make it better|make better|do the thing|clean up this)\b", re.IGNORECASE),
]

FILE_PATH_PATTERN = re.compile(
    r"(?:[\w.-]+[/\\][\w.-]+|[\w.-]+\.(?:py|ts|tsx|js|jsx|html|css|json|md|go|rs|cpp|c|h|yaml|yml|sql|toml))\b",
    re.IGNORECASE,
)

CODE_SYMBOL_PATTERN = re.compile(
    r"\b(?:def\s+\w+|class\s+\w+|function\s+\w+|import\s+\w+|const\s+\w+|let\s+\w+|\w+\(\)|bcrypt|jwt|sql|api|route|endpoint)\b",
    re.IGNORECASE,
)

ERROR_PATTERN = re.compile(
    r"\b(?:error|exception|traceback|failed|assert|status\s*code\s*\d+|401|403|404|500|syntaxerror|typeerror|valueerror)\b",
    re.IGNORECASE,
)

SUCCESS_CRITERIA_PATTERN = re.compile(
    r"\b(?:assert|test|verify|expect|ensure|check|spec|should\s+return|must\s+be|so\s+that)\b",
    re.IGNORECASE,
)

PRONOUN_TARGET_PATTERN = re.compile(
    r"^(?:please\s+)?(?:fix|debug|refactor|test|clean\s*up|improve|check|update)\s+(?:this|it|the\s+file|this\s+file|this\s+function|here)\s*$",
    re.IGNORECASE,
)


def classify_prompt_quality(prompt: str, active_file: Optional[str] = None) -> dict[str, Any]:
    """
    Classify prompt quality into 'good', 'weak', or 'vague' using deterministic heuristics (no LLM).
    Returns: {quality: 'good'|'weak'|'vague', issues: [...], score: float}
    """
    clean_p = prompt.strip() if prompt else ""
    if not clean_p:
        return {
            "quality": "vague",
            "issues": ["Prompt is empty"],
            "score": 0.0,
        }

    # 1. Check Active File Rescue
    # If user has an active file open and prompt references it via pronoun or short verb
    # e.g. 'fix this' + active_file='src/login/handler.py' -> good
    has_active_file = bool(active_file and active_file.strip())
    is_pronoun_command = bool(PRONOUN_TARGET_PATTERN.match(clean_p)) or clean_p.lower() in (
        "fix this", "fix it", "clean this", "test this", "debug this", "improve this", "update this"
    )

    if has_active_file and (is_pronoun_command or "this file" in clean_p.lower() or "this function" in clean_p.lower()):
        return {
            "quality": "good",
            "issues": [],
            "score": 0.85,
        }

    issues: list[str] = []
    score = 1.0

    # 2. Length check
    if len(clean_p) < 15:
        issues.append("Prompt is too brief (< 15 characters)")
        score -= 0.35

    # 3. Vague verbs check
    is_vague_verb = any(pat.search(clean_p) for pat in VAGUE_VERB_PATTERNS)
    if is_vague_verb:
        issues.append("Uses generic verbs without specific targets ('fix it', 'make better', etc.)")
        score -= 0.40

    # 4. Specificity check (file path, code symbol, error trace)
    has_file_ref = bool(FILE_PATH_PATTERN.search(clean_p))
    has_symbol_ref = bool(CODE_SYMBOL_PATTERN.search(clean_p))
    has_error_ref = bool(ERROR_PATTERN.search(clean_p))
    has_specificity = has_file_ref or has_symbol_ref or has_error_ref

    if not has_specificity:
        issues.append("Lacks specific targets (no file paths, symbols, classes, or error messages)")
        score -= 0.30

    # 5. Success criteria check
    has_success_criteria = bool(SUCCESS_CRITERIA_PATTERN.search(clean_p))
    if not has_success_criteria:
        issues.append("No explicit success criteria or verification expectations (e.g. tests, assertions)")
        score -= 0.15

    # 6. Ambiguous pronouns without active file
    has_pronouns = any(re.search(rf"\b{pronoun}\b", clean_p, re.IGNORECASE) for pronoun in ("it", "this", "that"))
    if has_pronouns and not has_active_file and not has_file_ref:
        issues.append("Contains ambiguous pronouns ('it', 'this') without an active file context")
        score -= 0.25

    # Ensure score stays bounded
    score = max(0.0, min(1.0, round(score, 2)))

    # Good criteria override if high specificity + clear intent
    if has_file_ref and (has_symbol_ref or has_success_criteria or has_error_ref) and len(clean_p) >= 25:
        return {
            "quality": "good",
            "issues": [],
            "score": 1.0,
        }

    if score >= 0.70 and not is_vague_verb:
        quality = "good"
    elif score >= 0.35:
        quality = "weak"
    else:
        quality = "vague"

    return {
        "quality": quality,
        "issues": issues,
        "score": score,
    }


# ── Cheap Model Selector ─────────────────────────────────────────────────────

HARD_TIER_MODELS = set(DEFAULT_MODEL_TIERS.get("HARD", [])) | {
    "anthropic/claude-sonnet-4-5",
    "claude-sonnet-4-5",
    "claude-3-7-sonnet-latest",
    "openai/gpt-4o",
    "gpt-4o",
    "nvidia-nim/meta/llama-3.2-11b-vision-instruct",
    "meta/llama-3.2-11b-vision-instruct",
}

CHEAP_CANDIDATE_MODELS = [
    ("groq", "openai/gpt-oss-20b"),
    ("groq", "llama-3.1-8b-instant"),
    ("openai", "gpt-4o-mini"),
    ("gemini", "gemini-2.5-flash"),
    ("deepseek", "deepseek-chat"),
    ("mistral", "mistral-small-latest"),
]


async def _is_ollama_reachable(base_url: str = "http://127.0.0.1:11434") -> bool:
    """Quick check if local Ollama server is active and reachable ($0 cost)."""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def select_cheap_enhancement_model() -> tuple[str, str]:
    """
    Select the cheapest available AI model for prompt rewriting.
    Hierarchy: local Ollama ($0) -> groq/openai/gpt-oss-20b / gpt-4o-mini -> cheapest active provider.
    NEVER selects HARD-tier models.
    """
    settings = await list_settings()
    ollama_url = settings.get("ollama.baseUrl") or "http://127.0.0.1:11434"

    # 1. Local Ollama if available
    if await _is_ollama_reachable(ollama_url):
        model = settings.get("ollama.model") or "llama3.2"
        return "ollama", model

    # 2. Check Groq API key
    if settings.get("groq.apiKey"):
        return "groq", "openai/gpt-oss-20b"

    # 3. Check OpenAI API key
    if settings.get("openai.apiKey"):
        return "openai", "gpt-4o-mini"

    # 4. Check Gemini API key
    if settings.get("gemini.apiKey"):
        return "gemini", "gemini-2.5-flash"

    # 5. Check Deepseek API key
    if settings.get("deepseek.apiKey"):
        return "deepseek", "deepseek-chat"

    # Safe default: cheapest model from presets
    prov, mod = CHEAP_CANDIDATE_MODELS[0]
    return prov, mod


# ── Prompt Enhancer Service ───────────────────────────────────────────────────

ENHANCER_SYSTEM_PROMPT = (
    "You are a prompt engineer for an AI coding assistant. Improve the user's coding request to be "
    "specific, actionable, complete. Add: (1) which files likely need changes, (2) what success looks like, "
    "(3) constraints. Keep concise. Output ONLY the improved prompt."
)


def _compute_prompt_changes(original: str, enhanced: str) -> list[str]:
    """Extract notable additions and clarifications made in the enhanced prompt."""
    changes: list[str] = []
    orig_lower = original.lower()
    enh_lower = enhanced.lower()

    if FILE_PATH_PATTERN.search(enhanced) and not FILE_PATH_PATTERN.search(original):
        changes.append("Identified specific target file(s)")

    if SUCCESS_CRITERIA_PATTERN.search(enhanced) and not SUCCESS_CRITERIA_PATTERN.search(original):
        changes.append("Added concrete verification & success criteria")

    if CODE_SYMBOL_PATTERN.search(enhanced) and not CODE_SYMBOL_PATTERN.search(original):
        changes.append("Specified code symbols and APIs")

    if len(enhanced) > len(original) + 20 and not changes:
        changes.append("Added detailed implementation requirements")

    if not changes:
        changes.append("Clarified action and expected outcome")

    return changes


async def enhance_prompt(
    prompt: str,
    quality: Optional[dict[str, Any]] = None,
    workspace_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Enhance a weak or vague prompt using a low-cost model with workspace context.
    Fail-open: any error or timeout (3s cap) returns the original prompt untouched.
    """
    clean_p = prompt.strip() if prompt else ""
    if not clean_p:
        return {
            "enhanced": clean_p,
            "original": clean_p,
            "changes": [],
            "model_used": "none",
        }

    # Session cache check
    if clean_p in _SESSION_ENHANCE_CACHE:
        logger.debug("enhance_prompt: returning session cached result for prompt")
        return dict(_SESSION_ENHANCE_CACHE[clean_p])

    # If prompt is already good, pass through untouched (zero token waste)
    q = quality or classify_prompt_quality(clean_p, (workspace_context or {}).get("active_file"))
    if q.get("quality") == "good":
        result = {
            "enhanced": clean_p,
            "original": clean_p,
            "changes": [],
            "model_used": "pass-through",
        }
        _SESSION_ENHANCE_CACHE[clean_p] = result
        return result

    # Build context message
    ctx = workspace_context or {}
    context_lines = [f"User prompt: {clean_p}"]
    if ctx.get("active_file"):
        context_lines.append(f"Active file: {ctx['active_file']}")
    if ctx.get("open_tabs"):
        context_lines.append(f"Open editor tabs: {', '.join(ctx['open_tabs'])}")
    if ctx.get("git_diff_summary"):
        context_lines.append(f"Recent changes: {ctx['git_diff_summary']}")
    if ctx.get("rag_symbols"):
        context_lines.append(f"Related symbols: {', '.join(ctx['rag_symbols'])}")

    user_content = "\n".join(context_lines)

    # Unit test hook shortcut
    global _custom_enhancer_fn
    if _custom_enhancer_fn is not None:
        try:
            enhanced_text = await asyncio.wait_for(_custom_enhancer_fn(clean_p, ctx), timeout=3.0)
            enhanced_text = enhanced_text.strip()
            changes = _compute_prompt_changes(clean_p, enhanced_text)
            _STATS["enhanced_count"] += 1
            res = {
                "enhanced": enhanced_text,
                "original": clean_p,
                "changes": changes,
                "model_used": "test-mock-cheap",
            }
            _SESSION_ENHANCE_CACHE[clean_p] = res
            return res
        except Exception as exc:
            logger.warning("enhance_prompt: mock hook exception (fail-open): %s", exc)
            return {
                "enhanced": clean_p,
                "original": clean_p,
                "changes": [],
                "model_used": "fallback",
            }

    # Model resolution
    provider_name, model_name = await select_cheap_enhancement_model()

    # Safety assertion: Never use HARD-tier models for enhancement
    full_model_tag = f"{provider_name}/{model_name}"
    if full_model_tag in HARD_TIER_MODELS or model_name in HARD_TIER_MODELS:
        logger.warning("enhance_prompt: HARD tier model rejected (%s), downgrading to cheap", full_model_tag)
        provider_name, model_name = "groq", "openai/gpt-oss-20b"

    # Execution with 3-second hard timeout (fail-open)
    try:
        from ..service import provider_for
        from ..schemas import ChatMessage, ChatRequest

        req = ChatRequest(
            messages=[
                ChatMessage(role="system", content=ENHANCER_SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_content),
            ],
            model=model_name,
            provider=provider_name,
            temperature=0.2,
            max_tokens=250,
        )

        async def _call_llm() -> str:
            provider = await provider_for(req)
            chunks: list[str] = []
            async for chunk in provider.stream_chat(req.messages, model_name, temperature=0.2, max_tokens=250):
                chunks.append(chunk)
            return "".join(chunks).strip()

        raw_enhanced = await asyncio.wait_for(_call_llm(), timeout=3.0)
        # Clean quotes or redundant prefixes
        enhanced_clean = re.sub(r'^(?:Enhanced prompt|Improved prompt):\s*', '', raw_enhanced, flags=re.IGNORECASE).strip('"\n\r ')

        if not enhanced_clean:
            enhanced_clean = clean_p

        changes = _compute_prompt_changes(clean_p, enhanced_clean)
        _STATS["enhanced_count"] += 1

        result = {
            "enhanced": enhanced_clean,
            "original": clean_p,
            "changes": changes,
            "model_used": f"{provider_name}/{model_name}",
        }
        _SESSION_ENHANCE_CACHE[clean_p] = result
        return result

    except Exception as exc:
        logger.info("enhance_prompt: error/timeout (fail-open returning original): %s", exc)
        return {
            "enhanced": clean_p,
            "original": clean_p,
            "changes": [],
            "model_used": "fallback",
        }
