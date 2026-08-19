"""
vision_service.py — Vision analysis and preview capture pipeline for Rony Agent.

Coordinates:
1. Offscreen/Window Screenshot capture via Electron Capture Service (:5178).
2. Dedicated sub-call analysis using lightweight/cost-effective Vision Language Models (VLMs)
   so the primary agent loop stays fast and cheap on text-only models (gpt-oss-120b).
"""

import json
import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)

# Default vision-capable models per provider preset
DEFAULT_VISION_MODELS: dict[str, str] = {
    "nvidia-nim": "meta/llama-3.2-11b-vision-instruct",
    "nvidia": "meta/llama-3.2-11b-vision-instruct",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.5-flash",
    "openrouter": "openai/gpt-4o-mini",
    "ollama": "llama3.2-vision",
    "groq": "meta/llama-3.2-11b-vision-instruct",
    "auto": "meta/llama-3.2-11b-vision-instruct",
}

DEFAULT_PROVIDER_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia-nim": "https://integrate.api.nvidia.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}


def resolve_default_vision_model(provider: str | None) -> str:
    """Return sensible default vision model for a given provider."""
    p = (provider or "nvidia-nim").lower().strip()
    return DEFAULT_VISION_MODELS.get(p, "meta/llama-3.2-11b-vision-instruct")


async def find_working_vision_config(
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
    preferred_base_url: str | None = None,
    preferred_api_key: str | None = None,
) -> tuple[str, str, str, str | None]:
    """Find a functional vision-capable provider configuration.
    
    If the preferred provider is Groq (which decommissioned its vision endpoints),
    or lacks a working key, automatically searches DB configured keys for:
    nvidia-nim, openai, gemini, anthropic, openrouter, or local ollama.
    
    Returns (provider, model, base_url, api_key).
    """
    from app.features.settings.service import get_api_key

    # Known providers with active VLM support
    candidate_providers = [
        "nvidia-nim",
        "openai",
        "gemini",
        "anthropic",
        "openrouter",
        "ollama",
    ]

    p_norm = (preferred_provider or "").lower().strip()

    # If preferred provider is not groq and has a key, use it
    if p_norm and p_norm != "groq" and p_norm != "auto":
        key = preferred_api_key or (await get_api_key(p_norm))
        if key or p_norm == "ollama":
            model = preferred_model or resolve_default_vision_model(p_norm)
            url = preferred_base_url or DEFAULT_PROVIDER_URLS.get(p_norm, "https://api.openai.com/v1")
            return p_norm, model, url, key

    # Otherwise scan configured candidate providers in order
    for cand in candidate_providers:
        cand_key = await get_api_key(cand)
        if cand_key or cand == "ollama":
            cand_model = resolve_default_vision_model(cand)
            cand_url = DEFAULT_PROVIDER_URLS.get(cand, "https://api.openai.com/v1")
            return cand, cand_model, cand_url, cand_key

    # Fallback to nvidia-nim or openai
    fallback_p = "nvidia-nim"
    fallback_key = await get_api_key(fallback_p)
    return fallback_p, resolve_default_vision_model(fallback_p), DEFAULT_PROVIDER_URLS[fallback_p], fallback_key


