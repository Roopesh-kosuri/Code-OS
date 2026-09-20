"""repo_map.py — Aider-style Ranked Workspace Repo-Map for CODE OS v5.0.0 (Phase 12).

Provides:
- build_repo_map(workspace, focus_files=None, max_lines=400):
    Returns a bounded, ranked text outline of workspace code structures.
    Hot/focus files are emitted first with full symbol signatures (# L<line>).
    Non-focus indexed files receive a concise one-line summary.
- LRU & TTL Caching:
    Cached by (workspace_mtime_bucket, sorted_focus_files), TTL=10s.
    Invalidated via watcher events.
- Budget Shrink:
    shrink_context_for_budget(...) drops repo-map first (lowest-ranked entries),
    then RAG snippets, and diagnostics last. Never drops RAG before repo-map.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

from app.core.paths import ensure_within_workspace, normalize_workspace
from .payload_governor import get_conservative_token_count, get_token_count
from .symbol_index import (
    CODE_EXTENSIONS,
    IGNORED_SCAN_DIRS,
    SymbolEntry,
    symbols_in_file,
)

logger = logging.getLogger(__name__)

# Cache configuration
_REPO_MAP_TTL = 10.0  # seconds
_repo_map_cache: dict[tuple[Any, ...], tuple[float, str]] = {}
_cache_lock = threading.Lock()
_cache_version: int = 0


def invalidate_repo_map_cache(path: str | Path | None = None) -> None:
    """Invalidate cached repo-map entries on file change or watcher event."""
    global _cache_version
    with _cache_lock:
        _cache_version += 1
        _repo_map_cache.clear()
    if path:
        try:
            from .symbol_index import invalidate_file
            invalidate_file(path)
        except Exception:
            pass
    logger.debug("repo_map: cache invalidated (path=%s, version=%d)", path, _cache_version)


def clear_repo_map_cache() -> None:
    """Clear all repo-map cache entries."""
    invalidate_repo_map_cache(None)


def _format_signature(sym: SymbolEntry) -> str:
    """Extract and format a clean signature line from a SymbolEntry."""
    name = sym.name
    kind = sym.kind
    snippet_lines = (sym.snippet or "").splitlines()
    first_line = snippet_lines[0].strip() if snippet_lines else ""

    if kind == "class":
        sig = f"class {name}:"
        return f"{sig:<32}# L{sym.start_line}"

    # Functions and methods
    indent = "  " if kind == "method" else ""

    # Try to extract parameter signature from snippet first line
    sig_core = f"{name}(...)"
    if first_line:
        # Match python or JS/TS function signatures
        py_match = re.search(rf"\b(?:def|async\s+def)\s+{re.escape(name)}\s*\((.*?)\)", first_line)
        if py_match:
            params = py_match.group(1).strip()
            # Collapse large params
            if len(params) > 40:
                params = "..."
            sig_core = f"def {name}({params}): ..."
        else:
            js_match = re.search(rf"\b(?:function|async\s+function)?\s*{re.escape(name)}\s*\((.*?)\)", first_line)
            if js_match:
                params = js_match.group(1).strip()
                if len(params) > 40:
                    params = "..."
                sig_core = f"def {name}({params}): ..." if not first_line.startswith(("function", "const", "let", "export")) else f"{name}({params}): ..."
            else:
                sig_core = f"def {name}(...): ..." if kind == "method" or not indent else f"def {name}(...): ..."
    else:
        sig_core = f"def {name}(...): ..."

    full_sig = f"{indent}{sig_core}"
    return f"{full_sig:<32}# L{sym.start_line}"


def _summarize_symbols(symbols: list[SymbolEntry]) -> str:
    """Create a concise 1-line summary of symbols for a non-focus file."""
    if not symbols:
        return "(no exported symbols)"

    classes = [s for s in symbols if s.kind == "class"]
    fns = [s for s in symbols if s.kind in ("function", "method")]

    parts: list[str] = []
    if len(classes) == 1:
        parts.append(f"class {classes[0].name}")
    elif len(classes) > 1:
        parts.append(f"{len(classes)} classes")

    if len(fns) == 1:
        parts.append("1 fn")
    elif len(fns) > 1:
        parts.append(f"{len(fns)} fns")

    return ", ".join(parts) if parts else f"{len(symbols)} symbols"


def build_repo_map(
    workspace: str,
    focus_files: list[str] | None = None,
    max_lines: int = 400,
) -> str:
    """Build an Aider-style ranked workspace repo-map outline.

    Args:
        workspace: Absolute path to the workspace root.
        focus_files: List of hot files (RAG top-K, recent edits, prompt symbols)
                     to place first with full symbol outlines.
        max_lines: Strict upper bound on lines in output (default 400).

    Returns:
        Formatted text outline strictly <= max_lines lines.
    """
    if max_lines <= 0:
        return ""

    ws_path = normalize_workspace(workspace)
    if not ws_path.exists():
        return ""

    # 1. Check cache
    try:
        ws_mtime = int(ws_path.stat().st_mtime)
    except OSError:
        ws_mtime = 0

    norm_focus: list[str] = []
    if focus_files:
        seen = set()
        for f in focus_files:
            if not f or not isinstance(f, str):
                continue
            clean = f.strip().replace("\\", "/")
            # Filter non-code files
            ext = Path(clean).suffix.lower()
            if ext not in CODE_EXTENSIONS:
                continue
            if clean not in seen:
                seen.add(clean)
                norm_focus.append(clean)
        norm_focus = norm_focus[:15]

    cache_key = (_cache_version, ws_mtime, tuple(sorted(norm_focus)), max_lines)
    now = time.time()

    with _cache_lock:
        if cache_key in _repo_map_cache:
            ts, cached_map = _repo_map_cache[cache_key]
            if now - ts < _REPO_MAP_TTL:
                return cached_map

    # 2. Gather focus files that exist on disk
    focus_resolved: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()

    for rel_f in norm_focus:
        try:
            full_p = ensure_within_workspace(ws_path, rel_f)
            if full_p.is_file() and full_p.suffix.lower() in CODE_EXTENSIONS:
                clean_rel = str(full_p.relative_to(ws_path)).replace("\\", "/")
                if clean_rel not in seen_paths:
                    seen_paths.add(clean_rel)
                    focus_resolved.append((clean_rel, full_p))
        except (ValueError, OSError):
            continue

    # 3. Gather remaining code files across workspace
    other_files: list[tuple[str, Path]] = []
    try:
        for dirpath, dirnames, filenames in os.walk(ws_path):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_SCAN_DIRS and not d.startswith(".")]
            for fname in sorted(filenames):
                if fname.startswith("."):
                    continue
                ext = Path(fname).suffix.lower()
                if ext not in CODE_EXTENSIONS:
                    continue
                full_f = Path(dirpath) / fname
                try:
                    clean_rel = str(full_f.relative_to(ws_path)).replace("\\", "/")
                    if clean_rel not in seen_paths:
                        seen_paths.add(clean_rel)
                        other_files.append((clean_rel, full_f))
                except (ValueError, OSError):
                    continue
    except OSError as exc:
        logger.debug("repo_map: error scanning workspace files: %s", exc)

    # Sort non-focus files deterministically
    other_files.sort(key=lambda x: x[0])

    lines: list[str] = []

    # 4. Render focus files first with full detail
    for rel_path, full_path in focus_resolved:
        if len(lines) >= max_lines:
            break
        syms = symbols_in_file(full_path, workspace=str(ws_path))
        if not syms:
            continue

        file_header = f"```{rel_path}"
        candidate_lines = [file_header]
        for s in syms:
            candidate_lines.append(_format_signature(s))
        candidate_lines.append("```")

        # Check line bound
        if len(lines) + len(candidate_lines) <= max_lines:
            lines.extend(candidate_lines)
        else:
            # Add as many as fit then close block
            remaining = max_lines - len(lines)
            if remaining >= 2:
                lines.append(file_header)
                for cl in candidate_lines[1:-1]:
                    if len(lines) < max_lines - 1:
                        lines.append(cl)
                    else:
                        break
                lines.append("```")
            break

    # 5. Render remaining indexed files with one-line summaries
    for rel_path, full_path in other_files:
        if len(lines) >= max_lines:
            break
        try:
            syms = symbols_in_file(full_path, workspace=str(ws_path))
            if not syms:
                continue
            summary = _summarize_symbols(syms)
            summary_line = f"{rel_path}: {summary}"
            lines.append(summary_line)
        except Exception:
            continue

    result = "\n".join(lines[:max_lines])

    # 6. Store in cache
    with _cache_lock:
        _repo_map_cache[cache_key] = (now, result)

    return result


def shrink_context_for_budget(
    repo_map: str,
    rag_snippets: str,
    diagnostics: str,
    budget_tokens: int,
    provider: str = "",
    model: str = "",
) -> tuple[str, str, str]:
    """Shrink context elements to stay within token budget.

    Ordering rule (Phase 12 Part 3 C3):
    - Drop lowest-ranked repo-map lines first until map fits or is empty.
    - If still over budget, shrink RAG snippets.
    - If still over budget, drop diagnostics last.
    - NEVER drop RAG before the repo-map!
    """
    def _current_total(rm: str, rag: str, diag: str) -> int:
        count = 0
        if rm:
            count += get_conservative_token_count(rm)
        if rag:
            count += get_conservative_token_count(rag)
        if diag:
            count += get_conservative_token_count(diag)
        return count

    curr = _current_total(repo_map, rag_snippets, diagnostics)
    if curr <= budget_tokens:
        return repo_map, rag_snippets, diagnostics

    # Step 1: Shrink repo-map first (drop lowest-ranked lines from the end)
    rm_lines = repo_map.splitlines() if repo_map else []
    while rm_lines and _current_total("\n".join(rm_lines), rag_snippets, diagnostics) > budget_tokens:
        # Drop lines in chunks for speed
        drop_count = max(1, len(rm_lines) // 10)
        rm_lines = rm_lines[:-drop_count]

    repo_map = "\n".join(rm_lines) if rm_lines else ""
    if _current_total(repo_map, rag_snippets, diagnostics) <= budget_tokens:
        return repo_map, rag_snippets, diagnostics

    # Step 2: Shrink RAG snippets next (only after repo-map has been shrunk to zero)
    if rag_snippets:
        rag_blocks = rag_snippets.split("\n\n")
        while rag_blocks and _current_total(repo_map, "\n\n".join(rag_blocks), diagnostics) > budget_tokens:
            rag_blocks.pop()
        rag_snippets = "\n\n".join(rag_blocks) if rag_blocks else ""

    if _current_total(repo_map, rag_snippets, diagnostics) <= budget_tokens:
        return repo_map, rag_snippets, diagnostics

    # Step 3: Shrink diagnostics last
    if diagnostics:
        diag_lines = diagnostics.splitlines()
        while diag_lines and _current_total(repo_map, rag_snippets, "\n".join(diag_lines)) > budget_tokens:
            diag_lines.pop()
        diagnostics = "\n".join(diag_lines) if diag_lines else ""

    return repo_map, rag_snippets, diagnostics
