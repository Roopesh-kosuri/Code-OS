import pytest
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.db.database import get_db, init_db, close_db
from app.features.settings.service import set_setting
from app.features.ai.cost.cost_aggregator import (
    PRICING_TABLE,
    get_model_rates,
    compute_cost,
    record_cost_event,
    get_spend_summary,
    get_daily_breakdown,
)
from app.features.ai.cost.budget_guard import (
    check_budget,
    apply_budget_guard,
    BudgetExceeded,
    get_budget_settings,
)


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path: Path):
    db_file = tmp_path / "test_cost.db"
    await init_db(db_file)
    yield
    await close_db()


def test_pricing_table_covers_all_providers():
    """Verify central pricing table covers all specified frontier and cloud models."""
    required_keys = [
        "openai/gpt-5",
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "nvidia/llama-3.3-70b",
        "google/gemini-2.5-flash",
        "google/gemini-2.5-pro",
        "glm/glm-5.2",
    ]
    for key in required_keys:
        assert key in PRICING_TABLE, f"Missing {key} in PRICING_TABLE"
        in_rate, out_rate = PRICING_TABLE[key]
        assert in_rate > 0
        assert out_rate > 0

    # Local models return (0.0, 0.0)
    assert get_model_rates("ollama", "llama3.3") == (0.0, 0.0)


def test_compute_cost_accuracy():
    """Spot-check GPT-4o, Groq, and local model cost computations."""
    # GPT-4o: $2.50 in / $10.00 out per 1M tokens
    # 1,000 in, 1,000 out -> (1000*2.5 + 1000*10) / 1,000,000 = 0.0125
    cost_gpt4o = compute_cost("openai", "gpt-4o", 1000, 1000)
    assert cost_gpt4o == 0.0125

    # Groq llama-3.3-70b: $0.59 in / $0.79 out per 1M tokens
    # 10,000 in, 10,000 out -> (10000*0.59 + 10000*0.79) / 1,000,000 = 0.0138
    cost_groq = compute_cost("groq", "llama-3.3-70b", 10000, 10000)
    assert cost_groq == 0.0138

    # Local (Ollama) is always $0.00
    cost_local = compute_cost("ollama", "llama-3.1-8b", 50000, 50000)
    assert cost_local == 0.0


@pytest.mark.asyncio
async def test_spend_summary_aggregates_from_all_sources():
    """Verify spend summary aggregates from cost_events, team_messages, and agent_jobs."""
    db = await get_db()
    ws = "/test/workspace"
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "Test WS"))
    await db.commit()

    # 1. Source: cost_events
    await record_cost_event(
        job_id="job-1",
        provider="openai",
        model="gpt-5",
        in_tok=100000,
        out_tok=25000,
        usd=0.50,
        workspace=ws,
    )

    # 2. Source: team_messages for job-2
    now_ts = time.time()
    await db.execute(
        """
        INSERT INTO agent_jobs (id, workspace, workflow, status, token_usage)
        VALUES ('job-2', ?, 'team-coding', 'completed', 5000)
        """,
        (ws,),
    )
    await db.execute(
        """
        INSERT INTO team_messages (job_id, sender_role, message_type, content, token_usage, cost_usd, timestamp)
        VALUES ('job-2', 'coder', 'metrics', 'tokens', 5000, 0.25, ?)
        """,
        (now_ts,),
    )

    # 3. Source: agent_jobs standalone job-3
    await db.execute(
        """
        INSERT INTO agent_jobs (id, workspace, workflow, status, token_usage)
        VALUES ('job-3', ?, 'dual-coder', 'completed', 20000)
        """,
        (ws,),
    )
    await db.commit()

    summary = await get_spend_summary(workspace=ws, period="today")
    assert summary["total_usd"] >= 0.75
    assert "openai" in summary["per_provider"]
    assert len(summary["per_job"]) >= 2