async def capture_screenshot(
    mode: str = "preview",
    target: str = "",
    workspace: str = "",
    port: int = 5178,
) -> tuple[bool, str, str]:
    """Capture a screenshot via Electron's internal capture service.

    Returns (success, image_base64_or_error, format).
    """
    capture_url = f"http://127.0.0.1:{port}/capture"
    payload = {
        "mode": mode,
        "target": target,
        "workspace": workspace,
        "width": 1280,
        "height": 900,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(capture_url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("success"):
                image_base64 = data.get("image_base64", "")
                fmt = data.get("format", "image/jpeg")
                return True, image_base64, fmt
            error_msg = data.get("error") or f"Capture service returned HTTP {resp.status_code}"
            return False, error_msg, ""
    except httpx.ConnectError:
        logger.warning("vision_service: Could not connect to Electron capture service on port %d", port)
        return False, f"Electron capture service is not running on port {port}. Please ensure CODE OS desktop app is open.", ""
    except Exception as exc:
        logger.exception("vision_service: Screenshot capture failed: %s", exc)
        return False, f"Screenshot capture failed: {exc}", ""


async def _execute_vlm_http_call(
    image_base64: str,
    format_type: str,
    question: str,
    target: str,
    mode: str,
    provider_id: str,
    vlm_model: str,
    url: str,
    api_key: str | None,
) -> tuple[bool, str]:
    """Execute standard OpenAI-compatible vision completion call."""
    if not url.endswith("/chat/completions"):
        endpoint = f"{url}/chat/completions"
    else:
        endpoint = url

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if "openrouter.ai" in url:
        headers["HTTP-Referer"] = "https://github.com/code-os/code-os"
        headers["X-Title"] = "CODE OS"

    system_prompt = (
        "You are an expert visual QA engineer and design inspector. "
        "Analyze the provided image/screenshot and answer the specific visual question accurately, concisely, and factually. "
        "Focus strictly on visual elements, layout structure, text visibility/contrast, overlapping elements, navigation, responsiveness, and styling as asked. "
        "Answer directly without generic filler."
    )

    user_text = f"Visual Inspection Target: {target or 'User Attached Image'} (Mode: {mode})\n\nSpecific Inspection Question:\n{question}"

    payload: dict[str, Any] = {
        "model": vlm_model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_text,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{format_type};base64,{image_base64}",
                        },
                    },
                ],
            },
        ],
        "max_tokens": 1024,
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code != 200:
                err_body = resp.text[:400]
                logger.warning("vision_service: VLM call failed (%s) with HTTP %d: %s", vlm_model, resp.status_code, err_body)
                return False, f"Vision model ({vlm_model}) returned HTTP {resp.status_code}: {err_body}"

            res_json = resp.json()
            choices = res_json.get("choices", [])
            if not choices:
                return False, f"Vision model ({vlm_model}) returned no choices in response."

            content = choices[0].get("message", {}).get("content", "")
            return True, content.strip()
    except Exception as exc:
        logger.exception("vision_service: VLM call error: %s", exc)
        return False, f"Vision analysis request failed: {exc}"


async def analyze_image_with_vlm(
    image_base64: str,
    format_type: str = "image/jpeg",
    question: str = "Describe the layout and any visual anomalies or broken elements.",
    target: str = "",
    mode: str = "preview",
    provider: str = "groq",
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> tuple[bool, str]:
    """Submit the captured or uploaded image to a Vision Language Model (VLM).

    Automatically discovers active configured vision keys (e.g. nvidia-nim, openai, gemini)
    and falls back if the primary provider lacks VLM capabilities.
    """
    prov, v_model, url, v_key = await find_working_vision_config(
        preferred_provider=provider,
        preferred_model=model,
        preferred_base_url=base_url,
        preferred_api_key=api_key,
    )

    success, result = await _execute_vlm_http_call(
        image_base64=image_base64,
        format_type=format_type,
        question=question,
        target=target,
        mode=mode,
        provider_id=prov,
        vlm_model=v_model,
        url=url,
        api_key=v_key,
    )

    # If first attempt failed with HTTP error, try fallback candidates
    if not success and prov != "nvidia-nim":
        from app.features.settings.service import get_api_key
        nim_key = await get_api_key("nvidia-nim")
        if nim_key:
            logger.info("vision_service: Retrying with nvidia-nim vision fallback...")
            success, result = await _execute_vlm_http_call(
                image_base64=image_base64,
                format_type=format_type,
                question=question,
                target=target,
                mode=mode,
                provider_id="nvidia-nim",
                vlm_model="meta/llama-3.2-11b-vision-instruct",
                url=DEFAULT_PROVIDER_URLS["nvidia-nim"],
                api_key=nim_key,
            )

    return success, result
