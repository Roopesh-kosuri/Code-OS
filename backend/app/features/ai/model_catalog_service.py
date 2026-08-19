"""
model_catalog_service.py
Fetches, caches (24-hour TTL), and validates available AI models per provider.
Prevents sending invalid model requests (e.g., 404s on Groq or OpenAI).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
import httpx

from ..settings.service import get_api_key

logger = logging.getLogger(__name__)

# 24 hours TTL in seconds
CATALOG_CACHE_TTL = 86400.0

# Curated static catalog fallbacks in case network is unreachable or on fresh boot
KNOWN_STATIC_CATALOG: dict[str, list[str]] = {
    "groq": [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile",
        "llama-3.3-70b-specdec",
        "llama-3.1-8b-instant",
        "llama-3.2-1b-preview",
        "llama-3.2-3b-preview",
        "deepseek-r1-distill-llama-70b",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        "o1",
        "o1-mini",
        "o1-preview",
        "o3-mini",
        "chatgpt-4o-latest",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash-thinking-exp",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ],
    "anthropic": [
        "claude-3-5-sonnet-latest",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "mistral": [
        "mistral-large-latest",
        "codestral-latest",
        "mistral-small-latest",
        "ministral-8b-latest",
    ],
    "nvidia-nim": [
        "meta/llama-3.3-70b-instruct",
        "meta/llama-3.1-8b-instruct",
        "minimaxai/minimax-01",
        "minimaxai/minimax-m3",
        "deepseek-ai/deepseek-r1",
        "deepseek-ai/deepseek-coder-6.7b-instruct",
        "z-ai/glm-5.2",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "mistralai/mistral-large-2-instruct",
    ],
    "ollama": [
        "llama3",
        "llama3.1",
        "llama3.2",
        "qwen2.5-coder",
        "mistral",
        "codellama",
        "deepseek-coder",
    ],
}

_DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia-nim": "https://integrate.api.nvidia.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://127.0.0.1:11434",
}


class ModelCatalogService:
    """Manages dynamic model caching (24h TTL) and model name validation."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_available_models(
        self,
        provider_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
        force_refresh: bool = False,
    ) -> list[str]:
        """Return list of valid model names for a provider, using cache or dynamic fetch."""
        prov_key = provider_id.lower()
        now = time.time()

        if not force_refresh and prov_key in self._cache:
            entry = self._cache[prov_key]
            if now - entry["timestamp"] < CATALOG_CACHE_TTL:
                return entry["models"]

        async with self._lock:
            # Double-check after acquiring lock
            if not force_refresh and prov_key in self._cache:
                entry = self._cache[prov_key]
                if now - entry["timestamp"] < CATALOG_CACHE_TTL:
                    return entry["models"]

            fetched_models = await self._fetch_live_models(prov_key, base_url, api_key)
            if fetched_models:
                self._cache[prov_key] = {"timestamp": now, "models": fetched_models}
                return fetched_models

            # Fallback to static catalog if live fetch failed
            static_models = KNOWN_STATIC_CATALOG.get(prov_key, [])
            if static_models:
                self._cache[prov_key] = {"timestamp": now, "models": static_models}
                return static_models

            return []

    async def _fetch_live_models(
        self,
        provider_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[str]:
        """Query provider GET /models endpoint."""
        url = base_url or _DEFAULT_URLS.get(provider_id)
        if not url:
            return []

        key = api_key or (await get_api_key(provider_id))
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                if provider_id == "ollama":
                    resp = await client.get(f"{url.rstrip('/')}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        return [m["name"] for m in data.get("models", [])]
                else:
                    endpoint = f"{url.rstrip('/')}/models"
                    resp = await client.get(endpoint, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        models_data = data.get("data", []) if isinstance(data, dict) else []
                        return [m["id"] for m in models_data if isinstance(m, dict) and "id" in m]
        except Exception as exc:
            logger.debug("Model catalog live fetch failed for %s: %s", provider_id, exc)

        return []

    async def validate_model_for_provider(
        self,
        provider_id: str,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> tuple[bool, str, list[str]]:
        """
        Validate whether model_name is recognized for provider_id.
        Returns: (is_valid, error_message, available_models_list)
        """
        if not model_name or model_name.lower() in ("auto", "default"):
            return True, "", []

        prov_key = provider_id.lower()
        models = await self.get_available_models(prov_key, base_url, api_key)
        if not models:
            # If no catalog available at all, allow request through
            return True, "", []

        # Check exact or case-insensitive match
        model_lower = model_name.lower().strip()
        matched = any(m.lower() == model_lower for m in models)
        if matched:
            return True, "", models

        # Check tag variant (e.g. llama3 matching llama3:latest or llama3:8b)
        tag_matched = any(
            m.lower().startswith(model_lower + ":") or model_lower.startswith(m.lower() + ":")
            for m in models
        )
        if tag_matched:
            return True, "", models

        sample_list = models[:6]
        formatted_samples = ", ".join(sample_list) + ("..." if len(models) > 6 else "")
        err_msg = (
            f"Model '{model_name}' not available on {provider_id}. "
            f"Available models: [{formatted_samples}]. Update in Settings or select from model dropdown."
        )
        return False, err_msg, models


model_catalog_service = ModelCatalogService()
