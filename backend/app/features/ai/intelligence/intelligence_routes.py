"""
intelligence_routes.py - FastAPI endpoints for CODE OS Intelligence layer:
Prompt quality classification, cheap model enhancement, and usage metrics.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .prompt_enhancer import (
    classify_prompt_quality,
    enhance_prompt,
    get_enhancement_stats,
    record_enhancement_action,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class PromptClassifyRequest(BaseModel):
    prompt: str = Field(..., description="User prompt to evaluate")
    active_file: Optional[str] = Field(default=None, description="Path of currently active file in editor")


class PromptClassifyResponse(BaseModel):
    quality: str = Field(..., description="'good' | 'weak' | 'vague'")
    issues: list[str] = Field(default_factory=list, description="List of quality defects detected")
    score: float = Field(..., description="Quality score from 0.0 to 1.0")


class PromptEnhanceRequest(BaseModel):
    prompt: str = Field(..., description="User prompt to enhance")
    quality: Optional[dict[str, Any]] = Field(default=None, description="Pre-computed quality object if available")
    workspace: Optional[str] = Field(default=None, description="Workspace path")
    active_file: Optional[str] = Field(default=None, description="Active file path")
    open_tabs: Optional[list[str]] = Field(default=None, description="List of open editor tabs")
    git_diff_summary: Optional[str] = Field(default=None, description="Recent git diff summary")
    rag_symbols: Optional[list[str]] = Field(default=None, description="Relevant RAG symbols")


class PromptEnhanceResponse(BaseModel):
    enhanced: str = Field(..., description="Rewritten actionable prompt")
    original: str = Field(..., description="Original user prompt")
    changes: list[str] = Field(default_factory=list, description="Summary of enhancements made")
    model_used: str = Field(..., description="Identifier of model used")
    error: Optional[str] = Field(default=None, description="Error message if enhancement failed or was unavailable")


class PromptActionRequest(BaseModel):
    action: str = Field(..., description="'accept' | 'revert' | 'dismiss'")


class EnhancementStatsResponse(BaseModel):
    enhanced_count: int
    accepted_count: int
    reverted_count: int
    tokens_saved_estimate: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/classify-prompt", response_model=PromptClassifyResponse)
async def classify_prompt_endpoint(payload: PromptClassifyRequest) -> PromptClassifyResponse:
    """Classify prompt quality using fast deterministic heuristics."""
    result = classify_prompt_quality(payload.prompt, active_file=payload.active_file)
    return PromptClassifyResponse(**result)


@router.get("/classify-prompt", response_model=PromptClassifyResponse)
async def classify_prompt_get_endpoint(prompt: str = "", active_file: Optional[str] = None) -> PromptClassifyResponse:
    """Classify prompt quality via GET query params (supports quick curl / health checks)."""
    result = classify_prompt_quality(prompt, active_file=active_file)
    return PromptClassifyResponse(**result)


@router.post("/enhance-prompt", response_model=PromptEnhanceResponse)
async def enhance_prompt_endpoint(payload: PromptEnhanceRequest) -> PromptEnhanceResponse:
    """
    Enhance a weak/vague prompt with a cheap AI model and workspace context.
    Fail-open: returns original prompt unchanged if any failure occurs.
    """
    workspace_context = {
        "active_file": payload.active_file,
        "open_tabs": payload.open_tabs,
        "git_diff_summary": payload.git_diff_summary,
        "rag_symbols": payload.rag_symbols,
        "workspace": payload.workspace,
    }
    result = await enhance_prompt(
        prompt=payload.prompt,
        quality=payload.quality,
        workspace_context=workspace_context,
    )
    return PromptEnhanceResponse(**result)


@router.post("/record-action")
@router.post("/prompt-action")
async def record_action_endpoint(payload: PromptActionRequest) -> dict[str, bool]:
    """Record user interaction with prompt enhancer (accept, revert, dismiss) or escalation decision."""
    record_enhancement_action(payload.action)
    return {"success": True}


@router.get("/enhancement-stats", response_model=EnhancementStatsResponse)
async def get_enhancement_stats_endpoint() -> EnhancementStatsResponse:
    """Retrieve prompt enhancement usage and token savings statistics."""
    stats = get_enhancement_stats()
    return EnhancementStatsResponse(**stats)


@router.get("/escalation-stats")
async def get_escalation_stats_endpoint() -> dict[str, Any]:
    """Retrieve adaptive orchestration escalation statistics."""
    from app.features.ai.intelligence.escalation_tracker import get_escalation_stats
    return get_escalation_stats()

