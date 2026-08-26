"""
constants.py - Centralized AI Provider configuration, fallback URLs, and preset mappings.

Deduplicates _RECOVERY_URLS and _PRESET_TO_PROVIDER across agent implementations.
"""
from __future__ import annotations

# Recovery fallback base URLs for supported providers
RECOVERY_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia-nim": "https://integrate.api.nvidia.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}

# Preset aliases and wire-protocol mappings
PRESET_TO_PROVIDER: dict[str, str] = {
    "local_reasoning": "ollama",
    "local_fast": "ollama",
    "api_fast": "groq",
    "api_reasoning": "openai-compatible",
    "auto": "auto",
    # Named cloud providers mapping to openai-compatible wire protocol when needed
    "groq": "openai-compatible",
    "openai": "openai-compatible",
    "gemini": "openai-compatible",
    "deepseek": "openai-compatible",
    "mistral": "openai-compatible",
    "openrouter": "openai-compatible",
    "nvidia-nim": "openai-compatible",
    "nvidia": "openai-compatible",
}

# Backward-compatible private aliases
_RECOVERY_URLS = RECOVERY_URLS
_PRESET_TO_PROVIDER = PRESET_TO_PROVIDER