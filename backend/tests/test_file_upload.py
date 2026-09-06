"""test_file_upload.py — Tests for file ingestion, PDF extraction, metadata, and deletion."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import fitz  # PyMuPDF
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.auth import get_token
from app.features.ai.file_ingestion.service import (
    ingest_file,
    save_uploaded_file,
    get_uploaded_file,
    list_uploaded_files,
    delete_uploaded_file,
)


def _create_test_pdf_bytes(pages_text: list[str]) -> bytes:
    """Helper to generate an in-memory multi-page PDF."""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_token()}"}


@pytest.mark.asyncio
async def test_upload_pdf_extracts_text(tmp_path: Path):
    """1. Verify PDF upload extracts multi-page text and correct page count via PyMuPDF."""
    pages = [
        "Architecture Specification: Code-OS Distributed Multi-Agent System",
        "Page Two: Detailed DAG Orchestrator with Step-Level Durability",
    ]
    pdf_bytes = _create_test_pdf_bytes(pages)
    ws = str(tmp_path / "workspace_pdf")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/files/upload",
            data={"workspace": ws},
            files={"file": ("spec.pdf", pdf_bytes, "application/pdf")},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "spec.pdf"
        assert data["file_id"] is not None
        assert data["metadata"]["page_count"] == 2
        assert data["metadata"]["word_count"] > 10

        # Retrieve full file content
        get_res = await ac.get(f"/api/files/{data['file_id']}?workspace={ws}", headers=_auth_headers())
        assert get_res.status_code == 200
        full_data = get_res.json()
        assert "Architecture Specification" in full_data["content"]
        assert "Page Two" in full_data["content"]
        assert "--- Page 2 ---" in full_data["content"]


@pytest.mark.asyncio
async def test_upload_code_file_reads_raw_content(tmp_path: Path):
    """2. Verify code files (.py, .ts, .go, etc.) read raw content without modification."""
    code_content = (
        "def compute_fibonacci(n: int) -> int:\n"
        "    if n <= 1:\n"
        "        return n\n"
        "    return compute_fibonacci(n - 1) + compute_fibonacci(n - 2)\n"
    )
    code_bytes = code_content.encode("utf-8")
    ws = str(tmp_path / "workspace_code")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/files/upload",
            data={"workspace": ws},
            files={"file": ("fibonacci.py", code_bytes, "text/x-python")},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "fibonacci.py"

        # Check full content retrieval
        get_res = await ac.get(f"/api/files/{data['file_id']}?workspace={ws}", headers=_auth_headers())
        assert get_res.status_code == 200
        assert get_res.json()["content"] == code_content


@pytest.mark.asyncio
async def test_upload_json_parses_correctly(tmp_path: Path):
    """3. Verify data files like JSON parse and format correctly."""
    sample_dict = {
        "project": "Code-OS",
        "version": "3.1.0",
        "features": ["smart_router", "session_replay", "file_upload"],
        "enabled": True,
    }
    json_bytes = json.dumps(sample_dict).encode("utf-8")
    ws = str(tmp_path / "workspace_json")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/files/upload",
            data={"workspace": ws},
            files={"file": ("config.json", json_bytes, "application/json")},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "config.json"

        get_res = await ac.get(f"/api/files/{data['file_id']}?workspace={ws}", headers=_auth_headers())
        assert get_res.status_code == 200
        extracted_content = get_res.json()["content"]
        parsed_back = json.loads(extracted_content)
        assert parsed_back["project"] == "Code-OS"
        assert parsed_back["enabled"] is True


@pytest.mark.asyncio
async def test_upload_unsupported_format_returns_error(tmp_path: Path):
    """4. Verify unsupported binary formats return an error message."""
    binary_bytes = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    ws = str(tmp_path / "workspace_unsupported")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/files/upload",
            data={"workspace": ws},
            files={"file": ("compiled_binary.exe", binary_bytes, "application/octet-stream")},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"] is not None
        assert "Unsupported file format" in data["error"]
        assert data["content_preview"] == ""


@pytest.mark.asyncio
async def test_file_metadata_includes_word_count(tmp_path: Path):
    """5. Verify file metadata includes accurate word_count, size_bytes, and timestamps."""
    text_content = "One two three four five six seven eight nine ten"
    text_bytes = text_content.encode("utf-8")
    ws = str(tmp_path / "workspace_meta")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/files/upload",
            data={"workspace": ws},
            files={"file": ("sample.txt", text_bytes, "text/plain")},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        meta = response.json()["metadata"]
        assert meta["word_count"] == 10
        assert meta["size_bytes"] == len(text_bytes)
        assert meta["filename"] == "sample.txt"
        assert "extracted_at" in meta
        assert meta["mime_type"] == "text/plain"


@pytest.mark.asyncio
async def test_delete_file_removes_from_disk(tmp_path: Path):
    """6. Verify file deletion removes both the raw file and metadata sidecar from disk."""
    ws = str(tmp_path / "workspace_del")
    file_bytes = b"Temporary content to be deleted"

    record = save_uploaded_file(ws, file_bytes, "temp.txt", "text/plain")
    file_id = record["file_id"]

    uploads_dir = Path(ws) / ".code_os" / "uploads"
    assert (uploads_dir / f"{file_id}_meta.json").exists()
    assert (uploads_dir / f"{file_id}_temp.txt").exists()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Delete via API
        del_res = await ac.delete(f"/api/files/{file_id}?workspace={ws}", headers=_auth_headers())
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True

        # Verify disk removal
        assert not (uploads_dir / f"{file_id}_meta.json").exists()
        assert not (uploads_dir / f"{file_id}_temp.txt").exists()

        # Subsequent GET should return 404
        get_res = await ac.get(f"/api/files/{file_id}?workspace={ws}", headers=_auth_headers())
        assert get_res.status_code == 404
