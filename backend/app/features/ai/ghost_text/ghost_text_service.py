"""
ghost_text_service.py — In-memory registry and SSE stream manager for Cursor-style inline diffs.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory stores
# editor_id -> {"editor_id": str, "file_path": str, "workspace": str, "registered_at": float}
_active_editors: Dict[str, dict] = {}

# editor_id -> {"editor_id": str, "file_path": str, "workspace": str, "original": str, "updated": str, "chunks": list, "job_id": str, "timestamp": float}
_pending_ghost_texts: Dict[str, dict] = {}

# editor_id -> list of asyncio.Queue
_stream_queues: Dict[str, List[asyncio.Queue]] = {}


def _normalize_path(path_str: str, ws: str = "") -> str:
    """Normalize file path to forward slashes with relative root."""
    if not path_str:
        return ""
    p = str(path_str).replace("\\", "/").strip()
    if ws:
        norm_w = _normalize_workspace(ws)
        if p.lower().startswith(norm_w.lower() + "/"):
            p = p[len(norm_w) + 1:]
    p = p.lstrip("./")
    return p


def _normalize_workspace(ws: str) -> str:
    if not ws:
        return ""
    try:
        return str(Path(ws).resolve()).replace("\\", "/")
    except Exception:
        return str(ws).replace("\\", "/")


def register_editor(workspace: str, file_path: str, editor_id: str) -> dict:
    """Register an open Monaco editor tab for ghost text streaming."""
    norm_ws = _normalize_workspace(workspace)
    norm_path = _normalize_path(file_path, norm_ws)
    entry = {
        "editor_id": str(editor_id),
        "file_path": norm_path,
        "workspace": norm_ws,
        "registered_at": time.time(),
    }
    _active_editors[str(editor_id)] = entry
    logger.info("Registered editor: editor_id=%s, file=%s, ws=%s", editor_id, norm_path, norm_ws)
    return entry


def unregister_editor(editor_id: str) -> dict:
    """Unregister an editor tab when closed."""
    eid = str(editor_id)
    removed = _active_editors.pop(eid, None)
    _pending_ghost_texts.pop(eid, None)

    # Signal completion to any open queues
    queues = _stream_queues.pop(eid, [])
    for q in queues:
        try:
            q.put_nowait({"type": "closed", "editor_id": eid})
        except Exception:
            pass

    logger.info("Unregistered editor: editor_id=%s (existed=%s)", eid, bool(removed))
    return {"status": "unregistered", "editor_id": eid, "found": bool(removed)}


def get_active_editors(workspace: str = "") -> List[dict]:
    """Return all active editors, optionally filtered by workspace."""
    norm_ws = _normalize_workspace(workspace)
    editors = list(_active_editors.values())
    if not norm_ws:
        return editors
    return [e for e in editors if e.get("workspace") == norm_ws or not e.get("workspace")]


def calculate_diff_chunks(original: str, updated: str) -> List[dict]:
    """Calculate structured line-by-line diff chunks between original and updated code."""
    chunks: List[dict] = []
    
    orig_lines = original.splitlines(keepends=True) if original else []
    upd_lines = updated.splitlines(keepends=True) if updated else []

    # If new file
    if not orig_lines:
        return [{
            "chunk_id": "chunk_0",
            "type": "insert",
            "start_line": 1,
            "end_line": max(1, len(upd_lines)),
            "original_lines": [],
            "new_lines": [l.rstrip("\r\n") for l in upd_lines],
            "text": updated,
        }]

    # Compute line opcodes using SequenceMatcher
    matcher = difflib.SequenceMatcher(None, orig_lines, upd_lines)
    chunk_idx = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        
        orig_slice = [l.rstrip("\r\n") for l in orig_lines[i1:i2]]
        new_slice = [l.rstrip("\r\n") for l in upd_lines[j1:j2]]

        chunk_type = "replace"
        if tag == "insert":
            chunk_type = "insert"
        elif tag == "delete":
            chunk_type = "delete"

        chunks.append({
            "chunk_id": f"chunk_{chunk_idx}",
            "type": chunk_type,
            "start_line": i1 + 1,
            "end_line": max(i1 + 1, i2),
            "original_lines": orig_slice,
            "new_lines": new_slice,
            "text": "".join(upd_lines[j1:j2]),
        })
        chunk_idx += 1

    return chunks


def stage_ghost_text(editor_id: str, file_path: str, original: str, updated: str, workspace: str, job_id: str = "") -> dict:
    """Stage a ghost text change pending acceptance or rejection."""
    chunks = calculate_diff_chunks(original, updated)
    entry = {
        "editor_id": editor_id,
        "file_path": _normalize_path(file_path),
        "workspace": workspace,
        "original": original,
        "updated": updated,
        "chunks": chunks,
        "job_id": job_id,
        "timestamp": time.time(),
    }
    _pending_ghost_texts[editor_id] = entry
    return entry


def get_pending_ghost_text(editor_id: str, file_path: str = "") -> Optional[dict]:
    """Retrieve pending ghost text for an editor or file."""
    if editor_id in _pending_ghost_texts:
        return _pending_ghost_texts[editor_id]
    
    if file_path:
        norm_p = _normalize_path(file_path)
        for entry in _pending_ghost_texts.values():
            if entry.get("file_path") == norm_p:
                return entry
    return None


def emit_diff_chunks(workspace: str, file_path: str, original: str, updated: str, job_id: str = "") -> List[dict]:
    """
    Called when an agent edits a file.
    If the file is open in one or more Monaco editors, diff chunks are emitted to their SSE streams.
    """
    norm_ws = _normalize_workspace(workspace)
    norm_p = _normalize_path(file_path, norm_ws)

    matching_editors = [
        e for e in _active_editors.values()
        if e.get("file_path") == norm_p and (not norm_ws or e.get("workspace") == norm_ws)
    ]

    if not matching_editors:
        logger.debug("No active editors open for file %s in ws %s", norm_p, norm_ws)
        return []

    chunks = calculate_diff_chunks(original, updated)

    for ed in matching_editors:
        eid = ed["editor_id"]
        # Stage pending ghost text
        stage_ghost_text(eid, norm_p, original, updated, workspace, job_id)

        # Notify active streaming queues
        queues = _stream_queues.get(eid, [])
        for q in queues:
            try:
                # 1. Start event
                q.put_nowait({
                    "type": "start",
                    "editor_id": eid,
                    "job_id": job_id,
                    "file_path": norm_p,
                    "total_chunks": len(chunks),
                })
                # 2. Emit each diff chunk
                for chk in chunks:
                    q.put_nowait({
                        "type": "chunk",
                        "editor_id": eid,
                        "job_id": job_id,
                        "file_path": norm_p,
                        "chunk": chk,
                    })
                # 3. Complete event
                q.put_nowait({
                    "type": "done",
                    "editor_id": eid,
                    "job_id": job_id,
                    "file_path": norm_p,
                    "total_chunks": len(chunks),
                })
            except Exception as exc:
                logger.warning("Error putting chunk in stream queue for %s: %s", eid, exc)

    return chunks


def accept_ghost_text(editor_id: str, file_path: str = "") -> dict:
    """Apply staged ghost text changes to disk and notify streams."""
    entry = get_pending_ghost_text(editor_id, file_path)
    if not entry:
        return {"status": "error", "error": "No pending ghost text found for this editor/file"}

    ws = entry.get("workspace", "")
    rel_path = entry.get("file_path", "")
    updated_content = entry.get("updated", "")

    # Write to disk
    if Path(rel_path).is_absolute():
        full_path = Path(rel_path)
    elif ws:
        full_path = Path(ws) / rel_path
    else:
        full_path = Path(rel_path).resolve()

    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(updated_content, encoding="utf-8")
        bytes_written = len(updated_content.encode("utf-8"))
    except OSError as exc:
        return {"status": "error", "error": f"Failed to write file to disk: {exc}"}

    # Clear pending
    _pending_ghost_texts.pop(entry["editor_id"], None)

    # Notify queues
    queues = _stream_queues.get(entry["editor_id"], [])
    for q in queues:
        try:
            q.put_nowait({
                "type": "accepted",
                "editor_id": entry["editor_id"],
                "file_path": rel_path,
                "bytes_written": bytes_written,
            })
        except Exception:
            pass

    logger.info("Accepted ghost text: %s (%d bytes)", rel_path, bytes_written)
    return {
        "status": "accepted",
        "file_path": rel_path,
        "editor_id": entry["editor_id"],
        "bytes_written": bytes_written,
    }


def reject_ghost_text(editor_id: str, file_path: str = "") -> dict:
    """Discard staged ghost text changes and notify streams."""
    entry = get_pending_ghost_text(editor_id, file_path)
    if not entry:
        return {"status": "error", "error": "No pending ghost text found for this editor/file"}

    rel_path = entry.get("file_path", "")
    eid = entry["editor_id"]
    _pending_ghost_texts.pop(eid, None)

    # Notify queues
    queues = _stream_queues.get(eid, [])
    for q in queues:
        try:
            q.put_nowait({
                "type": "rejected",
                "editor_id": eid,
                "file_path": rel_path,
            })
        except Exception:
            pass

    logger.info("Rejected ghost text: %s on editor %s", rel_path, eid)
    return {
        "status": "rejected",
        "file_path": rel_path,
        "editor_id": eid,
    }


async def stream_inline_diff(job_id: str, file_path: str, editor_id: str) -> AsyncGenerator[str, None]:
    """
    SSE generator that yields live diff chunks for an active editor session.
    Format: 'data: {...}\n\n'
    """
    norm_p = _normalize_path(file_path)
    eid = str(editor_id)

    q: asyncio.Queue = asyncio.Queue()
    if eid not in _stream_queues:
        _stream_queues[eid] = []
    _stream_queues[eid].append(q)

    # Send initial connection confirmation
    init_event = {
        "type": "connected",
        "job_id": job_id,
        "file_path": norm_p,
        "editor_id": eid,
        "timestamp": time.time(),
    }
    yield f"data: {json.dumps(init_event)}\n\n"

    # If there's already pending ghost text for this editor, send its chunks immediately
    pending = get_pending_ghost_text(eid, norm_p)
    if pending and pending.get("chunks"):
        yield f"data: {json.dumps({'type': 'start', 'editor_id': eid, 'file_path': norm_p, 'total_chunks': len(pending['chunks'])})}\n\n"
        for chk in pending["chunks"]:
            yield f"data: {json.dumps({'type': 'chunk', 'editor_id': eid, 'file_path': norm_p, 'chunk': chk})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'editor_id': eid, 'file_path': norm_p, 'total_chunks': len(pending['chunks'])})}\n\n"

    try:
        while True:
            try:
                # Wait for next event or heartbeat
                item = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type") in ("accepted", "rejected", "closed"):
                    break
            except asyncio.TimeoutError:
                # SSE Heartbeat comment to keep connection alive
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        logger.debug("SSE stream cancelled for editor_id=%s", eid)
    finally:
        if eid in _stream_queues and q in _stream_queues[eid]:
            _stream_queues[eid].remove(q)
            if not _stream_queues[eid]:
                _stream_queues.pop(eid, None)


def clear_all_editors() -> None:
    """Clear all active editors, pending texts, and queues (for tests/reset)."""
    _active_editors.clear()
    _pending_ghost_texts.clear()
    _stream_queues.clear()

