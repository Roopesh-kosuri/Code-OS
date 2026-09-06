"""
staging_review_routes.py — FastAPI routes for Smart Staging / PR View.

Endpoints:
- GET /api/staging/summary?job_id=...
- GET /api/staging/diff/{job_id}/{file_path:path}
- POST /api/staging/approve-files (body: {job_id, file_paths})
- POST /api/staging/reject-files (body: {job_id, file_paths})
- POST /api/staging/approve-chunk (body: {job_id, file_path, chunk_index})
- POST /api/staging/reject-chunk (body: {job_id, file_path, chunk_index})
- POST /api/staging/apply (body: {job_id})
- POST /api/staging/stage (body: {job_id, workspace, files}) [Convenience staging]
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .staging_review_service import (
    get_staged_changes_summary,
    get_file_diff,
    approve_files,
    reject_files,
    approve_chunk,
    reject_chunk,
    apply_approved_changes,
    stage_files_for_review,
)

router = APIRouter()


class ApproveFilesRequest(BaseModel):
    job_id: str
    file_paths: List[str] = Field(default_factory=list)


class RejectFilesRequest(BaseModel):
    job_id: str
    file_paths: List[str] = Field(default_factory=list)


class ChunkActionRequest(BaseModel):
    job_id: str
    file_path: str
    chunk_index: int


class ApplyRequest(BaseModel):
    job_id: str


class StageFilesRequest(BaseModel):
    job_id: str
    workspace: str
    files: List[Dict[str, Any]] = Field(default_factory=list)


@router.get("/summary")
async def handle_get_summary(job_id: str = Query(..., description="Agent job ID")):
    """Get overall staging summary for a job."""
    summary = get_staged_changes_summary(job_id)
    return summary


@router.get("/diff/{job_id}/{file_path:path}")
async def handle_get_diff(job_id: str, file_path: str):
    """Get Monaco-compatible diff data for a single staged file."""
    diff_data = get_file_diff(job_id, file_path)
    if "error" in diff_data and not diff_data.get("lines"):
        raise HTTPException(status_code=404, detail=diff_data["error"])
    return diff_data


@router.post("/approve-files")
async def handle_approve_files(req: ApproveFilesRequest):
    """Mark selected files as approved."""
    result = approve_files(job_id=req.job_id, file_paths=req.file_paths)
    return result


@router.post("/reject-files")
async def handle_reject_files(req: RejectFilesRequest):
    """Discard or reject selected files."""
    result = reject_files(job_id=req.job_id, file_paths=req.file_paths)
    return result


@router.post("/approve-chunk")
async def handle_approve_chunk(req: ChunkActionRequest):
    """Approve a single diff block within a file."""
    result = approve_chunk(
        job_id=req.job_id,
        file_path=req.file_path,
        chunk_index=req.chunk_index,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to approve chunk"))
    return result


@router.post("/reject-chunk")
async def handle_reject_chunk(req: ChunkActionRequest):
    """Reject a single diff block within a file."""
    result = reject_chunk(
        job_id=req.job_id,
        file_path=req.file_path,
        chunk_index=req.chunk_index,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to reject chunk"))
    return result


@router.post("/apply")
async def handle_apply(req: ApplyRequest):
    """Apply approved files/chunks to disk and discard rejected ones."""
    result = apply_approved_changes(job_id=req.job_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to apply changes"))
    return result


@router.post("/stage")
async def handle_stage(req: StageFilesRequest):
    """Stage files for PR review (helper / integration endpoint)."""
    summary = stage_files_for_review(job_id=req.job_id, workspace=req.workspace, files=req.files)
    return {"ok": True, "summary": summary}
