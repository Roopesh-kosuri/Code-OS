#!/usr/bin/env python3
"""
probe_nvidia_models.py - NVIDIA NIM Deep-Dive Probe

Tests candidate NVIDIA NIM models against live API endpoints:
- Executes 1 minimal streaming chat completion request
- Executes 1 minimal tool-calling smoke request
- Records latency, ok/fail status, and HTTP response
- Writes results directly into SQLite model_catalog_cache (last_seen_ok, last_probed)
- Prints a formatted ASCII summary table
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import httpx

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.features.ai.providers.catalog import (
    fetch_provider_models,
    mark_model_probed,
)

BASE_URL = "https://integrate.api.nvidia.com/v1"


def get_nvidia_api_key() -> str | None:
    """Retrieve NVIDIA API key from environment or SQLite settings."""
    env_key = os.getenv("NVIDIA_API_KEY")
    if env_key:
        return env_key.strip()

    # Fallback to database
    try:
        settings = get_settings()
        db_path = settings.database_path
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.execute(
                    "SELECT encrypted_key FROM api_keys WHERE provider_id IN ('nvidia-nim', 'nvidia') AND encrypted_key IS NOT NULL"
                )
                row = cur.fetchone()
                if row and row[0]:
                    return decrypt_secret(row[0])
            finally:
                conn.close()
    except Exception as exc:
        print(f"[-] Warning: Failed to query database for API key: {exc}")

    return None


async def probe_streaming_chat(client: httpx.AsyncClient, model_id: str) -> tuple[bool, float, str]:
    """Execute minimal streaming chat completion request."""
    t0 = time.perf_counter()
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
        "stream": True,
    }
    try:
        resp = await client.post(f"{BASE_URL}/chat/completions", json=payload)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if resp.status_code == 200:
            return True, latency_ms, "OK"
        detail = resp.text[:60].replace("\n", " ")
        return False, latency_ms, f"HTTP {resp.status_code} ({detail})"
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, latency_ms, f"Err: {str(exc)[:50]}"


async def probe_tool_call(client: httpx.AsyncClient, model_id: str) -> tuple[bool, float, str]:
    """Execute minimal tool-calling smoke request."""
    t0 = time.perf_counter()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_weather",
                "description": "Get current weather for location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            },
        }
    ]
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "What is the weather in Paris? Use the lookup_weather tool."}],
        "tools": tools,
        "max_tokens": 60,
        "stream": False,
    }
    try:
        resp = await client.post(f"{BASE_URL}/chat/completions", json=payload)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if resp.status_code == 200:
            return True, latency_ms, "OK"
        detail = resp.text[:60].replace("\n", " ")
        return False, latency_ms, f"HTTP {resp.status_code} ({detail})"
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, latency_ms, f"Err: {str(exc)[:50]}"


async def run_probe(max_candidates: int = 10, custom_models: list[str] | None = None) -> list[dict]:
    api_key = get_nvidia_api_key()
    if not api_key:
        print("[!] ERROR: No NVIDIA API key found in NVIDIA_API_KEY environment variable or database.")
        print("[!] Probing cannot proceed without valid credentials.")
        return []

    print(f"[*] Found NVIDIA API key (prefix: {api_key[:8]}...)")

    candidates: list[str] = ["minimaxai/minimax-m3"]
    if custom_models:
        for cm in custom_models:
            if cm not in candidates:
                candidates.append(cm)
    else:
        print("[*] Fetching live model IDs from NVIDIA NIM /models endpoint...")
        fetched = await fetch_provider_models("nvidia-nim", api_key=api_key)
        print(f"[*] Fetched {len(fetched)} models from NVIDIA NIM.")
        # Prioritize key candidates
        preferred = [
            "meta/llama-3.2-11b-vision-instruct",
            "meta/llama-3.2-90b-vision-instruct",
            "meta/llama-3.1-8b-instruct",
            "meta/llama-3.1-70b-instruct",
            "deepseek-ai/deepseek-r1",
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ]
        for p in preferred:
            if p not in candidates:
                candidates.append(p)
        for f in fetched:
            if f not in candidates:
                candidates.append(f)
            if len(candidates) >= max_candidates:
                break

    candidates = candidates[:max_candidates]
    print(f"[*] Probing {len(candidates)} candidate models...\n")

    results: list[dict] = []
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(headers=headers, timeout=15.0, verify=False) as client:  # nosec B501
        for model in candidates:
            print(f" -> Probing {model}...", end="", flush=True)
            chat_ok, chat_lat, chat_msg = await probe_streaming_chat(client, model)
            tool_ok, tool_lat, tool_msg = await probe_tool_call(client, model)

            is_ok = chat_ok and tool_ok
            status = "VERIFIED" if is_ok else "UNAVAILABLE"
            tot_lat = (chat_lat + tool_lat) / 2.0

            # Record into SQLite cache
            mark_model_probed("nvidia-nim", model, ok=is_ok)
            mark_model_probed("nvidia", model, ok=is_ok)

            result_entry = {
                "model": model,
                "chat_ok": chat_ok,
                "chat_msg": chat_msg,
                "tool_ok": tool_ok,
                "tool_msg": tool_msg,
                "latency_ms": tot_lat,
                "status": status,
                "last_seen_ok": 1 if is_ok else 0,
            }
            results.append(result_entry)
            print(f" [{status}] (chat={chat_msg}, tool={tool_msg})")

    return results


def print_summary_table(results: list[dict]) -> None:
    """Print ASCII summary table."""
    if not results:
        print("[!] No probe results to display.")
        return

    col_model = 40
    col_chat = 16
    col_tool = 16
    col_lat = 14
    col_status = 14
    col_ok = 12

    sep = (
        f"+{'-' * (col_model + 2)}+{'-' * (col_chat + 2)}+{'-' * (col_tool + 2)}"
        f"+{'-' * (col_lat + 2)}+{'-' * (col_status + 2)}+{'-' * (col_ok + 2)}+"
    )

    header = (
        f"| {'Model ID'.ljust(col_model)} "
        f"| {'Streaming Chat'.ljust(col_chat)} "
        f"| {'Tool Call'.ljust(col_tool)} "
        f"| {'Latency'.ljust(col_lat)} "
        f"| {'Status'.ljust(col_status)} "
        f"| {'Last Seen OK'.ljust(col_ok)} |"
    )

    print("\n" + "=" * len(sep))
    print(" NVIDIA NIM MODEL CATALOG PROBE SUMMARY")
    print("=" * len(sep))
    print(sep)
    print(header)
    print(sep)

    for r in results:
        m_str = (r["model"][: col_model - 3] + "...") if len(r["model"]) > col_model else r["model"]
        c_str = "OK" if r["chat_ok"] else "FAIL"
        t_str = "OK" if r["tool_ok"] else "FAIL"
        lat_str = f"{r['latency_ms']:.1f} ms"
        status_str = r["status"]
        ok_str = str(r["last_seen_ok"])

        row = (
            f"| {m_str.ljust(col_model)} "
            f"| {c_str.ljust(col_chat)} "
            f"| {t_str.ljust(col_tool)} "
            f"| {lat_str.ljust(col_lat)} "
            f"| {status_str.ljust(col_status)} "
            f"| {ok_str.ljust(col_ok)} |"
        )
        print(row)

    print(sep + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe NVIDIA NIM models and update SQLite cache.")
    parser.add_argument("--limit", type=int, default=6, help="Maximum number of candidate models to probe")
    parser.add_argument("--models", nargs="*", help="Specific models to probe")
    args = parser.parse_args()

    results = asyncio.run(run_probe(max_candidates=args.limit, custom_models=args.models))
    print_summary_table(results)


if __name__ == "__main__":
    main()
