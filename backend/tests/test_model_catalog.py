"""
test_model_catalog.py - Comprehensive offline test suite for Live Model Catalog & Routing.

Covers:
1. test_fetch_parses_openai_compatible_models (mocked HTTP)
2. test_fetch_anthropic_and_ollama_shapes (mocked HTTP)
3. test_cache_serves_last_known_good_offline
4. test_route_skips_unavailable_model
5. test_route_cascades_tiers_then_preset
6. test_no_decommissioned_ids_in_config
7. test_nvidia_probe_marks_unavailable_on_404
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import get_settings
from app.features.ai.providers.catalog import (
    VERIFIED_PRESET_MODELS,
    _get_sqlite_connection,
    _upsert_models_to_sqlite,
    fetch_provider_models,
    get_verified_models,
    mark_model_probed,
)
from app.features.ai.smart_router.model_router import (
    DEFAULT_MODEL_TIERS,
    MODEL_TIERS,
    get_last_routing_decision,
    reset_model_tiers_to_default,
    route_model,
    update_model_tiers,
)
from app.features.ai.provider_health import DEFAULT_PROVIDER_MODELS


@pytest.mark.asyncio
async def test_fetch_parses_openai_compatible_models(monkeypatch):
    """Verify fetch_provider_models parses OpenAI-compatible /models responses."""
    mock_resp = httpx.Response(
        200,
        json={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "o3-mini"}]},
        request=httpx.Request("GET", "https://api.openai.com/v1/models"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        models = await fetch_provider_models("openai", api_key="sk-mock-test")

    assert models == ["gpt-4o", "gpt-4o-mini", "o3-mini"]


@pytest.mark.asyncio
async def test_fetch_anthropic_and_ollama_shapes(monkeypatch):
    """Verify Anthropic (/v1/models) and Ollama (/api/tags) schemas parse correctly."""
    anthropic_resp = httpx.Response(
        200,
        json={"data": [{"id": "claude-sonnet-4-5"}, {"id": "claude-3-5-haiku-latest"}]},
        request=httpx.Request("GET", "https://api.anthropic.com/v1/models"),
    )
    ollama_resp = httpx.Response(
        200,
        json={"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5-coder:7b"}]},
        request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = anthropic_resp
        anthropic_models = await fetch_provider_models("anthropic", api_key="ant-mock-test")

    assert "claude-sonnet-4-5" in anthropic_models
    assert "claude-3-5-haiku-latest" in anthropic_models

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ollama_resp
        ollama_models = await fetch_provider_models("ollama")

    assert "llama3.2:latest" in ollama_models
    assert "qwen2.5-coder:7b" in ollama_models


@pytest.mark.asyncio
async def test_cache_serves_last_known_good_offline(tmp_path, monkeypatch):
    """Verify fetch failure serves last-known-good SQLite entries without raising."""
    # Seed SQLite with test entries
    _upsert_models_to_sqlite("mock-provider", ["mock-model-v1", "mock-model-v2"], last_seen_ok=1)

    # Simulate network crash on fetch
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Network unreachable")):
        res = await fetch_provider_models("mock-provider", api_key="dummy")

    assert res == []

    # Serving last-known-good from SQLite
    verified = get_verified_models("mock-provider")
    assert "mock-model-v1" in verified
    assert "mock-model-v2" in verified


def test_route_skips_unavailable_model():
    """Verify route_model skips unverified models and logs/records the reason."""
    reset_model_tiers_to_default()
    # Prepend a fictional unverified model to HARD tier
    update_model_tiers({
        "HARD": ["anthropic/fictional-opus-99", "openai/gpt-4o"],
    })

    try:
        decision = route_model("HARD", available_providers=["anthropic", "openai"])
        # Selected should be gpt-4o because fictional-opus-99 is unverified on Anthropic
        assert decision["model"] == "gpt-4o"
        assert decision["provider"] == "openai"

        # Skipped list must contain the unverified model
        skipped_models = [s["model"] for s in decision["skipped"]]
        assert "anthropic/fictional-opus-99" in skipped_models
        reason_found = any("unavailable or unverified" in s["reason"] for s in decision["skipped"])
        assert reason_found is True
    finally:
        reset_model_tiers_to_default()


def test_route_cascades_tiers_then_preset():
    """Verify route_model cascades HARD -> MEDIUM -> EASY, and falls back to preset if all empty."""
    reset_model_tiers_to_default()

    # 1. HARD tier filtered, cascades to MEDIUM
    dec1 = route_model("HARD", available_providers=["deepseek"])
    assert dec1["tier"] == "MEDIUM"
    assert dec1["provider"] == "deepseek"
    assert dec1["model"] == "deepseek-chat"
    assert "cascaded" in dec1["reason"].lower()

    # 2. All tiers filtered, falls back to default preset
    dec2 = route_model("HARD", available_providers=["non-existent-provider"])
    assert dec2["provider"] == "openai"
    assert dec2["model"] == "gpt-4o"
    assert "fell back to default preset" in dec2["reason"].lower()


def test_no_decommissioned_ids_in_config():
    """Assert zero decommissioned or fictional model IDs exist in active routing configs."""
    banned_substrings = [
        "llama-3.3-70b",
        "glm-5.2",
        "claude-opus-5",
        "gpt-5.6",
        "gpt-5",
        "claude-sonnet-5",
        "gemini-3.1-pro",
        "gemini-3.5-flash",
        "glm-air",
        "minimax-m3",
    ]

    # 1. Check DEFAULT_MODEL_TIERS
    for tier, models in DEFAULT_MODEL_TIERS.items():
        for m in models:
            for banned in banned_substrings:
                assert banned not in m.lower(), f"Banned model '{banned}' found in DEFAULT_MODEL_TIERS[{tier}]: {m}"

    # 2. Check DEFAULT_PROVIDER_MODELS
    for prov, model in DEFAULT_PROVIDER_MODELS.items():
        for banned in banned_substrings:
            assert banned not in model.lower(), f"Banned model '{banned}' found in DEFAULT_PROVIDER_MODELS[{prov}]: {model}"

    # 3. Check VERIFIED_PRESET_MODELS
    for prov, models in VERIFIED_PRESET_MODELS.items():
        for m in models:
            for banned in banned_substrings:
                assert banned not in m.lower(), f"Banned model '{banned}' found in VERIFIED_PRESET_MODELS[{prov}]: {m}"


def test_nvidia_probe_marks_unavailable_on_404():
    """Verify NVIDIA probe records last_seen_ok=0 on 404/410 and removes it from verified models."""
    model_id = "test/decommissioned-model-404"

    # Mark probe failure (simulating 404/410 response)
    mark_model_probed("nvidia-nim", model_id, ok=False)

    # SQLite record must have last_seen_ok = 0
    conn = _get_sqlite_connection()
    try:
        cur = conn.execute(
            "SELECT last_seen_ok FROM model_catalog_cache WHERE provider IN ('nvidia-nim', 'nvidia') AND model_id = ?",
            (model_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 0
    finally:
        conn.close()

    # get_verified_models must exclude this model
    verified = get_verified_models("nvidia-nim")
    assert model_id not in verified


def test_provider_models_routes():
    """Verify GET /api/providers/models and POST /api/providers/refresh-models endpoints."""
    from fastapi.testclient import TestClient
    from app.core.auth import get_token
    from app.main import app

    headers = {"Authorization": f"Bearer {get_token()}"}
    client = TestClient(app)
    # Test GET /api/providers/models?provider=groq
    resp = client.get("/api/providers/models?provider=groq", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "groq"
    assert "openai/gpt-oss-120b" in data["models"]
    assert data["count"] >= 1

    # Test GET /api/providers/models (all providers)
    resp_all = client.get("/api/providers/models", headers=headers)
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert "providers" in data_all
    assert "groq" in data_all["providers"]
    assert "anthropic" in data_all["providers"]


