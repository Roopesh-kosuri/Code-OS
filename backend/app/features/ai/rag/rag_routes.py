"""
rag_routes.py — FastAPI endpoints for Semantic RAG vector indexing and codebase search.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.trust import ensure_workspace_trusted
from .vector_index_service import (
    init_vector_store,
    index_workspace,
    index_file,
    remove_file,
    semantic_search,
    get_file_context,
    get_indexing_status,
)

router = APIRouter()


# ── Request Models ────────────────────────────────────────────────────────────

class IndexWorkspaceRequest(BaseModel):
    workspace: str = Field(..., description="Absolute workspace root directory")


class IndexFileRequest(BaseModel):
    workspace: str = Field(..., description="Absolute workspace root directory")
    file_path: str = Field(..., description="File path relative to workspace or absolute")


class RemoveFileRequest(BaseModel):
    workspace: str = Field(..., description="Absolute workspace root directory")
    file_path: str = Field(..., description="File path to remove from index")


class SearchRequest(BaseModel):
    workspace: str = Field(..., description="Absolute workspace root directory")
    query: str = Field(..., description="Search query or architectural question")
    top_k: int = Field(default=5, ge=1, le=50, description="Max results to return")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/index-workspace")
async def handle_index_workspace(req: IndexWorkspaceRequest) -> Dict[str, Any]:
    """Scan and index all code files in the workspace into ChromaDB."""
    await ensure_workspace_trusted(req.workspace)
    status = await index_workspace(req.workspace)
    return {"ok": True, **status}


@router.post("/index-file")
async def handle_index_file(req: IndexFileRequest) -> Dict[str, Any]:
    """Incrementally index or re-index a single file in ChromaDB."""
    await ensure_workspace_trusted(req.workspace)
    chunks_count = await index_file(req.workspace, req.file_path)
    return {"ok": True, "chunks_indexed": chunks_count, "file_path": req.file_path}


@router.post("/remove-file")
async def handle_remove_file(req: RemoveFileRequest) -> Dict[str, Any]:
    """Remove a file from the vector index."""
    await ensure_workspace_trusted(req.workspace)
    success = await remove_file(req.workspace, req.file_path)
    return {"ok": True, "removed": success, "file_path": req.file_path}


@router.post("/search")
async def handle_search(req: SearchRequest) -> Dict[str, Any]:
    """Semantic vector search across codebase chunks using cosine similarity."""
    results = await semantic_search(req.workspace, req.query, top_k=req.top_k)
    return {"ok": True, "query": req.query, "results": results, "count": len(results)}


@router.get("/status")
@router.get("/status/{workspace:path}")
async def handle_get_status(workspace: Optional[str] = None) -> Dict[str, Any]:
    """Get vector index status (indexed file count, total chunks, last updated)."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter is required")
    status = await get_indexing_status(workspace)
    return {"ok": True, **status}


@router.get("/file-context")
async def handle_get_file_context(
    workspace: str = Query(..., description="Workspace root path"),
    file_path: str = Query(..., description="Target file path"),
) -> Dict[str, Any]:
    """Retrieve all indexed chunks for a file, sorted by line order."""
    chunks = await get_file_context(workspace, file_path)
    return {"ok": True, "file_path": file_path, "chunks": chunks, "count": len(chunks)}
