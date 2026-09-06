"""
staging_review_service.py — Service for GitHub-PR-style Smart Staging & Review.

Provides:
- In-memory staging review store per job_id
- Summary calculations with added/removed line metrics
- Monaco-compatible diff output (red/green lines, line numbers, chunks)
- File-level and chunk-level approval/rejection
- Reconstructed atomic disk write for approved files/chunks
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.paths import normalize_path

logger = logging.getLogger(__name__)

# In-memory staging store: job_id -> { "workspace": str, "files": dict[path, dict] }
_STAGED_REVIEWS: Dict[str, Dict[str, Any]] = {}


def _normalize_file_path(path: str) -> str:
    """Normalize file path to forward slashes without leading slash."""
    p = path.replace("\\", "/").strip()
    if p.startswith("/"):
        p = p[1:]
    return p


def calculate_diff_chunks(original: str, updated: str) -> tuple[List[Dict[str, Any]], int, int, str]:
    """
    Calculate diff chunks, line metrics, and determine status.
    Chunks conform to: [{ 'type': 'insert'|'delete'|'context', 'content': str, ... }]
    """
    orig_lines = original.splitlines(keepends=True)
    upd_lines = updated.splitlines(keepends=True)

    # Determine status
    if not original and updated:
        status = "added"
    elif original and not updated:
        status = "deleted"
    else:
        status = "modified"

    chunks: List[Dict[str, Any]] = []
    chunk_index = 0
    lines_added = 0
    lines_removed = 0

    matcher = difflib.SequenceMatcher(None, orig_lines, upd_lines)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            context_slice = [l.rstrip("\r\n") for l in orig_lines[i1:i2]]
            context_content = "".join(orig_lines[i1:i2])
            chunks.append({
                "index": chunk_index,
                "type": "context",
                "content": context_content,
                "original_lines": context_slice,
                "new_lines": context_slice,
                "approved": None,  # Context lines don't need approval
                "start_line": i1 + 1,
                "end_line": i2,
            })
            chunk_index += 1
        elif tag == "delete":
            del_slice = [l.rstrip("\r\n") for l in orig_lines[i1:i2]]
            del_content = "".join(orig_lines[i1:i2])
            lines_removed += (i2 - i1)
            chunks.append({
                "index": chunk_index,
                "type": "delete",
                "content": del_content,
                "original_lines": del_slice,
                "new_lines": [],
                "approved": False,
                "start_line": i1 + 1,
                "end_line": i2,
            })
            chunk_index += 1
        elif tag == "insert":
            ins_slice = [l.rstrip("\r\n") for l in upd_lines[j1:j2]]
            ins_content = "".join(upd_lines[j1:j2])
            lines_added += (j2 - j1)
            chunks.append({
                "index": chunk_index,
                "type": "insert",
                "content": ins_content,
                "original_lines": [],
                "new_lines": ins_slice,
                "approved": False,
                "start_line": i1 + 1,
                "end_line": max(i1 + 1, i2),
            })
            chunk_index += 1
        elif tag == "replace":
            # Split replace into delete followed by insert for granular chunking
            del_slice = [l.rstrip("\r\n") for l in orig_lines[i1:i2]]
            del_content = "".join(orig_lines[i1:i2])
            lines_removed += (i2 - i1)
            chunks.append({
                "index": chunk_index,
                "type": "delete",
                "content": del_content,
                "original_lines": del_slice,
                "new_lines": [],
                "approved": False,
                "start_line": i1 + 1,
                "end_line": i2,
            })
            chunk_index += 1

            ins_slice = [l.rstrip("\r\n") for l in upd_lines[j1:j2]]
            ins_content = "".join(upd_lines[j1:j2])
            lines_added += (j2 - j1)
            chunks.append({
                "index": chunk_index,
                "type": "insert",
                "content": ins_content,
                "original_lines": [],
                "new_lines": ins_slice,
                "approved": False,
                "start_line": i1 + 1,
                "end_line": max(i1 + 1, i2),
            })
            chunk_index += 1

    return chunks, lines_added, lines_removed, status


def stage_files_for_review(job_id: str, workspace: str, files: List[Any]) -> Dict[str, Any]:
    """
    Ingest files into the staging review store.
    Files can be dicts or objects with path/file_path, original, updated.
    """
    file_dict: Dict[str, Dict[str, Any]] = {}

    for f in files:
        if isinstance(f, dict):
            raw_path = f.get("path") or f.get("file_path") or ""
            original = f.get("original") or f.get("original_content") or ""
            updated = f.get("updated") or f.get("updated_content") or ""
            approved = f.get("approved", False)
        else:
            raw_path = getattr(f, "path", "") or getattr(f, "file_path", "")
            original = getattr(f, "original", "") or getattr(f, "original_content", "")
            updated = getattr(f, "updated", "") or getattr(f, "updated_content", "")
            approved = getattr(f, "approved", False)

        norm_path = _normalize_file_path(raw_path)
        chunks, lines_added, lines_removed, status = calculate_diff_chunks(original, updated)

        file_dict[norm_path] = {
            "path": norm_path,
            "original": original,
            "updated": updated,
            "status": status,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "approved": bool(approved),
            "chunks": chunks,
        }

    _STAGED_REVIEWS[job_id] = {
        "workspace": workspace,
        "files": file_dict,
    }

    return get_staged_changes_summary(job_id)


def clear_staged_changes(job_id: Optional[str] = None) -> None:
    """Clear staging review store for a job or all jobs."""
    if job_id:
        _STAGED_REVIEWS.pop(job_id, None)
    else:
        _STAGED_REVIEWS.clear()


def get_staged_changes_summary(job_id: str) -> Dict[str, Any]:
    """
    Return summary of all staged changes for the given job:
    {
      files: [{
        path, status: "added"|"modified"|"deleted",
        lines_added, lines_removed, approved,
        chunks: [{type: "insert"|"delete"|"context", content, index, approved}]
      }],
      total_files, total_lines_added, total_lines_removed,
      approved_count, rejected_count, pending_count
    }
    """
    job_data = _STAGED_REVIEWS.get(job_id)
    if not job_data:
        return {
            "job_id": job_id,
            "files": [],
            "total_files": 0,
            "total_lines_added": 0,
            "total_lines_removed": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "pending_count": 0,
        }

    files_list = []
    total_added = 0
    total_removed = 0
    approved_count = 0
    rejected_count = 0
    pending_count = 0

    for file_entry in job_data["files"].values():
        total_added += file_entry["lines_added"]
        total_removed += file_entry["lines_removed"]

        is_approved = file_entry.get("approved", False)
        # Check if rejected
        all_diff_chunks = [c for c in file_entry["chunks"] if c["type"] in ("insert", "delete")]
        is_rejected = bool(all_diff_chunks) and all(c.get("approved") is False for c in all_diff_chunks) and not is_approved

        if is_approved:
            approved_count += 1
        elif is_rejected:
            rejected_count += 1
        else:
            pending_count += 1

        files_list.append({
            "path": file_entry["path"],
            "status": file_entry["status"],
            "lines_added": file_entry["lines_added"],
            "lines_removed": file_entry["lines_removed"],
            "approved": is_approved,
            "chunks": [
                {
                    "index": c["index"],
                    "type": c["type"],
                    "content": c["content"],
                    "approved": c.get("approved"),
                    "start_line": c["start_line"],
                    "end_line": c["end_line"],
                }
                for c in file_entry["chunks"]
            ],
        })

    return {
        "job_id": job_id,
        "files": files_list,
        "total_files": len(files_list),
        "total_lines_added": total_added,
        "total_lines_removed": total_removed,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "pending_count": pending_count,
    }


def get_file_diff(job_id: str, file_path: str) -> Dict[str, Any]:
    """
    Return full diff for a file in Monaco-compatible format:
    Red lines (deletions), green lines (insertions), line numbers, and chunks.
    """
    job_data = _STAGED_REVIEWS.get(job_id)
    if not job_data:
        return {
            "error": f"Job {job_id} not found in staging store",
            "job_id": job_id,
            "file_path": file_path,
            "lines": [],
            "chunks": [],
        }

    norm_path = _normalize_file_path(file_path)
    file_entry = job_data["files"].get(norm_path)
    if not file_entry:
        return {
            "error": f"File {file_path} not found in staging for job {job_id}",
            "job_id": job_id,
            "file_path": file_path,
            "lines": [],
            "chunks": [],
        }

    original = file_entry["original"]
    updated = file_entry["updated"]
    chunks = file_entry["chunks"]

    # Generate unified diff text
    orig_lines = original.splitlines(keepends=True)
    upd_lines = updated.splitlines(keepends=True)
    unified_diff = "".join(
        difflib.unified_diff(
            orig_lines,
            upd_lines,
            fromfile=f"a/{norm_path}",
            tofile=f"b/{norm_path}",
        )
    )

    # Format line-by-line for Monaco editor decoration / diff viewer
    lines: List[Dict[str, Any]] = []
    line_no = 1
    orig_line_counter = 1
    new_line_counter = 1

    for chunk in chunks:
        chunk_type = chunk["type"]
        chunk_index = chunk["index"]

        if chunk_type == "context":
            for line_content in chunk["original_lines"]:
                lines.append({
                    "line_number": line_no,
                    "orig_line_number": orig_line_counter,
                    "new_line_number": new_line_counter,
                    "type": "context",
                    "content": line_content,
                    "chunk_index": chunk_index,
                })
                line_no += 1
                orig_line_counter += 1
                new_line_counter += 1
        elif chunk_type == "delete":
            for line_content in chunk["original_lines"]:
                lines.append({
                    "line_number": line_no,
                    "orig_line_number": orig_line_counter,
                    "new_line_number": None,
                    "type": "delete",
                    "content": line_content,
                    "chunk_index": chunk_index,
                })
                line_no += 1
                orig_line_counter += 1
        elif chunk_type == "insert":
            for line_content in chunk["new_lines"]:
                lines.append({
                    "line_number": line_no,
                    "orig_line_number": None,
                    "new_line_number": new_line_counter,
                    "type": "insert",
                    "content": line_content,
                    "chunk_index": chunk_index,
                })
                line_no += 1
                new_line_counter += 1

    return {
        "job_id": job_id,
        "file_path": norm_path,
        "path": norm_path,
        "status": file_entry["status"],
        "lines_added": file_entry["lines_added"],
        "lines_removed": file_entry["lines_removed"],
        "approved": file_entry.get("approved", False),
        "original_content": original,
        "updated_content": updated,
        "diff_text": unified_diff,
        "lines": lines,
        "chunks": chunks,
    }


def approve_files(job_id: str, file_paths: List[str]) -> Dict[str, Any]:
    """
    Mark selected files as approved in staged_changes.
    Also approves all diff chunks for each marked file.
    """
    job_data = _STAGED_REVIEWS.get(job_id)
    if not job_data:
        return {"success": False, "error": f"Job {job_id} not found", "approved_files": []}

    approved: List[str] = []
    norm_paths = {_normalize_file_path(p) for p in file_paths}

    for path, entry in job_data["files"].items():
        if path in norm_paths:
            entry["approved"] = True
            for chunk in entry["chunks"]:
                if chunk["type"] in ("insert", "delete"):
                    chunk["approved"] = True
            approved.append(path)

    return {
        "success": True,
        "job_id": job_id,
        "approved_files": approved,
        "summary": get_staged_changes_summary(job_id),
    }


def reject_files(job_id: str, file_paths: List[str]) -> Dict[str, Any]:
    """
    Discard / reject selected files from staged changes.
    Marks file as rejected and marks all chunks as rejected.
    """
    job_data = _STAGED_REVIEWS.get(job_id)
    if not job_data:
        return {"success": False, "error": f"Job {job_id} not found", "rejected_files": []}

    rejected: List[str] = []
    norm_paths = {_normalize_file_path(p) for p in file_paths}

    for path, entry in job_data["files"].items():
        if path in norm_paths:
            entry["approved"] = False
            for chunk in entry["chunks"]:
                if chunk["type"] in ("insert", "delete"):
                    chunk["approved"] = False
            rejected.append(path)

    return {
        "success": True,
        "job_id": job_id,
        "rejected_files": rejected,
        "summary": get_staged_changes_summary(job_id),
    }


def approve_chunk(job_id: str, file_path: str, chunk_index: int) -> Dict[str, Any]:
    """Approve a single diff block within a file."""
    job_data = _STAGED_REVIEWS.get(job_id)
    if not job_data:
        return {"success": False, "error": f"Job {job_id} not found"}

    norm_path = _normalize_file_path(file_path)
    entry = job_data["files"].get(norm_path)
    if not entry:
        return {"success": False, "error": f"File {file_path} not found in job {job_id}"}

    target_chunk = next((c for c in entry["chunks"] if c["index"] == chunk_index), None)
    if not target_chunk:
        return {"success": False, "error": f"Chunk index {chunk_index} not found in {file_path}"}

    target_chunk["approved"] = True

    # If all diff chunks are approved, mark whole file approved
    diff_chunks = [c for c in entry["chunks"] if c["type"] in ("insert", "delete")]
    if diff_chunks and all(c.get("approved") is True for c in diff_chunks):
        entry["approved"] = True

    return {
        "success": True,
        "job_id": job_id,
        "file_path": norm_path,
        "chunk_index": chunk_index,
        "approved": True,
    }


def reject_chunk(job_id: str, file_path: str, chunk_index: int) -> Dict[str, Any]:
    """Reject a single diff block within a file."""
    job_data = _STAGED_REVIEWS.get(job_id)
    if not job_data:
        return {"success": False, "error": f"Job {job_id} not found"}

    norm_path = _normalize_file_path(file_path)
    entry = job_data["files"].get(norm_path)
    if not entry:
        return {"success": False, "error": f"File {file_path} not found in job {job_id}"}

    target_chunk = next((c for c in entry["chunks"] if c["index"] == chunk_index), None)
    if not target_chunk:
        return {"success": False, "error": f"Chunk index {chunk_index} not found in {file_path}"}

    target_chunk["approved"] = False
    # If any diff chunk is rejected, file cannot be marked fully approved
    entry["approved"] = False

    return {
        "success": True,
        "job_id": job_id,
        "file_path": norm_path,
        "chunk_index": chunk_index,
        "approved": False,
    }


def _reconstruct_file_content(file_entry: Dict[str, Any]) -> str:
    """
    Reconstruct file text using granular chunk approval states.
    If chunk is approved -> apply new lines / delete original lines.
    If chunk is rejected/unapproved -> retain original lines.
    """
    if file_entry.get("approved") is True:
        return file_entry["updated"]

    result_lines: List[str] = []
    for chunk in file_entry["chunks"]:
        ctype = chunk["type"]
        is_approved = chunk.get("approved") is True

        if ctype == "context":
            result_lines.extend(chunk["original_lines"])
        elif ctype == "delete":
            if not is_approved:
                # Rejected delete -> keep original lines
                result_lines.extend(chunk["original_lines"])
            # If approved delete -> do not add to result
        elif ctype == "insert":
            if is_approved:
                # Approved insert -> add new lines
                result_lines.extend(chunk["new_lines"])
            # If rejected insert -> do not add to result

    # Preserve newline termination if original or updated had it
    content = "\n".join(result_lines)
    if file_entry["original"].endswith("\n") or file_entry["updated"].endswith("\n"):
        content += "\n"
    return content


def apply_approved_changes(job_id: str) -> Dict[str, Any]:
    """
    Write all approved files (or files with approved chunks) to disk in workspace,
    and discard rejected ones.
    """
    job_data = _STAGED_REVIEWS.get(job_id)
    if not job_data:
        return {
            "success": False,
            "error": f"Job {job_id} not found in staging store",
            "applied_files": [],
            "rejected_files": [],
        }

    workspace = job_data["workspace"]
    workspace_path = Path(normalize_path(workspace))

    applied_files: List[str] = []
    rejected_files: List[str] = []

    for path, entry in list(job_data["files"].items()):
        is_approved = entry.get("approved", False)
        diff_chunks = [c for c in entry["chunks"] if c["type"] in ("insert", "delete")]
        has_approved_chunk = any(c.get("approved") is True for c in diff_chunks)

        if is_approved or has_approved_chunk:
            full_path = workspace_path / path
            if entry["status"] == "deleted" and is_approved:
                if full_path.exists():
                    try:
                        full_path.unlink()
                    except Exception as e:
                        logger.error("Failed to delete %s: %s", full_path, e)
            else:
                final_content = _reconstruct_file_content(entry)
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(final_content, encoding="utf-8")
                except Exception as e:
                    logger.error("Failed to write %s: %s", full_path, e)
            applied_files.append(path)
        else:
            rejected_files.append(path)

    # Remove applied files from active staging review
    for p in applied_files:
        job_data["files"].pop(p, None)

    return {
        "success": True,
        "job_id": job_id,
        "applied_files": applied_files,
        "rejected_files": rejected_files,
        "remaining_files": list(job_data["files"].keys()),
    }
