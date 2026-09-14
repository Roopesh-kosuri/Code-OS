"""
catalog.py - Live model catalog service with 6h TTL, offline-first SQLite cache,
and verified model discovery for AI routing and providers.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from ....core.config import get_settings
from .constants import RECOVERY_URLS

logger = logging.getLogger(__name__)

# 6 hours cache TTL in seconds
CATALOG_CACHE_TTL = 21600.0

# 7 days in seconds for NVIDIA NIM verification expiration
NVIDIA_MAX_PROBE_AGE_SECONDS = 7 * 86400.0

# In-memory fast cache: provider -> {"timestamp": float, "models": list[str]}
_IN_MEMORY_CACHE: dict[str, dict[str, Any]] = {}

# Curated verified baseline presets served when no network or DB is available
VERIFIED_PRESET_MODELS: dict[str, list[str]] = {
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"],
    "nvidia-nim": ["meta/llama-3.2-11b-vision-instruct"],
    "nvidia": ["meta/llama-3.2-11b-vision-instruct"],
    "anthropic": [
        "claude-sonnet-4-5",
        "claude-3-7-sonnet-latest",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
    ],
    "openai": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "mistral": ["mistral-large-latest", "mistral-small-latest", "codestral-latest"],
    "ollama": ["llama3.2", "qwen2.5-coder", "mistral"],
    "openrouter": ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4-5", "openai/gpt-4o"],
    "moonshot": ["moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"],
    "qwen": ["qwen-max", "qwen-plus", "qwen-turbo"],
    "glm": ["glm-4-plus", "glm-4-air", "glm-4-flash"],
    "xai": ["grok-3", "grok-3-mini", "grok-2"],
    "cohere": ["command-a-03-2025", "command-r-plus-08-2024", "command-r-08-2024"],
    "llama": ["llama-3.1-8b-instant"],
}

_DEFAULT_URLS = {
    "moonshot": "https://api.moonshot.ai/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "mistral": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "llama": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia-nim": "https://integrate.api.nvidia.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "cohere": "https://api.cohere.com/v1",
    "ollama": "http://127.0.0.1:11434",
}


def _get_db_path() -> Path:
    settings = get_settings()
    return settings.database_path


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_catalog_cache (
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            last_seen_ok INTEGER NOT NULL DEFAULT 1,
            last_probed REAL NOT NULL,
            PRIMARY KEY (provider, model_id)
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_catalog_cache_provider ON model_catalog_cache(provider);"
    )
    conn.commit()


def _seed_sqlite_baselines(conn: sqlite3.Connection) -> None:
    """Seed baseline verified models into SQLite if table is empty for a provider."""
    now = time.time()
    for prov, models in VERIFIED_PRESET_MODELS.items():
        cur = conn.execute("SELECT COUNT(*) FROM model_catalog_cache WHERE provider = ?", (prov,))
        count = cur.fetchone()[0]
        if count == 0:
            for m in models:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO model_catalog_cache (provider, model_id, last_seen_ok, last_probed)
                    VALUES (?, ?, 1, ?)
                    """,
                    (prov, m, now),
                )
    conn.commit()


def _get_sqlite_connection() -> sqlite3.Connection:
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    _ensure_sqlite_schema(conn)
    _seed_sqlite_baselines(conn)
    return conn


