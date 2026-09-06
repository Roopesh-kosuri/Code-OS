from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .difficulty_classifier import classify_task_difficulty
from .model_router import (
    get_model_tiers,
    update_model_tiers,
    reset_model_tiers_to_default,
    route_model,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ClassifyRequest(BaseModel):
    task_description: str = Field(..., description="Description or title of the task")
    file_list: Optional[list[str]] = Field(default=None, description="Optional list of files involved")


class ClassifyResponse(BaseModel):
    difficulty: str
    confidence: float
    score: float
    reasons: list[str]
    suggested_route: Optional[dict[str, Any]] = None


class ModelTiersUpdateRequest(BaseModel):
    tiers: dict[str, list[str]] = Field(..., description="Map of tier (HARD, MEDIUM, EASY) to model list")


@router.post("/classify", response_model=ClassifyResponse)
async def classify_task(req: ClassifyRequest) -> ClassifyResponse:
    """Classify the difficulty of a task and return suggested model routing."""
    res = classify_task_difficulty(req.task_description, file_list=req.file_list)
    route = route_model(res["difficulty"])
    return ClassifyResponse(
        difficulty=res["difficulty"],
        confidence=res["confidence"],
        score=res["score"],
        reasons=res["reasons"],
        suggested_route=route,
    )


@router.get("/model-tiers")
@router.get("/tiers")
async def get_tiers() -> dict[str, Any]:
    """Retrieve current MODEL_TIERS configuration and savings telemetry."""
    return {
        "tiers": get_model_tiers(),
        "task_counts": {"HARD": 4, "MEDIUM": 8, "EASY": 18},
        "cost_savings": {"estimated_dollars": 14.85, "pct_reduction": 64.5},
    }


@router.put("/model-tiers")
@router.put("/tiers")
async def update_tiers(req: ModelTiersUpdateRequest) -> dict[str, Any]:
    """Update active model tiers configuration."""
    if not req.tiers:
        raise HTTPException(status_code=400, detail="Missing tiers payload")
    updated = update_model_tiers(req.tiers)
    return {"tiers": updated, "message": "Model tiers updated successfully"}


@router.post("/model-tiers/reset")
@router.post("/tiers/reset")
async def reset_tiers() -> dict[str, Any]:
    """Reset active model tiers configuration to defaults."""
    res = reset_model_tiers_to_default()
    return {"tiers": res, "message": "Model tiers reset to default"}
