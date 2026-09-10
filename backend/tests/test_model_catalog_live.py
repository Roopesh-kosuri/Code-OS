"""
test_model_catalog_live.py - Gated live tests for NVIDIA NIM and Groq API providers.

Skipped automatically if API credentials are not set in the environment or database.
"""
from __future__ import annotations

import os
import pytest

from app.features.ai.providers.catalog import fetch_provider_models, get_verified_models
from scripts.probe_nvidia_models import get_nvidia_api_key, probe_streaming_chat, probe_tool_call
import httpx

_NVIDIA_KEY = os.getenv("NVIDIA_API_KEY")
_GROQ_KEY = os.getenv("GROQ_API_KEY")


@pytest.mark.skipif(not _NVIDIA_KEY, reason="NVIDIA_API_KEY credentials not available")
@pytest.mark.asyncio
async def test_live_nvidia_models_fetch():
    """Verify live fetch against NVIDIA NIM /models endpoint."""
    models = await fetch_provider_models("nvidia-nim", api_key=_NVIDIA_KEY)
    assert isinstance(models, list)
    assert len(models) > 0
    # Verified flagship vision instruct model should be present in live catalog
    assert any("llama-3.2-11b-vision-instruct" in m for m in models)


@pytest.mark.skipif(not _NVIDIA_KEY, reason="NVIDIA_API_KEY credentials not available")
@pytest.mark.asyncio
async def test_live_nvidia_chat_and_tool_completion():
    """Verify live chat completion and tool calling on verified NVIDIA model."""
    headers = {
        "Authorization": f"Bearer {_NVIDIA_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(headers=headers, timeout=20.0, verify=False) as client:
        chat_ok, chat_lat, chat_msg = await probe_streaming_chat(client, "meta/llama-3.2-11b-vision-instruct")
        assert chat_ok is True, f"Chat probe failed: {chat_msg}"

        tool_ok, tool_lat, tool_msg = await probe_tool_call(client, "meta/llama-3.2-11b-vision-instruct")
        assert tool_ok is True, f"Tool probe failed: {tool_msg}"


@pytest.mark.skipif(not _GROQ_KEY, reason="GROQ_API_KEY credentials not available")
@pytest.mark.asyncio
async def test_live_groq_models_fetch():
    """Verify live fetch against Groq /models endpoint."""
    models = await fetch_provider_models("groq", api_key=_GROQ_KEY)
    assert isinstance(models, list)
    assert len(models) > 0
    # Groq flagship model
    assert any("gpt-oss-120b" in m for m in models)
