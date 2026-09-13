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
from app.features.ai.harness.payload_governor import get_token_count

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE_LINES = 200
DEFAULT_MAX_CONTEXT_TOKENS = 8000
DEFAULT_MAX_CONTEXT_FILES = 15

# Token budget threshold to trigger hierarchical summarization
SUMMARIZATION_TOKEN_THRESHOLD = 4000


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
    provider: str = "",
    model: str = "",
) -> tuple[str, str]:
    """Greedily assemble top-ranked chunks within 80% token budget with a context map header."""
    if not file_paths:
        return "", ""

    token_budget = int(max_tokens * 0.80)  # Reserve 20% for agent output
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
    current_tokens = 0

    for chunk in ranked:
        chunk_tokens = get_token_count(chunk["content"], provider, model)
        if chunk_tokens is None:
            logger.warning("context_assembler: exact tokenizer unavailable; omitting attachment context")
            return "", ""
        if current_tokens + chunk_tokens <= token_budget or not included_chunks:
            included_chunks.append(chunk)
            current_tokens += chunk_tokens

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


# Re-export for convenience and unified context assembly access
from app.features.ai.harness.prompt_builder import _gather_budgeted_rag_context


async def summarize_conversation(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    threshold_tokens: int = SUMMARIZATION_TOKEN_THRESHOLD,
    provider: Any | None = None,
) -> str:
    """Hierarchically summarize a long conversation into a rolling summary.

    Only triggers when the combined token count of *messages* exceeds
    *threshold_tokens*.  Lines that start with ``ANCHOR:`` are always
    preserved verbatim so memory anchors survive summarization.

    Args:
        messages: List of ``{"role": ..., "content": ...}`` dicts.
        model: Cheap model to use for summarization (default: gpt-4o-mini).
        threshold_tokens: Minimum token count to trigger summarization.
        provider: An ``AIProvider`` instance with a ``stream_agent`` method.
                  When *None* the function returns an empty string (no-op).

    Returns:
        The summary string, or an empty string when the conversation is
        short enough or no provider is supplied.
    """
    if not messages:
        return ""

    full_text = "\n".join(
        f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
        for m in messages
    )

    token_count = get_token_count(full_text, model=model)
    if token_count is None:
        logger.warning("context_assembler: exact tokenizer unavailable; skipping conversation summarization")
        return ""
    if token_count <= threshold_tokens:
        return ""

    if provider is None:
        logger.debug("context_assembler: summarize_conversation skipped — no provider supplied")
        return ""

    # Extract ANCHOR lines that must survive summarization
    anchor_lines: list[str] = [
        line for line in full_text.splitlines()
        if line.strip().upper().startswith("ANCHOR:")
    ]

    try:
        from app.features.ai.schemas import ChatMessage  # lazy import
        system_msg = (
            "You are a concise summarization assistant. "
            "Summarize the following conversation into a compact, third-person "
            "rolling summary (\u2264300 words). Focus on: decisions made, files changed, "
            "errors encountered, and outstanding tasks. "
            "Do NOT include filler or generic observations."
        )
        user_msg = f"Conversation to summarize:\n\n{full_text[:12000]}"
        messages_for_provider = [
            ChatMessage(role="system", content=system_msg),
            ChatMessage(role="user", content=user_msg),
        ]
        summary_parts: list[str] = []
        async for event in provider.stream_agent(model, messages_for_provider, temperature=0.3):
            # stream_agent yields ProviderStreamEvent objects
            if hasattr(event, "type") and event.type == "text":
                summary_parts.append(event.content)
            elif isinstance(event, str):
                summary_parts.append(event)
        summary = "".join(summary_parts).strip()
    except Exception as exc:
        logger.warning("context_assembler: summarize_conversation failed: %s", exc)
        return ""

    if anchor_lines:
        summary = summary + "\n\n" + "\n".join(anchor_lines)

    return summary



__all__ = [
    "get_token_count",
    "split_file_into_chunks",
    "rank_chunks",
    "assemble_context_with_budget",
    "_get_attachment_context_text",
    "_build_context_from_files",
    "_build_semantic_context",
    "_gather_budgeted_rag_context",
    "summarize_conversation",
]
