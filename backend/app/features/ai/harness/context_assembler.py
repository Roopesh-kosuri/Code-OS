from __future__ import annotations
"""
context_assembler.py - Relevance-ranked chunking and token budget management for chat agents.
"""

import logging
import re
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.search.semantic_service import semantic_search

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE_LINES = 200
DEFAULT_MAX_CONTEXT_TOKENS = 8000
DEFAULT_MAX_CONTEXT_FILES = 15


def split_file_into_chunks(file_path: str, content: str, chunk_size_lines: int = DEFAULT_CHUNK_SIZE_LINES) -> list[dict]:
    """Split a file content into ~200-line chunks, respecting logical boundaries where feasible."""
    lines = content.splitlines(keepends=True)
    if not lines:
        return []

    if len(lines) <= chunk_size_lines:
        return [{
            "path": file_path,
            "start_line": 1,
            "end_line": len(lines),
            "content": content,
            "type": "full",
        }]

    chunks: list[dict] = []
    total_lines = len(lines)
    i = 0
    while i < total_lines:
        end = min(i + chunk_size_lines, total_lines)
        
        # If not at the end of file, look for function/class break within 20 lines
        if end < total_lines:
            for probe in range(end, max(i + chunk_size_lines - 20, i), -1):
                line_str = lines[probe - 1]
                if line_str.startswith(("def ", "class ", "async def ", "function ", "export ")):
                    end = probe - 1
                    break

        chunk_lines = lines[i:end]
        chunk_text = "".join(chunk_lines)
        chunks.append({
            "path": file_path,
            "start_line": i + 1,
            "end_line": end,
            "content": chunk_text,
            "type": "relevant section" if i > 0 else "imports/header",
        })
        i = end

    return chunks


def rank_chunks(chunks: list[dict], query: str) -> list[dict]:
    """Rank chunks by relevance to the query: exact symbol matches > file name in query > keywords."""
    if not query or not chunks:
        return chunks

    q_lower = query.lower()
    q_words = set(re.findall(r"\w+", q_lower))

    scored: list[tuple[float, dict]] = []
    for chunk in chunks:
        score = 0.0
        p_name = Path(chunk["path"]).name.lower()
        
        # 1. Exact file name mentioned in query
        if p_name in q_lower:
            score += 50.0

        content_lower = chunk["content"].lower()

        # 2. Exact symbol matches (words from query defined as def/class)
        for w in q_words:
            if len(w) > 2:
                if f"def {w}" in content_lower or f"class {w}" in content_lower or f"function {w}" in content_lower:
                    score += 100.0
                elif w in content_lower:
                    score += 5.0

        # 3. Header/imports bonus
        if chunk.get("start_line", 1) == 1:
            score += 2.0

        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored]


def assemble_context_with_budget(
    file_paths: list[str],
    workspace: str,
    query: str = "",
    max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
    max_files: int = DEFAULT_MAX_CONTEXT_FILES,
) -> tuple[str, str]:
    """Greedily assemble top-ranked chunks within 80% token budget with a context map header."""
    if not file_paths:
        return "", ""

    char_budget = int(max_tokens * 4 * 0.80)  # Reserve 20% for agent output
    ws_norm = normalize_workspace(workspace) if workspace else ""

    all_chunks: list[dict] = []
    for path_str in file_paths[:max_files]:
        try:
            full_p = ensure_within_workspace(ws_norm, path_str) if ws_norm else Path(path_str)
            if full_p.is_file():
                content = full_p.read_text(encoding="utf-8", errors="replace")
                all_chunks.extend(split_file_into_chunks(path_str, content))
        except Exception as exc:
            logger.warning("context_assembler: failed to read %s: %s", path_str, exc)

    ranked = rank_chunks(all_chunks, query)

    included_chunks: list[dict] = []
    current_chars = 0

    for chunk in ranked:
        chunk_len = len(chunk["content"])
        if current_chars + chunk_len <= char_budget or not included_chunks:
            included_chunks.append(chunk)
            current_chars += chunk_len

    # Sort included chunks by path and line number for coherent reading
    included_chunks.sort(key=lambda c: (c["path"], c["start_line"]))

    # Build Context Map Header
    map_entries = [
        f"{c['path']}:{c['start_line']}-{c['end_line']} ({c['type']})"
        for c in included_chunks
    ]
    context_map = f"[Context: {', '.join(map_entries)}]"

    body_parts = [context_map, ""]
    for c in included_chunks:
        header = f"--- File: {c['path']} (Lines {c['start_line']}-{c['end_line']}) ---"
        body_parts.append(header + "\n" + c["content"])

    return "\n".join(body_parts), context_map


def _get_attachment_context_text(file_paths: list[str], workspace: str, query: str = "") -> str:
    """Build context text with relevance ranking and token budgeting."""
    context_text, _ = assemble_context_with_budget(file_paths, workspace, query=query)
    return context_text


def _build_context_from_files(file_paths: list[str], workspace: str, query: str = "") -> str:
    """Read and format multiple workspace files into a unified context block."""
    return _get_attachment_context_text(file_paths, workspace, query)


async def _build_semantic_context(query: str, workspace: str, top_k: int = 5) -> str:
    """Perform semantic search and format relevant snippets as context."""
    if not query or not workspace:
        return ""
    try:
        results = await semantic_search(query=query, workspace_path=workspace, limit=top_k)
        if not results:
            return ""
        snippets = []
        for r in results:
            path = r.get("path", "")
            snippet = r.get("snippet", r.get("content", ""))
            snippets.append(f"--- Semantic match ({path}) ---\n" + str(snippet) + "\n")
        return "\n".join(snippets)
    except Exception as exc:
        logger.warning("context_assembler: semantic search context failed: %s", exc)
        return ""