@pytest.mark.asyncio
async def test_daily_breakdown_30_days():
    """Verify get_daily_breakdown produces 30 continuous daily points with aggregated costs."""
    ws = "/test/daily"
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "Daily WS"))
    await db.commit()

    now = time.time()
    # Insert an event today
    await record_cost_event("job-today", "openai", "gpt-4o", 1000, 1000, usd=0.0125, workspace=ws)
    # Insert an event 2 days ago
    two_days_ago = now - (2 * 86400)
    await db.execute(
        """
        INSERT INTO cost_events (id, workspace, job_id, provider, model, input_tokens, output_tokens, cost_usd, timestamp)
        VALUES ('ev-old', ?, 'job-old', 'groq', 'llama-3.3-70b', 5000, 5000, 0.0069, ?)
        """,
        (ws, two_days_ago),
    )
    await db.commit()

    breakdown = await get_daily_breakdown(workspace=ws, days=30)
    assert len(breakdown) == 30

    total_breakdown_usd = sum(item["usd"] for item in breakdown)
    assert total_breakdown_usd >= 0.019


@pytest.mark.asyncio
async def test_budget_guard_blocks_at_100_percent():
    """Verify hard stop is triggered when spend reaches or exceeds 100% of daily limit."""
    ws = "/test/budget-block"
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "Budget WS"))
    await db.commit()

    # Configure daily limit of $1.00 and hard stop at 100%
    await set_setting("budget.daily_limit_usd", "1.00")
    await set_setting("budget.auto_downgrade_at_percent", "90")
    await set_setting("budget.hard_stop_at_percent", "100")

    # Record spend of $1.05
    await record_cost_event("job-block", "openai", "gpt-4o", 100000, 80000, usd=1.05, workspace=ws)

    status = await check_budget(workspace=ws)
    assert status["ok"] is False
    assert status["action"] == "block"
    assert status["usage_percent"] >= 100.0

    # apply_budget_guard must raise BudgetExceeded
    with pytest.raises(BudgetExceeded) as exc_info:
        await apply_budget_guard(ws, "openai", "gpt-4o")

    err = exc_info.value
    assert err.usage_percent >= 100.0
    rec = err.to_recovery_payload()
    assert rec["error_type"] == "budget_exceeded"
    assert len(rec["suggested_actions"]) >= 2


@pytest.mark.asyncio
async def test_budget_guard_downgrades_at_90_percent():
    """Verify auto-downgrade action triggers when spend is between 90% and 100%."""
    ws = "/test/budget-downgrade"
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "Downgrade WS"))
    await db.commit()

    # Configure daily limit of $1.00, downgrade at 90%, hard stop at 100%
    await set_setting("budget.daily_limit_usd", "1.00")
    await set_setting("budget.auto_downgrade_at_percent", "90")
    await set_setting("budget.hard_stop_at_percent", "100")
    await set_setting("budget.downgrade_model", "groq/llama-3.3-70b")

    # Record spend of $0.93 (93% of limit)
    await record_cost_event("job-dg", "openai", "gpt-4o", 90000, 70000, usd=0.93, workspace=ws)

    status = await check_budget(workspace=ws)
    assert status["ok"] is True
    assert status["action"] == "downgrade"
    assert 90.0 <= status["usage_percent"] < 100.0

    # apply_budget_guard must swap model to downgrade model
    prov, model, act = await apply_budget_guard(ws, "openai", "gpt-5")
    assert act == "downgrade"
    assert prov == "groq"
    assert "llama-3.3-70b" in model


def test_local_models_are_free():
    """Verify all local / Ollama models have zero cost."""
    local_providers = ["ollama", "local", "lmstudio", "llamacpp"]
    local_models = [
        "llama3.2:3b",
        "mistral:7b",
        "deepseek-r1:14b",
        "qwen2.5-coder:7b",
        "codellama:13b",
    ]

    for p in local_providers:
        for m in local_models:
            in_rate, out_rate = get_model_rates(p, m)
            assert in_rate == 0.0
            assert out_rate == 0.0
            cost = compute_cost(p, m, 1_000_000, 1_000_000)
            assert cost == 0.0


@pytest.mark.asyncio
async def test_budget_settings_show_topbar_pill_toggle():
    """Verify show_topbar_pill setting defaults to True and respects 'false' toggle."""
    # Defaults to True
    cfg = await get_budget_settings()
    assert cfg["show_topbar_pill"] is True

    # When turned off in settings, returns False
    await set_setting("budget.show_topbar_pill", "false")
    cfg_off = await get_budget_settings()
    assert cfg_off["show_topbar_pill"] is False

    # When toggled back on, returns True
    await set_setting("budget.show_topbar_pill", "true")
    cfg_on = await get_budget_settings()
    assert cfg_on["show_topbar_pill"] is True

