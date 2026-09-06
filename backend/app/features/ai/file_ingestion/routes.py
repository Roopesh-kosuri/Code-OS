"""routes.py — FastAPI endpoints for file upload, retrieval, and deletion.

Endpoints:
- POST /api/files/upload : Upload and ingest file (PDF, code, image, data, text)
- GET /api/files/list : List uploaded files in a workspace
- GET /api/files/{file_id} : Retrieve file content and metadata
- DELETE /api/files/{file_id} : Delete uploaded file
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from .service import (
    delete_uploaded_file,
    get_uploaded_file,
    list_uploaded_files,
    save_uploaded_file,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    workspace: str = Form(""),
) -> dict[str, Any]:
    """Upload a file, extract its contents locally, and save to workspace storage."""
    try:
        file_bytes = await file.read()
        filename = file.filename or "uploaded_file"
        mime_type = file.content_type

        record = save_uploaded_file(
            workspace=workspace,
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        return {
            "file_id": record["file_id"],
            "filename": record["filename"],
            "content_preview": record["content_preview"],
            "metadata": record["metadata"],
            "error": record.get("error"),
        }
    except Exception as exc:
        logger.error("File upload failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"File upload failed: {exc}")


@router.get("/list")
async def list_files(
    workspace: str = Query(""),
) -> list[dict[str, Any]]:
    """List all uploaded files in the workspace with metadata and previews."""
    return list_uploaded_files(workspace)


@router.get("/{file_id}")
async def get_file_by_id(
    file_id: str,
    workspace: str = Query(""),
) -> dict[str, Any]:
    """Retrieve full content and metadata for an uploaded file by ID."""
    record = get_uploaded_file(file_id, workspace)
    if not record:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")

    return {
        "file_id": record["file_id"],
        "filename": record["filename"],
        "content": record.get("content", ""),
        "content_preview": record.get("content_preview", ""),
        "metadata": record.get("metadata", {}),
        "error": record.get("error"),
    }


@router.delete("/{file_id}")
async def delete_file_by_id(
    file_id: str,
    workspace: str = Query(""),
) -> dict[str, Any]:
    """Remove uploaded file and its metadata sidecar from disk."""
    success = delete_uploaded_file(file_id, workspace)
    if not success:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found for deletion")

    return {
        "status": "ok",
        "file_id": file_id,
        "deleted": True,
    }
