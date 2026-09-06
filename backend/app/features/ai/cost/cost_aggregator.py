from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.db.database import get_db

logger = logging.getLogger(__name__)

# Central pricing table (USD per 1M tokens)
# (input_cost_per_m, output_cost_per_m)
PRICING_TABLE: dict[str, tuple[float, float]] = {
    # 1. User specified explicit pricing
    "openai/gpt-5": (2.50, 10.00),
    "openai/gpt-5-turbo": (2.50, 10.00),
    "anthropic/claude-opus-5": (3.00, 15.00),
    "anthropic/claude-sonnet-5": (3.00, 15.00),
    "openai/gpt-oss-120b": (0.59, 0.79),
    "groq/openai/gpt-oss-120b": (0.59, 0.79),
    "groq/gpt-oss-120b": (0.59, 0.79),
    "openai/gpt-oss-20b": (0.05, 0.08),
    "groq/openai/gpt-oss-20b": (0.05, 0.08),
    "groq/gpt-oss-20b": (0.05, 0.08),
    "nvidia/llama-3.3-70b": (0.59, 0.79),
    "nvidia-nim/llama-3.3-70b": (0.59, 0.79),
    "groq/llama-3.3-70b": (0.59, 0.79),
    "groq/llama-3.3-70b-versatile": (0.59, 0.79),
    "google/gemini-2.5-flash": (0.15, 0.60),
    "gemini/gemini-2.5-flash": (0.15, 0.60),
    "google/gemini-2.5-pro": (1.25, 5.00),
    "gemini/gemini-2.5-pro": (1.25, 5.00),
    "glm/glm-5.2": (2.00, 8.00),
    "glm/glm-5-2": (2.00, 8.00),

    # Common frontier / standard models
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "anthropic/claude-3-5-sonnet": (3.00, 15.00),
    "anthropic/claude-3-opus": (15.00, 75.00),
    "groq/llama-3.1-8b-instant": (0.05, 0.08),
    "deepseek/deepseek-chat": (0.14, 0.28),
    "deepseek/deepseek-reasoner": (0.55, 2.19),
    "moonshot/moonshot-v1-8k": (0.12, 0.12),
    "qwen/qwen-turbo": (0.04, 0.12),
}


def _normalize_key(provider: str, model: str) -> str:
    p = provider.strip().lower()
    m = model.strip().lower()
    if "/" in m:
        return m
    return f"{p}/{m}"


def get_model_rates(provider: str, model: str) -> tuple[float, float]:
    """Return (input_rate_per_m, output_rate_per_m) in USD."""
    prov = (provider or "").strip().lower()
    mod = (model or "").strip().lower()

    # Ollama / local models are always 100% free ($0.00)
    if prov in ("ollama", "local", "lmstudio", "llamacpp") or mod.startswith("ollama/") or mod.startswith("local/"):
        return (0.0, 0.0)

    # Check exact key
    key = _normalize_key(prov, mod)
    if key in PRICING_TABLE:
        return PRICING_TABLE[key]

    # Check direct model without provider prefix if found
    for table_key, rates in PRICING_TABLE.items():
        if table_key.endswith(f"/{mod}") or table_key == mod:
            return rates

    # Fallback to catalog if available
    try:
        from app.features.ai.catalog import PROVIDER_CATALOG
        for p_key, models in PROVIDER_CATALOG.items():
            if prov and p_key.lower() != prov:
                continue
            for m in models:
                if m.id.lower() == mod or mod.endswith(m.id.lower()):
                    return (float(m.input_cost_per_m), float(m.output_cost_per_m))
    except Exception:
        pass

    # Safe default conservative rate ($1.00 / $2.00 per 1M)
    return (1.00, 2.00)


def compute_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute total cost in USD for given tokens and model."""
    in_rate, out_rate = get_model_rates(provider, model)
    cost = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0
    return round(cost, 6)


async def record_cost_event(
    job_id: str | None,
    provider: str,
    model: str,
    in_tok: int,
    out_tok: int,
    usd: float | None = None,
    workspace: str = "",
) -> str:
    """Record a cost event row in cost_events table. Returns event ID."""
    db = await get_db()
    event_id = str(uuid.uuid4())
    cost_val = usd if (usd is not None and usd >= 0) else compute_cost(provider, model, in_tok, out_tok)
    now_ts = time.time()

    ws = workspace or ""
    if not ws and job_id:
        try:
            cursor = await db.execute("SELECT workspace FROM agent_jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            if row and row["workspace"]:
                ws = row["workspace"]
        except Exception:
            pass

    try:
        await db.execute(
            """
            INSERT INTO cost_events (id, workspace, job_id, provider, model, input_tokens, output_tokens, cost_usd, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                ws,
                job_id,
                provider,
                model,
                int(in_tok or 0),
                int(out_tok or 0),
                float(cost_val or 0.0),
                now_ts,
            ),
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to record cost event: %s", exc)

    return event_id


