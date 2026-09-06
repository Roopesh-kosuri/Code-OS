"""
test_ghost_text.py — Unit and integration tests for Ghost Text & Inline Diffs.

Tests:
1. test_register_editor_tracks_open_files
2. test_stream_inline_diff_emits_chunks
3. test_accept_ghost_text_applies_changes
4. test_reject_ghost_text_discards_changes
5. test_editor_not_open_uses_staged_changes
6. test_ghost_text_routes_api
"""

import asyncio
import json
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.features.ai.ghost_text.ghost_text_service import (
    register_editor,
    unregister_editor,
    get_active_editors,
    emit_diff_chunks,
    stage_ghost_text,
    get_pending_ghost_text,
    accept_ghost_text,
    reject_ghost_text,
    calculate_diff_chunks,
    clear_all_editors,
    _stream_queues,
)
from app.features.ai.agents.agent_tools import _handle_edit_file


@pytest.fixture(autouse=True)
def clean_registry():
    clear_all_editors()
    yield
    clear_all_editors()


def test_register_editor_tracks_open_files():
    """Verify editor registration and unregistration tracks open files correctly."""
    ws = "/test/workspace"
    file_path = "src/components/App.tsx"
    editor_id = "monaco_tab_1"

    entry = register_editor(workspace=ws, file_path=file_path, editor_id=editor_id)
    assert entry["editor_id"] == editor_id
    assert entry["file_path"] == "src/components/App.tsx"

    active = get_active_editors(workspace=ws)
    assert len(active) == 1
    assert active[0]["editor_id"] == editor_id

    # Unregister
    removed = unregister_editor(editor_id)
    assert removed is not None
    assert len(get_active_editors(workspace=ws)) == 0


@pytest.mark.asyncio
async def test_stream_inline_diff_emits_chunks():
    """Verify diff chunks are accurately computed and emitted to active queues."""
    ws = "/test/workspace"
    file_path = "main.py"
    editor_id = "monaco_editor_main"

    register_editor(workspace=ws, file_path=file_path, editor_id=editor_id)

    # Attach an async queue
    queue: asyncio.Queue = asyncio.Queue()
    _stream_queues[editor_id] = [queue]

    original = "def hello():\n    print('hello')\n"
    updated = "def hello():\n    print('hello world!')\n    return True\n"

    chunks = emit_diff_chunks(workspace=ws, file_path=file_path, original=original, updated=updated, job_id="job_42")
    assert len(chunks) > 0

    # Read events from queue
    start_ev = await queue.get()
    assert start_ev["type"] == "start"
    assert start_ev["editor_id"] == editor_id
    assert start_ev["job_id"] == "job_42"

    chunk_ev = await queue.get()
    assert chunk_ev["type"] == "chunk"
    assert "chunk" in chunk_ev
    assert chunk_ev["chunk"]["type"] in ("insert", "replace")

    # Read until done
    done_found = False
    while not queue.empty():
        ev = await queue.get()
        if ev["type"] == "done":
            done_found = True
            break
    assert done_found


def test_accept_ghost_text_applies_changes(tmp_path: Path):
    """Verify accepting ghost text writes updated content to disk and clears pending."""
    ws = str(tmp_path)
    file_path = "test_file.py"
    editor_id = "monaco_1"
    target_file = tmp_path / file_path
    target_file.write_text("initial text", encoding="utf-8")

    register_editor(workspace=ws, file_path=file_path, editor_id=editor_id)

    # Stage ghost text
    stage_ghost_text(
        editor_id=editor_id,
        file_path=file_path,
        original="initial text",
        updated="accepted new text",
        workspace=ws,
        job_id="job_accept",
    )

    pending = get_pending_ghost_text(editor_id)
    assert pending is not None
    assert pending["updated"] == "accepted new text"

    # Accept
    res = accept_ghost_text(editor_id)
    assert res.get("status") in ("accepted", "applied")
    assert target_file.read_text(encoding="utf-8") == "accepted new text"
    assert get_pending_ghost_text(editor_id) is None


def test_reject_ghost_text_discards_changes(tmp_path: Path):
    """Verify rejecting ghost text leaves disk content completely unchanged."""
    ws = str(tmp_path)
    file_path = "test_reject.py"
    editor_id = "monaco_2"
    target_file = tmp_path / file_path
    target_file.write_text("original text content", encoding="utf-8")

    register_editor(workspace=ws, file_path=file_path, editor_id=editor_id)

    # Stage ghost text
    stage_ghost_text(
        editor_id=editor_id,
        file_path=file_path,
        original="original text content",
        updated="rejected modifications",
        workspace=ws,
        job_id="job_reject",
    )

    # Reject
    res = reject_ghost_text(editor_id)
    assert res.get("status") == "rejected"
    # Verify disk content is untouched
    assert target_file.read_text(encoding="utf-8") == "original text content"
    assert get_pending_ghost_text(editor_id) is None


def test_editor_not_open_uses_staged_changes(tmp_path: Path):
    """Verify _handle_edit_file stages changes when editor is NOT open."""
    ws = str(tmp_path)
    file_path = "unopened_file.py"
    target_file = tmp_path / file_path
    target_file.write_text("existing code", encoding="utf-8")

    staged_changes: list = []
    args = {
        "path": file_path,
        "original": "existing code",
        "updated": "existing code\n# new line",
    }

    result = _handle_edit_file(workspace=ws, arguments=args, staged_changes=staged_changes)
    assert result.success is True
    assert len(staged_changes) == 1
    assert staged_changes[0].path == file_path
    assert staged_changes[0].updated == "existing code\n# new line"
    # Disk should still have original content since change is only staged
    assert target_file.read_text(encoding="utf-8") == "existing code"


@pytest.mark.asyncio
async def test_ghost_text_routes_api():
    """Verify HTTP endpoints for register, pending, unregister, accept, reject."""
    from app.core.auth import get_token
    headers = {"Authorization": f"Bearer {get_token()}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register
        reg_resp = await client.post(
            "/api/ghost-text/register",
            json={"workspace": "/test/ws", "file_path": "index.ts", "editor_id": "test_ed_api"},
            headers=headers,
        )
        assert reg_resp.status_code == 200
        assert reg_resp.json()["ok"] is True

        # 2. Query editors
        list_resp = await client.get("/api/ghost-text/editors?workspace=/test/ws", headers=headers)
        assert list_resp.status_code == 200
        editors = list_resp.json()["editors"]
        assert any(e["editor_id"] == "test_ed_api" for e in editors)

        # 3. Check pending (empty at start)
        pending_resp = await client.get("/api/ghost-text/pending?editor_id=test_ed_api&file_path=index.ts", headers=headers)
        assert pending_resp.status_code == 200
        assert pending_resp.json()["ok"] is True

        # 4. Reject endpoint (graceful when no pending)
        rej_resp = await client.post(
            "/api/ghost-text/reject",
            json={"editor_id": "test_ed_api", "file_path": "index.ts"},
            headers=headers,
        )
        assert rej_resp.status_code == 200

        # 5. Unregister
        unreg_resp = await client.post(
            "/api/ghost-text/unregister",
            json={"editor_id": "test_ed_api"},
            headers=headers,
        )
        assert unreg_resp.status_code == 200
        assert unreg_resp.json()["ok"] is True

