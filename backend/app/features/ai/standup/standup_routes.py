"""
standup_routes.py — REST API router for Daily Standup Generator.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.features.ai.standup.aggregator_service import gather_yesterday_activity
from app.features.ai.standup.standup_generator import generate_standup

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory history cache with fallback
STANDUP_HISTORY: List[Dict[str, Any]] = []


class GenerateStandupRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace path")
    date: Optional[str] = Field(None, description="Optional target date in YYYY-MM-DD")
    format: Optional[str] = Field("slack", description="Output format: 'slack' or 'markdown'")


@router.post("/generate")
async def generate_standup_endpoint(req: GenerateStandupRequest) -> Dict[str, Any]:
    """Aggregates yesterday's activity and synthesizes a professional standup report."""
    try:
        raw_data = await gather_yesterday_activity(req.workspace, date=req.date)
        report_text = await generate_standup(raw_data, format=req.format or "slack")

        report_entry = {
            "id": str(uuid.uuid4()),
            "workspace": req.workspace,
            "date": req.date or "yesterday",
            "format": req.format or "slack",
            "report": report_text,
            "raw_data": raw_data,
            "created_at": time.time(),
        }
        STANDUP_HISTORY.append(report_entry)

        return {
            "report": report_text,
            "raw_activity": raw_data,
            "format": req.format or "slack",
            "id": report_entry["id"],
        }
    except Exception as exc:
        logger.error("Standup generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to generate standup: {exc}")


@router.get("/history")
async def get_standup_history(workspace: str = Query(...)) -> Dict[str, Any]:
    """Returns past generated standup reports for the given workspace."""
    workspace_reports = [r for r in STANDUP_HISTORY if r.get("workspace") == workspace]
    # Return most recent first
    sorted_reports = sorted(workspace_reports, key=lambda x: x.get("created_at", 0), reverse=True)
    return {"history": sorted_reports}