def _get_period_cutoff(period: str) -> float:
    now = datetime.now(timezone.utc)
    p = period.lower().strip()
    if p == "today":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day.timestamp()
    elif p == "week" or p == "7d":
        return (now - timedelta(days=7)).timestamp()
    elif p == "month" or p == "30d":
        return (now - timedelta(days=30)).timestamp()
    elif p == "all" or p == "all-time":
        return 0.0
    return (now.replace(hour=0, minute=0, second=0, microsecond=0)).timestamp()


async def get_spend_summary(workspace: str = "", period: str = "today") -> dict[str, Any]:
    """
    Get aggregated spend summary across cost_events, team_messages, and agent_jobs.
    Returns: {total_usd, per_provider: {}, per_model: {}, per_job: []}
    """
    db = await get_db()
    cutoff_ts = _get_period_cutoff(period)

    total_usd = 0.0
    per_provider: dict[str, float] = {}
    per_model: dict[str, float] = {}
    per_job_map: dict[str, dict[str, Any]] = {}

    tracked_job_ids: set[str] = set()

    # 1. Primary Ledger: cost_events
    if workspace:
        cur = await db.execute(
            """
            SELECT id, workspace, job_id, provider, model, input_tokens, output_tokens, cost_usd, timestamp
            FROM cost_events
            WHERE timestamp >= ? AND workspace = ?
            ORDER BY timestamp DESC
            """,
            (cutoff_ts, workspace),
        )
    else:
        cur = await db.execute(
            """
            SELECT id, workspace, job_id, provider, model, input_tokens, output_tokens, cost_usd, timestamp
            FROM cost_events
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            """,
            (cutoff_ts,),
        )
    event_rows = await cur.fetchall()

    for row in event_rows:
        usd = float(row["cost_usd"] or 0.0)
        prov = str(row["provider"] or "unknown").lower()
        mod = str(row["model"] or "unknown")
        jid = row["job_id"]
        tokens = int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0)

        total_usd += usd
        per_provider[prov] = round(per_provider.get(prov, 0.0) + usd, 6)
        per_model[mod] = round(per_model.get(mod, 0.0) + usd, 6)

        if jid:
            tracked_job_ids.add(jid)
            if jid not in per_job_map:
                per_job_map[jid] = {
                    "job_id": jid,
                    "workspace": row["workspace"] or "",
                    "provider": prov,
                    "model": mod,
                    "cost_usd": 0.0,
                    "token_count": 0,
                    "event_count": 0,
                    "timestamp": row["timestamp"],
                }
            per_job_map[jid]["cost_usd"] = round(per_job_map[jid]["cost_usd"] + usd, 6)
            per_job_map[jid]["token_count"] += tokens
            per_job_map[jid]["event_count"] += 1

    # 2. Secondary source: team_messages (for messages not yet in cost_events)
    try:
        if workspace:
            tm_cur = await db.execute(
                """
                SELECT tm.job_id, tm.token_usage, tm.cost_usd, tm.timestamp, tm.sender_role, aj.workspace
                FROM team_messages tm
                LEFT JOIN agent_jobs aj ON tm.job_id = aj.id
                WHERE tm.timestamp >= ? AND (aj.workspace = ? OR aj.workspace IS NULL) AND tm.cost_usd > 0
                """,
                (cutoff_ts, workspace),
            )
        else:
            tm_cur = await db.execute(
                """
                SELECT tm.job_id, tm.token_usage, tm.cost_usd, tm.timestamp, tm.sender_role, aj.workspace
                FROM team_messages tm
                LEFT JOIN agent_jobs aj ON tm.job_id = aj.id
                WHERE tm.timestamp >= ? AND tm.cost_usd > 0
                """,
                (cutoff_ts,),
            )
        tm_rows = await tm_cur.fetchall()

        for tm in tm_rows:
            jid = tm["job_id"]
            # If job not already accounted in cost_events
            if jid and jid not in tracked_job_ids:
                usd = float(tm["cost_usd"] or 0.0)
                toks = int(tm["token_usage"] or 0)
                prov = "team-agent"
                mod = tm["sender_role"] or "agent"

                total_usd += usd
                per_provider[prov] = round(per_provider.get(prov, 0.0) + usd, 6)
                per_model[mod] = round(per_model.get(mod, 0.0) + usd, 6)

                if jid not in per_job_map:
                    per_job_map[jid] = {
                        "job_id": jid,
                        "workspace": tm["workspace"] or "",
                        "provider": prov,
                        "model": mod,
                        "cost_usd": 0.0,
                        "token_count": 0,
                        "event_count": 0,
                        "timestamp": tm["timestamp"],
                    }
                per_job_map[jid]["cost_usd"] = round(per_job_map[jid]["cost_usd"] + usd, 6)
                per_job_map[jid]["token_count"] += toks
                per_job_map[jid]["event_count"] += 1
    except Exception as exc:
        logger.debug("Failed querying team_messages for spend summary: %s", exc)

    # 3. Tertiary source: agent_jobs token_usage (fallback estimation for standalone jobs)
    try:
        if workspace:
            aj_cur = await db.execute(
                """
                SELECT id, workspace, workflow, token_usage, started_at
                FROM agent_jobs
                WHERE token_usage > 0 AND workspace = ?
                """,
                (workspace,),
            )
        else:
            aj_cur = await db.execute(
                """
                SELECT id, workspace, workflow, token_usage, started_at
                FROM agent_jobs
                WHERE token_usage > 0
                """
            )
        aj_rows = await aj_cur.fetchall()

        for aj in aj_rows:
            jid = aj["id"]
            if jid and jid not in per_job_map:
                toks = int(aj["token_usage"] or 0)
                # Estimate conservative default cost
                usd = round((toks * 1.0) / 1_000_000.0, 6)
                total_usd += usd
                prov = "agent"
                mod = aj["workflow"] or "job"
                per_provider[prov] = round(per_provider.get(prov, 0.0) + usd, 6)
                per_model[mod] = round(per_model.get(mod, 0.0) + usd, 6)
                per_job_map[jid] = {
                    "job_id": jid,
                    "workspace": aj["workspace"] or "",
                    "provider": prov,
                    "model": mod,
                    "cost_usd": usd,
                    "token_count": toks,
                    "event_count": 1,
                    "timestamp": time.time(),
                }
    except Exception as exc:
        logger.debug("Failed querying agent_jobs for spend summary: %s", exc)

    jobs_list = sorted(per_job_map.values(), key=lambda x: x["timestamp"], reverse=True)

    return {
        "total_usd": round(total_usd, 4),
        "per_provider": per_provider,
        "per_model": per_model,
        "per_job": jobs_list,
    }


