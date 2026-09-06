"""
memory_routes.py — REST API router for AI Memory & Feedback Loop (Self-Improvement).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.features.ai.memory.memory_service import (
    boost_memory,
    decay_unused_memories,
    delete_memory,
    get_relevant_memories,
    list_memories,
    log_mistake,
    synthesize_lesson,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateMemoryRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace path")
    lesson: str = Field(..., description="Actionable lesson learned (starts with Always/Never)")
    category: Optional[str] = Field("manual", description="Category of memory")
    confidence: Optional[int] = Field(100, ge=0, le=100, description="Confidence score 0-100")


class LogMistakeRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace path")
    category: str = Field(..., description="Category: rejected_edit, failed_test, repair_loop, user_correction, security_fix, manual")
    raw_event: str = Field(..., description="Raw failure details, error traceback, or edit rejection note")
    source_event_id: Optional[str] = Field(None, description="Event or proposal ID that triggered the mistake")
    confidence: Optional[int] = Field(100, ge=0, le=100, description="Confidence score 0-100")


class BoostMemoryRequest(BaseModel):
    amount: Optional[int] = Field(10, ge=1, le=50, description="Amount to increase confidence by")


@router.get("")
async def get_memories_endpoint(
    workspace: str = Query(..., description="Root workspace path"),
    category: Optional[str] = Query(None, description="Optional category filter"),
) -> List[Dict[str, Any]]:
    """Lists stored memories for a workspace, optionally filtered by category."""
    try:
        return await list_memories(workspace=workspace, category=category)
    except Exception as exc:
        logger.error("Failed to list memories: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("")
async def create_memory_endpoint(req: CreateMemoryRequest) -> Dict[str, Any]:
    """Manually teaches the agent a new rule or lesson."""
    try:
        rule = await synthesize_lesson(req.lesson, category=req.category or "manual")
        return await log_mistake(
            workspace=req.workspace,
            category=req.category or "manual",
            raw_event_or_lesson=req.lesson,
            confidence=req.confidence or 100,
            lesson=rule,
        )
    except Exception as exc:
        logger.error("Failed to create memory: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/log-mistake")
async def log_mistake_endpoint(req: LogMistakeRequest) -> Dict[str, Any]:
    """Ingests an agent failure/mistake, synthesizes a lesson, and persists it."""
    try:
        return await log_mistake(
            workspace=req.workspace,
            category=req.category,
            raw_event_or_lesson=req.raw_event,
            source_event_id=req.source_event_id,
            confidence=req.confidence or 100,
        )
    except Exception as exc:
        logger.error("Failed to log mistake: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/relevant")
async def get_relevant_memories_endpoint(
    workspace: str = Query(..., description="Root workspace path"),
    task_description: str = Query(..., description="Task title or description"),
    top_k: int = Query(5, ge=1, le=20, description="Max memories to return"),
) -> List[Dict[str, Any]]:
    """Retrieves semantically relevant memories to guide a task."""
    try:
        return await get_relevant_memories(
            workspace=workspace,
            task_description=task_description,
            top_k=top_k,
        )
    except Exception as exc:
        logger.error("Failed to retrieve relevant memories: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{memory_id}/boost")
async def boost_memory_endpoint(
    memory_id: str,
    req: Optional[BoostMemoryRequest] = None,
) -> Dict[str, Any]:
    """Boosts confidence of a memory up to 100%."""
    amount = req.amount if req else 10
    res = await boost_memory(memory_id, amount=amount)
    if not res:
        raise HTTPException(status_code=404, detail="Memory not found")
    return res


@router.delete("/{memory_id}")
async def delete_memory_endpoint(memory_id: str) -> Dict[str, Any]:
    """Forgets (deletes) a memory permanently from SQLite and vector store."""
    deleted = await delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True, "id": memory_id}
