from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.database import get_db
from app.features.settings.service import set_setting
from .budget_guard import (
    DEFAULT_DOWNGRADE_MODEL,
    check_budget,
    get_budget_settings,
)
from .cost_aggregator import (
    get_daily_breakdown,
    get_spend_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["cost"])


class BudgetUpdateRequest(BaseModel):
    daily_limit_usd: Optional[float] = None
    session_limit_usd: Optional[float] = None
    auto_downgrade_at_percent: Optional[float] = Field(default=None, ge=1.0, le=100.0)
    hard_stop_at_percent: Optional[float] = Field(default=None, ge=1.0, le=200.0)
    downgrade_model: Optional[str] = None
    show_topbar_pill: Optional[bool] = None
    workspace: Optional[str] = None


@router.get("/summary")
async def get_summary_endpoint(
    period: str = Query(default="today", description="today|week|month|all"),
    workspace: str = Query(default="", description="Optional workspace path filter"),
) -> dict[str, Any]:
    """Get aggregated spend summary across cost_events, team_messages, and agent_jobs."""
    return await get_spend_summary(workspace=workspace, period=period)


@router.get("/breakdown")
async def get_breakdown_endpoint(
    days: int = Query(default=30, ge=1, le=365, description="Number of days for daily breakdown"),
    workspace: str = Query(default="", description="Optional workspace path filter"),
) -> list[dict[str, Any]]:
    """Get day-by-day spend and token breakdown."""
    return await get_daily_breakdown(workspace=workspace, days=days)


@router.get("/budget")
async def get_budget_endpoint(
    workspace: str = Query(default="", description="Optional workspace path"),
) -> dict[str, Any]:
    """Get current budget status, limits, and usage percentage."""
    cfg = await get_budget_settings()
    status = await check_budget(workspace)
    return {
        **cfg,
        "status": status.get("action", "none"),
        "usage_percent": status.get("usage_percent", 0.0),
        "today_spend_usd": status.get("spend", 0.0),
        "ok": status.get("ok", True),
    }


@router.put("/budget")
async def update_budget_endpoint(payload: BudgetUpdateRequest) -> dict[str, Any]:
    """Update budget limits and auto-downgrade / hard stop thresholds."""
    if payload.daily_limit_usd is not None:
        val_str = str(payload.daily_limit_usd) if payload.daily_limit_usd > 0 else ""
        await set_setting("budget.daily_limit_usd", val_str)

    if payload.session_limit_usd is not None:
        val_str = str(payload.session_limit_usd) if payload.session_limit_usd > 0 else ""
        await set_setting("budget.session_limit_usd", val_str)

    if payload.auto_downgrade_at_percent is not None:
        await set_setting("budget.auto_downgrade_at_percent", str(payload.auto_downgrade_at_percent))

    if payload.hard_stop_at_percent is not None:
        await set_setting("budget.hard_stop_at_percent", str(payload.hard_stop_at_percent))

    if payload.downgrade_model is not None:
        await set_setting("budget.downgrade_model", payload.downgrade_model.strip())

    if payload.show_topbar_pill is not None:
        await set_setting("budget.show_topbar_pill", "true" if payload.show_topbar_pill else "false")

    cfg = await get_budget_settings()
    status = await check_budget(payload.workspace or "")
    return {
        **cfg,
        "status": status.get("action", "none"),
        "usage_percent": status.get("usage_percent", 0.0),
        "today_spend_usd": status.get("spend", 0.0),
        "ok": status.get("ok", True),
    }


@router.post("/reset-today")
async def reset_today_spend_endpoint(
    workspace: str = Query(default="", description="Optional workspace path"),
) -> dict[str, Any]:
    """Admin action: Reset today's recorded cost events."""
    db = await get_db()
    now = datetime.now(timezone.utc)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    try:
        if workspace:
            await db.execute(
                "DELETE FROM cost_events WHERE timestamp >= ? AND workspace = ?",
                (start_of_today, workspace),
            )
        else:
            await db.execute(
                "DELETE FROM cost_events WHERE timestamp >= ?",
                (start_of_today,),
            )
        await db.commit()
    except Exception as exc:
        logger.error("Failed to reset today's spend: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"success": True, "message": "Today's spend reset successfully."}