async def get_daily_breakdown(workspace: str = "", days: int = 30) -> list[dict[str, Any]]:
    """
    Get day-by-day spend and token breakdown for the past `days`.
    Returns: [{date: 'YYYY-MM-DD', usd: float, job_count: int, token_count: int}]
    """
    db = await get_db()
    days = max(1, min(days, 365))
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = start_date.timestamp()

    # Pre-populate continuous date buckets
    date_buckets: dict[str, dict[str, Any]] = {}
    for i in range(days):
        d_str = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        date_buckets[d_str] = {
            "date": d_str,
            "usd": 0.0,
            "job_count": 0,
            "token_count": 0,
            "_jobs": set(),
        }

    # Query cost_events
    if workspace:
        cur = await db.execute(
            """
            SELECT cost_usd, input_tokens, output_tokens, job_id, timestamp
            FROM cost_events
            WHERE timestamp >= ? AND workspace = ?
            """,
            (start_ts, workspace),
        )
    else:
        cur = await db.execute(
            """
            SELECT cost_usd, input_tokens, output_tokens, job_id, timestamp
            FROM cost_events
            WHERE timestamp >= ?
            """,
            (start_ts,),
        )
    rows = await cur.fetchall()

    for r in rows:
        ts = float(r["timestamp"] or 0.0)
        d_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if d_str in date_buckets:
            bucket = date_buckets[d_str]
            bucket["usd"] = round(bucket["usd"] + float(r["cost_usd"] or 0.0), 6)
            bucket["token_count"] += int(r["input_tokens"] or 0) + int(r["output_tokens"] or 0)
            if r["job_id"]:
                bucket["_jobs"].add(r["job_id"])

    # Query team_messages for older or untracked jobs
    try:
        if workspace:
            tm_cur = await db.execute(
                """
                SELECT tm.cost_usd, tm.token_usage, tm.job_id, tm.timestamp
                FROM team_messages tm
                LEFT JOIN agent_jobs aj ON tm.job_id = aj.id
                WHERE tm.timestamp >= ? AND (aj.workspace = ? OR aj.workspace IS NULL) AND tm.cost_usd > 0
                """,
                (start_ts, workspace),
            )
        else:
            tm_cur = await db.execute(
                """
                SELECT tm.cost_usd, tm.token_usage, tm.job_id, tm.timestamp
                FROM team_messages tm
                WHERE tm.timestamp >= ? AND tm.cost_usd > 0
                """,
                (start_ts,),
            )
        tm_rows = await tm_cur.fetchall()
        for tm in tm_rows:
            ts = float(tm["timestamp"] or 0.0)
            d_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if d_str in date_buckets:
                bucket = date_buckets[d_str]
                jid = tm["job_id"]
                if jid and jid not in bucket["_jobs"]:
                    bucket["usd"] = round(bucket["usd"] + float(tm["cost_usd"] or 0.0), 6)
                    bucket["token_count"] += int(tm["token_usage"] or 0)
                    bucket["_jobs"].add(jid)
    except Exception as exc:
        logger.debug("Failed querying team_messages for daily breakdown: %s", exc)

    # Finalize job counts and clean internal sets
    result = []
    for d_str in sorted(date_buckets.keys()):
        b = date_buckets[d_str]
        result.append({
            "date": b["date"],
            "usd": round(b["usd"], 4),
            "job_count": len(b["_jobs"]),
            "token_count": b["token_count"],
        })

    return result