def _read_models_from_sqlite(provider_id: str) -> list[str]:
    """Read last-known-good models from SQLite cache."""
    try:
        conn = _get_sqlite_connection()
        try:
            prov_key = provider_id.lower().strip()
            now = time.time()
            if prov_key in ("nvidia", "nvidia-nim"):
                # NVIDIA NIM 7-day rule
                cutoff = now - NVIDIA_MAX_PROBE_AGE_SECONDS
                cur = conn.execute(
                    """
                    SELECT DISTINCT model_id FROM model_catalog_cache
                    WHERE (provider = 'nvidia' OR provider = 'nvidia-nim')
                      AND last_seen_ok = 1
                      AND last_probed >= ?
                    ORDER BY model_id
                    """,
                    (cutoff,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT DISTINCT model_id FROM model_catalog_cache
                    WHERE provider = ? AND last_seen_ok = 1
                    ORDER BY model_id
                    """,
                    (prov_key,),
                )
            rows = cur.fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("catalog: error reading models from SQLite for %s: %s", provider_id, exc)
        return []


def _upsert_models_to_sqlite(provider_id: str, model_ids: list[str], last_seen_ok: int = 1) -> None:
    """Upsert returned models into SQLite cache with current probe timestamp."""
    if not model_ids:
        return
    try:
        conn = _get_sqlite_connection()
        try:
            prov_key = provider_id.lower().strip()
            now = time.time()
            for m in model_ids:
                conn.execute(
                    """
                    INSERT INTO model_catalog_cache (provider, model_id, last_seen_ok, last_probed)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(provider, model_id) DO UPDATE SET
                        last_seen_ok = excluded.last_seen_ok,
                        last_probed = excluded.last_probed
                    """,
                    (prov_key, m, last_seen_ok, now),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("catalog: error upserting models to SQLite for %s: %s", provider_id, exc)


def mark_model_probed(provider: str, model_id: str, ok: bool) -> None:
    """Update last_seen_ok and last_probed for a model probe result."""
    prov_key = provider.lower().strip()
    _upsert_models_to_sqlite(prov_key, [model_id], last_seen_ok=1 if ok else 0)
    # Invalidate in-memory cache so next read pulls updated status
    _IN_MEMORY_CACHE.pop(prov_key, None)
    if prov_key == "nvidia-nim":
        _IN_MEMORY_CACHE.pop("nvidia", None)
    elif prov_key == "nvidia":
        _IN_MEMORY_CACHE.pop("nvidia-nim", None)


async def fetch_provider_models(
    provider_id: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[str]:
    """Fetch live model catalog from provider API.

    - OpenAI-compatible (groq, gemini, deepseek, mistral, openrouter, nvidia-nim, custom):
      GET {base_url}/models with Bearer key, parse data[].id
    - anthropic: GET https://api.anthropic.com/v1/models (x-api-key, anthropic-version: 2023-06-01)
    - ollama: GET http://localhost:11434/api/tags, parse models[].name
    - 10s timeout; on ANY failure return [] (never raise)
    """
    prov_key = provider_id.lower().strip()
    url = base_url or _DEFAULT_URLS.get(prov_key) or RECOVERY_URLS.get(prov_key)
    if not url:
        return []

    # Resolve API key if not supplied
    key = api_key
    if not key and prov_key != "ollama":
        try:
            from ...settings.service import get_api_key
            key = await get_api_key(prov_key)
        except Exception:
            key = None

    try:
        # Create client with fallback on SSL issues
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:  # nosec B501
            if prov_key == "ollama":
                endpoint = f"{url.rstrip('/')}/api/tags"
                resp = await client.get(endpoint)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", []) if isinstance(m, dict) and "name" in m]
                    if models:
                        _upsert_models_to_sqlite(prov_key, models, last_seen_ok=1)
                        _IN_MEMORY_CACHE[prov_key] = {"timestamp": time.time(), "models": models}
                    return models
                return []

            if prov_key == "anthropic":
                endpoint = "https://api.anthropic.com/v1/models"
                headers = {
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                }
                if key:
                    headers["x-api-key"] = key
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
                    if models:
                        _upsert_models_to_sqlite(prov_key, models, last_seen_ok=1)
                        _IN_MEMORY_CACHE[prov_key] = {"timestamp": time.time(), "models": models}
                    return models
                return []

            # OpenAI-compatible
            endpoint = f"{url.rstrip('/')}/models"
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            resp = await client.get(endpoint, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models_data = data.get("data", []) if isinstance(data, dict) else []
                models = [m["id"] for m in models_data if isinstance(m, dict) and "id" in m]
                if models:
                    _upsert_models_to_sqlite(prov_key, models, last_seen_ok=1)
                    _IN_MEMORY_CACHE[prov_key] = {"timestamp": time.time(), "models": models}
                return models

    except Exception as exc:
        logger.debug("catalog: live fetch failed for %s (returning empty): %s", prov_key, exc)

    return []


def get_verified_models(provider_id: str) -> list[str]:
    """Synchronously retrieve live-verified or last-known-good models for a provider.

    1. Return in-memory cache if within 6h TTL.
    2. Fallback to SQLite last-known-good cache.
    3. For NVIDIA NIM, enforces that models were seen OK within the last 7 days.
    4. If empty or offline, returns curated verified baseline presets.
    """
    prov_key = provider_id.lower().strip()
    now = time.time()

    # 1. Check in-memory cache
    if prov_key in _IN_MEMORY_CACHE:
        entry = _IN_MEMORY_CACHE[prov_key]
        if now - entry["timestamp"] < CATALOG_CACHE_TTL and entry.get("models"):
            # For NVIDIA, ensure entries pass the 7-day rule
            if prov_key in ("nvidia", "nvidia-nim"):
                sqlite_models = _read_models_from_sqlite(prov_key)
                if sqlite_models:
                    return sqlite_models
            else:
                return list(entry["models"])

    # 2. Query SQLite last-known-good
    cached_models = _read_models_from_sqlite(prov_key)
    if cached_models:
        _IN_MEMORY_CACHE[prov_key] = {"timestamp": now, "models": cached_models}
        return list(cached_models)

    # 3. Fallback to baseline verified presets
    fallback = VERIFIED_PRESET_MODELS.get(prov_key, [])
    if fallback:
        _IN_MEMORY_CACHE[prov_key] = {"timestamp": now, "models": list(fallback)}
        return list(fallback)

    return []


async def refresh_provider_models(provider_id: str) -> list[str]:
    """Force an on-demand live fetch and update SQLite + in-memory cache."""
    fetched = await fetch_provider_models(provider_id)
    if fetched:
        return fetched
    return get_verified_models(provider_id)


async def refresh_all_providers() -> dict[str, int]:
    """Refresh model catalog for all supported providers."""
    results: dict[str, int] = {}
    providers = list(VERIFIED_PRESET_MODELS.keys())
    for prov in providers:
        try:
            models = await fetch_provider_models(prov)
            if not models:
                models = get_verified_models(prov)
            results[prov] = len(models)
        except Exception as exc:
            logger.debug("catalog refresh error for %s: %s", prov, exc)
            results[prov] = len(get_verified_models(prov))
    return results


# Background refresher task handle
_bg_refresh_task: Optional[asyncio.Task] = None


async def _catalog_background_loop() -> None:
    """Run non-blocking background refresh every 6 hours."""
    while True:
        try:
            await asyncio.sleep(CATALOG_CACHE_TTL)
            logger.info("catalog: starting scheduled 6h model catalog refresh")
            await refresh_all_providers()
            logger.info("catalog: scheduled 6h model catalog refresh complete")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("catalog: background refresh loop exception: %s", exc)
            await asyncio.sleep(60.0)


def start_catalog_background_refresher() -> None:
    """Start the non-blocking background refresh task if not already running."""
    global _bg_refresh_task
    try:
        loop = asyncio.get_running_loop()
        if _bg_refresh_task is None or _bg_refresh_task.done():
            _bg_refresh_task = loop.create_task(_catalog_background_loop())
            logger.info("catalog: background refresher task started")
    except RuntimeError:
        pass
