"""
completion_service.py — High-speed inline code completion engine for CODE OS Monaco editor.

Provides fast, cost-controlled ghost-text suggestions at cursor position with:
- Strict context capping (last 80–120 lines / max 6k chars prefix, ~30 lines suffix)
- Ultra-low latency model routing (Groq 8B / fast cloud / local Ollama)
- Single-attempt 4.0s timeout with silent error failover
- Output sanitization (fences stripping, suffix overlap removal)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any
from pydantic import BaseModel, Field

from .providers.openai_compatible import OpenAICompatibleProvider
from .providers.ollama import OllamaProvider
from .schemas import ChatMessage
from ..settings.service import get_api_key, list_settings

logger = logging.getLogger(__name__)

# ── Context Budget Limits ───────────────────────────────────────────────────
MAX_PREFIX_CHARS = 6_000
MAX_PREFIX_LINES = 100
MAX_SUFFIX_CHARS = 1_500
MAX_SUFFIX_LINES = 30
COMPLETION_TIMEOUT_SECONDS = 4.0
DEFAULT_MAX_TOKENS = 128
DEFAULT_TEMPERATURE = 0.2


class CompletionRequest(BaseModel):
    workspace: str = ""
    path: str = ""
    language: str = "plaintext"
    prefix: str = ""
    suffix: str = ""
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=16, le=256)
    temperature: float = Field(default=DEFAULT_TEMPERATURE, ge=0.0, le=1.0)


class CompletionResponse(BaseModel):
    completion: str = ""
    model: str = ""
    latency_ms: float = 0.0
    input_tokens_est: int = 0


def _cap_context(prefix: str, suffix: str) -> tuple[str, str]:
    """Strictly cap prefix and suffix lines and character lengths."""
    # 1. Cap Prefix
    prefix_lines = prefix.split("\n")
    if len(prefix_lines) > MAX_PREFIX_LINES:
        prefix = "\n".join(prefix_lines[-MAX_PREFIX_LINES:])
    if len(prefix) > MAX_PREFIX_CHARS:
        prefix = prefix[-MAX_PREFIX_CHARS:]

    # 2. Cap Suffix
    suffix_lines = suffix.split("\n")
    if len(suffix_lines) > MAX_SUFFIX_LINES:
        suffix = "\n".join(suffix_lines[:MAX_SUFFIX_LINES])
    if len(suffix) > MAX_SUFFIX_CHARS:
        suffix = suffix[:MAX_SUFFIX_CHARS]

    return prefix, suffix


def _clean_completion_text(completion: str, suffix: str) -> str:
    """Sanitize model completion text: strip fences, markers, and suffix duplication."""
    if not completion:
        return ""

    text = completion

    # Strip any special FIM tokens if model echoed them
    text = re.sub(r"<\|(?:code_prefix|code_suffix|cursor_completion|end_of_text|fim_prefix|fim_suffix|fim_middle)\|>", "", text)

    # Strip markdown code blocks if the model wrapped it in ```...```
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        else:
            text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    # Don't repeat suffix start: check if completion ends with the start of the suffix
    clean_suffix = suffix.lstrip()
    if clean_suffix:
        # Check first line of suffix
        suffix_first_line = clean_suffix.split("\n")[0].strip()
        if suffix_first_line and len(suffix_first_line) >= 3:
            if text.rstrip().endswith(suffix_first_line):
                # Trim the duplicated line from completion
                idx = text.rstrip().rfind(suffix_first_line)
                if idx > 0:
                    text = text[:idx]

    return text


async def _resolve_fast_completion_provider() -> tuple[Any, str]:
    """Resolve the fastest available provider & model for sub-second code completions."""
    settings = await list_settings()

    # 1. Google Gemini — lowest latency & cleanest code completions (~200ms)
    gemini_key = await get_api_key("gemini")
    if gemini_key:
        model = settings.get("gemini.completionModel") or settings.get("gemini.model") or "gemini-2.5-flash"
        base_url = settings.get("gemini.baseUrl") or "https://generativelanguage.googleapis.com/v1beta/openai"
        provider = OpenAICompatibleProvider(base_url, gemini_key, timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_retries=0)
        return provider, model

    # 2. OpenAI
    openai_key = await get_api_key("openai")
    if openai_key:
        model = settings.get("openai.completionModel") or settings.get("openai.model") or "gpt-4o-mini"
        base_url = settings.get("openai.baseUrl") or "https://api.openai.com/v1"
        provider = OpenAICompatibleProvider(base_url, openai_key, timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_retries=0)
        return provider, model

    # 3. DeepSeek
    deepseek_key = await get_api_key("deepseek")
    if deepseek_key:
        model = settings.get("deepseek.completionModel") or settings.get("deepseek.model") or "deepseek-chat"
        base_url = settings.get("deepseek.baseUrl") or "https://api.deepseek.com/v1"
        provider = OpenAICompatibleProvider(base_url, deepseek_key, timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_retries=0)
        return provider, model

    # 4. Groq
    groq_key = await get_api_key("groq")
    if groq_key:
        groq_model = settings.get("groq.completionModel") or settings.get("groq.model") or "llama-3.1-8b-instant"
        base_url = settings.get("groq.baseUrl") or "https://api.groq.com/openai/v1"
        provider = OpenAICompatibleProvider(base_url, groq_key, timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_retries=0, provider_id="groq")
        return provider, groq_model

    # 5. NVIDIA NIM
    nim_key = await get_api_key("nvidia-nim")
    if nim_key:
        nim_model = settings.get("nvidia-nim.completionModel") or "meta/llama-3.1-8b-instruct"
        base_url = settings.get("nvidia-nim.baseUrl") or "https://integrate.api.nvidia.com/v1"
        provider = OpenAICompatibleProvider(base_url, nim_key, timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_retries=0)
        return provider, nim_model

    # 6. Generic OpenAI-compatible
    compat_key = await get_api_key("openai-compatible")
    if compat_key:
        model = settings.get("openai-compatible.model") or "gpt-4o-mini"
        base_url = settings.get("openai-compatible.baseUrl") or "https://api.openai.com/v1"
        provider = OpenAICompatibleProvider(base_url, compat_key, timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_retries=0)
        return provider, model

    # 7. Local Ollama fallback
    ollama_url = settings.get("ollama.baseUrl") or "http://127.0.0.1:11434"
    ollama_model = settings.get("ollama.model") or "llama3"
    provider = OllamaProvider(ollama_url, timeout_seconds=COMPLETION_TIMEOUT_SECONDS, max_retries=0)
    return provider, ollama_model


async def generate_inline_completion(req: CompletionRequest) -> CompletionResponse:
    """Generate a fast, single-attempt inline code completion at cursor.
    
    Guardrail: Single attempt only. Any error/timeout returns empty string silently.
    """
    start_time = time.time()

    # 1. Budget and cap context window
    prefix, suffix = _cap_context(req.prefix, req.suffix)
    if not prefix.strip() and not suffix.strip():
        return CompletionResponse(completion="", latency_ms=0.0)

    est_tokens = int((len(prefix) + len(suffix)) / 4)

    # 2. Resolve fast provider
    try:
        provider, model_name = await _resolve_fast_completion_provider()
    except Exception as exc:
        logger.debug("completion: provider resolution failed: %s", exc)
        return CompletionResponse(completion="", latency_ms=0.0)

    # 3. Construct Fill-In-the-Middle (FIM) prompt
    system_prompt = (
        "You are an ultra-fast inline code autocomplete engine for CODE OS.\n"
        "Given the code before the cursor (prefix) and after the cursor (suffix), output ONLY the exact code to be inserted at the cursor position.\n"
        "Strict rules:\n"
        "- Output ONLY the insertion text. Do NOT wrap in markdown code fences (```).\n"
        "- Do NOT add explanations, conversational comments, or greetings.\n"
        "- Do NOT repeat the existing suffix code.\n"
        "- If no completion is appropriate, output nothing."
    )

    user_content = (
        f"File: {req.path or 'snippet'}\n"
        f"Language: {req.language}\n\n"
        f"--- CODE PREFIX (BEFORE CURSOR) ---\n"
        f"{prefix}\n"
        f"--- CODE SUFFIX (AFTER CURSOR) ---\n"
        f"{suffix}\n\n"
        f"--- INSERTION CODE AT CURSOR ---"
    )

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_content),
    ]

    # 4. Execute single-attempt completion with hard timeout
    raw_completion_chunks: list[str] = []

    async def _collect():
        async for chunk in provider.stream_chat(
            model=model_name,
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        ):
            raw_completion_chunks.append(chunk)

    try:
        await asyncio.wait_for(_collect(), timeout=COMPLETION_TIMEOUT_SECONDS)
    except Exception as exc:
        # Silent failover: guardrail against UI error popups or retry storms
        logger.debug("completion: LLM call error/timeout (%s): %s", model_name, exc)
        return CompletionResponse(completion="", model=model_name, latency_ms=(time.time() - start_time) * 1000.0)

    raw_text = "".join(raw_completion_chunks)
    cleaned_completion = _clean_completion_text(raw_text, suffix)
    duration_ms = (time.time() - start_time) * 1000.0

    logger.info(
        "completion: generated %d chars (%d input tokens est) in %.1fms using %s",
        len(cleaned_completion),
        est_tokens,
        duration_ms,
        model_name,
    )

    return CompletionResponse(
        completion=cleaned_completion,
        model=model_name,
        latency_ms=round(duration_ms, 1),
        input_tokens_est=est_tokens,
    )
