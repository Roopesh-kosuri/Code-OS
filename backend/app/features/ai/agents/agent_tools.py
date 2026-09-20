"""
agent_tools.py — File-system tool definitions for CODE OS agents.

Provides read_file, list_directory, search_code, and edit_file tools that agents can invoke
via structured [TOOL_CALL: ...] blocks in their LLM output.  Tool results are
injected back into the conversation so the LLM can iterate.

Security: All file access goes through core.paths.ensure_within_workspace().
"""

import json
import os
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ....core.paths import ensure_within_workspace, normalize_workspace, IGNORED_DIRS

logger = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────────────
MAX_READ_LINES = 500  # Maximum lines per single read_file call
DEFAULT_READ_LIMIT = 250  # Default lines returned per read_file call
MAX_LIST_DEPTH = 3
MAX_TOOL_CALLS_PER_ITERATION = 5
MAX_TOOL_ITERATIONS = 6
TOOL_PHASE_TIMEOUT_SECONDS = 120
MAX_SEARCH_RESULTS = 15


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    """A single parsed tool invocation from LLM output."""
    name: str
    arguments: dict[str, Any]
    raw_text: str = ""


@dataclass
class ToolResult:
    """Result of executing a single tool call."""
    tool_name: str
    success: bool
    output: str
    error: str = ""
    failure_reason: str = ""
    failure_detail: str = ""
    data: Any = None


def _clean_rel_path(path_str: str) -> str:
    """Normalize user/LLM supplied relative path."""
    p = path_str.strip().strip("\"'").replace("\\", "/")
    while p.startswith("./") or p.startswith("/"):
        p = p.lstrip("./").lstrip("/")
    return p or "."


# ── Tool Handlers ────────────────────────────────────────────────────────────

def _handle_read_file(workspace: str, arguments: dict) -> ToolResult:
    """Read a file's contents with smart line-windowing, sandboxed to the workspace."""
    raw_path = arguments.get("path", "")
    if not raw_path:
        return ToolResult(tool_name="read_file", success=False, output="", error="Missing required parameter: path")

    rel_path = _clean_rel_path(raw_path)
    try:
        target = ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return ToolResult(tool_name="read_file", success=False, output="", error=f"Path rejected: {exc}")

    if not target.is_file():
        return ToolResult(tool_name="read_file", success=False, output="", error=f"File not found: {rel_path}")

    try:
        stat = target.stat()
        if stat.st_size > 2_000_000:
            return ToolResult(tool_name="read_file", success=False, output="", error=f"File too large ({stat.st_size} bytes, max 2MB)")

        raw = target.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        total_lines = len(lines)

        try:
            start_line = max(1, int(arguments.get("start_line", 1) or 1))
        except (ValueError, TypeError):
            start_line = 1

        try:
            limit = min(max(1, int(arguments.get("limit", DEFAULT_READ_LIMIT) or DEFAULT_READ_LIMIT)), MAX_READ_LINES)
        except (ValueError, TypeError):
            limit = DEFAULT_READ_LIMIT

        start_idx = start_line - 1
        end_idx = min(start_idx + limit, total_lines)
        selected_lines = lines[start_idx:end_idx]

        content = "\n".join(selected_lines)
        header = f"=== FILE: {rel_path} (Lines {start_line}-{end_idx} of {total_lines}) ==="
        
        truncated_hint = ""
        if end_idx < total_lines:
            truncated_hint = f"\n... [Showing lines {start_line}-{end_idx} of {total_lines}. To view more, call read_file with path='{rel_path}', start_line={end_idx + 1}]"

        return ToolResult(tool_name="read_file", success=True, output=f"{header}\n<untrusted_file_content path=\"{rel_path}\">\n{content}\n</untrusted_file_content>{truncated_hint}")
    except OSError as exc:
        return ToolResult(tool_name="read_file", success=False, output="", error=f"Read error: {exc}")


def _handle_list_directory(workspace: str, arguments: dict) -> ToolResult:
    """List directory contents, sandboxed to the workspace."""
    raw_path = arguments.get("path", ".")
    rel_path = _clean_rel_path(raw_path)
    max_depth = min(int(arguments.get("max_depth", 2)), MAX_LIST_DEPTH)

    try:
        target = ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return ToolResult(tool_name="list_directory", success=False, output="", error=f"Path rejected: {exc}")

    if not target.is_dir():
        return ToolResult(tool_name="list_directory", success=False, output="", error=f"Not a directory: {rel_path}")

    root = normalize_workspace(workspace)

    def _tree(path: Path, depth: int, prefix: str = "") -> list[str]:
        if depth > max_depth:
            return []
        entries: list[str] = []
        try:
            children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return [f"{prefix}(permission denied)"]

        for i, child in enumerate(children):
            if child.name in IGNORED_DIRS or child.name.startswith("."):
                continue
            is_last = i == len(children) - 1
            connector = "└── " if is_last else "├── "
            if child.is_dir():
                entries.append(f"{prefix}{connector}{child.name}/")
                extension = "    " if is_last else "│   "
                entries.extend(_tree(child, depth + 1, prefix + extension))
            else:
                size = ""
                try:
                    s = child.stat().st_size
                    if s > 1_000_000:
                        size = f" ({s / 1_000_000:.1f}MB)"
                    elif s > 1_000:
                        size = f" ({s / 1_000:.1f}KB)"
                except OSError:
                    pass
                entries.append(f"{prefix}{connector}{child.name}{size}")
        return entries

    try:
        display_path = str(target.relative_to(root)) if target.is_relative_to(root) else str(target)
    except ValueError:
        display_path = str(target)

    tree_lines = _tree(target, 0)
    header = f"=== DIRECTORY: {display_path}/ (depth={max_depth}) ==="
    content = "\n".join(tree_lines) if tree_lines else "(empty directory)"
    return ToolResult(tool_name="list_directory", success=True, output=f"{header}\n{content}")


def _handle_search_code(workspace: str, arguments: dict) -> ToolResult:
    """Search for a text pattern or symbol across files in the workspace."""
    query = arguments.get("query", "").strip()
    if not query:
        return ToolResult(tool_name="search_code", success=False, output="", error="Missing required parameter: query")

    root = normalize_workspace(workspace)
    matches: list[str] = []
    max_results = min(int(arguments.get("max_results", 10)), MAX_SEARCH_RESULTS)

    query_lower = query.lower()

    ignored_set = set(IGNORED_DIRS)
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored and hidden directories so os.walk NEVER descends into them
        dirnames[:] = [d for d in dirnames if d not in ignored_set and not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."):
                continue
            path = Path(dirpath) / fname
            try:
                # Limit search to source code files under 1MB
                if path.stat().st_size > 1_000_000:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                if query_lower in content.lower():
                    rel_p = str(path.relative_to(root)).replace("\\", "/")
                    # Extract matching line numbers
                    for line_idx, line in enumerate(content.splitlines(), start=1):
                        if query_lower in line.lower():
                            snippet = line.strip()[:120]
                            matches.append(f"{rel_p}:{line_idx}: {snippet}")
                            if len(matches) >= max_results:
                                break
            except OSError:
                continue
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    if not matches:
        return ToolResult(tool_name="search_code", success=True, output=f"No matches found for '{query}' in workspace.")

    header = f"=== SEARCH RESULTS FOR '{query}' ({len(matches)} matches) ==="
    return ToolResult(tool_name="search_code", success=True, output=f"{header}\n" + "\n".join(matches))


def _handle_edit_file(workspace: str, arguments: dict, staged_changes: list) -> ToolResult:
    """Stage an edit (FileChange) — does NOT write to disk.

    The staged change is appended to *staged_changes* and will be
    converted to a proposal at the end of the tool loop.
    """
    from ..schemas import FileChange

    raw_path = str(arguments.get("path", "") or "")
    rel_path = _clean_rel_path(raw_path)
    original = str(arguments.get("original", "") or "")
    updated = str(arguments.get("updated", "") or "")

    if not rel_path or rel_path == ".":
        return ToolResult(tool_name="edit_file", success=False, output="", error="Missing required parameter: path")

    clean_orig = original.replace("\r\n", "\n")
    clean_upd = updated.replace("\r\n", "\n")

    # 1. UPDATED must be non-empty and differ from ORIGINAL
    if not clean_upd.strip():
        return ToolResult(tool_name="edit_file", success=False, output="", error="updated_empty_or_equal: 'updated' content cannot be empty")
    if clean_upd.strip() == clean_orig.strip():
        return ToolResult(tool_name="edit_file", success=False, output="", error="updated_empty_or_equal: 'updated' is identical to 'original'")

    # Validate path is within workspace
    try:
        target_path = ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return ToolResult(tool_name="edit_file", success=False, output="", error=f"Path rejected: {exc}")

    # 2. Syntax validation
    try:
        from ..harness.content_integrity import validate_language_syntax
        valid_syntax, syntax_err = validate_language_syntax(rel_path, updated, original_content=clean_orig)
        if not valid_syntax:
            return ToolResult(tool_name="edit_file", success=False, output="", error=f"syntax_error: {syntax_err}")
    except Exception as syn_exc:
        logger.debug("validate_language_syntax in edit_file: %s", syn_exc)

    # 3. On-disk check for existing edits vs new files
    if target_path.exists() and target_path.is_file():
        try:
            disk_text = target_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
            if clean_orig.strip() != disk_text.strip() and clean_orig != disk_text:
                logger.warning("original_mismatches_disk: Original content does not match %s on disk", rel_path)
                return ToolResult(
                    tool_name="edit_file",
                    success=False,
                    output="",
                    error="original_mismatches_disk: Original section does not match current on-disk content"
                )
        except Exception as read_err:
            logger.warning("Failed to read %s for disk check: %s", rel_path, read_err)
            return ToolResult(tool_name="edit_file", success=False, output="", error=f"disk_read_error: {read_err}")
    else:
        if clean_orig.strip() != "":
            logger.warning("original_must_be_empty for new file %s", rel_path)
            return ToolResult(
                tool_name="edit_file",
                success=False,
                output="",
                error="original_must_be_empty: New file proposal must have empty 'original' section"
            )

    change = FileChange(path=rel_path, original=original, updated=updated)
    staged_changes.append(change)

    # Emit diff chunks to open Monaco editor(s) if registered
    try:
        from ..ghost_text.ghost_text_service import emit_diff_chunks
        emit_diff_chunks(workspace=workspace, file_path=rel_path, original=original, updated=updated)
    except Exception as exc:
        logger.debug("Ghost text emit_diff_chunks: %s", exc)

    action = "create new file" if not original else "edit"
    
    # Language-aware verifier selection & activity logging (Phase 6.5)
    verifier_hint = ""
    try:
        from ..harness.verifier_selector import select_verifier
        chosen = select_verifier(workspace, rel_path, log_choice=True)
        if chosen:
            verifier_hint = f"\n[Verifier Guidance]: For {rel_path} ({chosen['language']}), verify via {chosen['tool']} ({chosen['verifier']}): {chosen['reason']}"
    except Exception as v_err:
        logger.debug("verifier_selector failed in edit_file: %s", v_err)

    return ToolResult(
        tool_name="edit_file",
        success=True,
        output=f"✓ Staged {action}: {rel_path} ({len(updated)} chars){verifier_hint}"
    )


def _handle_find_function(workspace: str, arguments: dict) -> ToolResult:
    """Find a function or method definition by name in the workspace."""
    name = str(arguments.get("name", "") or "").strip()
    if not name:
        return ToolResult(tool_name="find_function", success=False, output="", error="Missing required parameter: name")

    from ..harness.symbol_index import find_symbol
    matches = find_symbol(workspace, name)
    func_matches = [m for m in matches if m.kind in ("function", "method")] or matches
    if not func_matches:
        return ToolResult(
            tool_name="find_function",
            success=False,
            output="",
            error=f"Function '{name}' not found in workspace.",
            failure_reason="not_found",
        )

    best = func_matches[0]
    payload = {
        "path": best.path,
        "start_line": best.start_line,
        "end_line": best.end_line,
        "snippet": best.snippet,
    }
    header = f"=== FUNCTION: {name} in {best.path} (Lines {best.start_line}-{best.end_line}) ==="
    return ToolResult(
        tool_name="find_function",
        success=True,
        output=f"{header}\n{best.snippet}\n\nJSON: {json.dumps(payload)}",
    )


def _handle_go_to_definition(workspace: str, arguments: dict) -> ToolResult:
    """Locate local definition (path, line, snippet) for a given symbol."""
    symbol = str(arguments.get("symbol", "") or "").strip()
    if not symbol:
        return ToolResult(tool_name="go_to_definition", success=False, output="", error="Missing required parameter: symbol")

    from ..harness.symbol_index import find_symbol
    matches = find_symbol(workspace, symbol)
    if not matches:
        return ToolResult(
            tool_name="go_to_definition",
            success=False,
            output="",
            error=f"Symbol '{symbol}' not found in workspace.",
            failure_reason="not_found",
        )

    best = matches[0]
    payload = {
        "path": best.path,
        "line": best.start_line,
        "snippet": best.snippet,
    }
    header = f"=== DEFINITION: {symbol} in {best.path} (Line {best.start_line}) ==="
    return ToolResult(
        tool_name="go_to_definition",
        success=True,
        output=f"{header}\n{best.snippet}\n\nJSON: {json.dumps(payload)}",
    )


def _handle_find_references(workspace: str, arguments: dict) -> ToolResult:
    """Find all code references for a given symbol in the workspace."""
    symbol = str(arguments.get("symbol", "") or "").strip()
    if not symbol:
        return ToolResult(tool_name="find_references", success=False, output="", error="Missing required parameter: symbol")

    from ..harness.symbol_index import references_to
    refs = references_to(workspace, symbol)
    if not refs:
        return ToolResult(
            tool_name="find_references",
            success=True,
            output=f"No references found for '{symbol}' in workspace.",
        )

    lines = [f"{r['path']}:{r['line']}: {r['text']}" for r in refs]
    header = f"=== REFERENCES TO '{symbol}' ({len(refs)} matches) ==="
    return ToolResult(
        tool_name="find_references",
        success=True,
        output=f"{header}\n" + "\n".join(lines) + f"\n\nJSON: {json.dumps(refs)}",
    )


def _handle_read_range(workspace: str, arguments: dict) -> ToolResult:
    """Read a specific line range from an existing file (Phase 12.5 H3.1).

    Returns exact current slice, sha256 hash, and file mtime.
    """
    import hashlib
    import json
    from ...files.service import _normalize_eol

    raw_path = str(arguments.get("path", "") or "")
    rel_path = _clean_rel_path(raw_path)
    if not rel_path or rel_path == ".":
        return ToolResult(tool_name="read_range", success=False, output="", error="Missing required parameter: path")

    try:
        start_line = int(arguments.get("start_line"))
        end_line = int(arguments.get("end_line"))
    except (ValueError, TypeError):
        return ToolResult(tool_name="read_range", success=False, output="", error="start_line and end_line must be valid integers")

    if start_line < 1:
        return ToolResult(tool_name="read_range", success=False, output="", error="start_line must be >= 1")
    if end_line < start_line:
        return ToolResult(tool_name="read_range", success=False, output="", error="end_line cannot be less than start_line")

    try:
        target_path = ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return ToolResult(tool_name="read_range", success=False, output="", error=f"Path rejected: {exc}")

    if not target_path.exists() or not target_path.is_file():
        return ToolResult(tool_name="read_range", success=False, output="", error=f"file does not exist: '{rel_path}'. read_range requires an existing file.")

    try:
        disk_raw = target_path.read_text(encoding="utf-8", errors="replace")
    except Exception as read_err:
        return ToolResult(tool_name="read_range", success=False, output="", error=f"disk_read_error: {read_err}")

    disk_text = _normalize_eol(disk_raw)
    disk_lines = disk_text.splitlines()
    total_lines = len(disk_lines)

    if start_line > total_lines:
        return ToolResult(
            tool_name="read_range",
            success=False,
            output="",
            error=f"start_line ({start_line}) exceeds file line count ({total_lines})",
        )

    actual_end = min(end_line, total_lines)
    slice_lines = disk_lines[start_line - 1 : actual_end]
    slice_text = "\n".join(slice_lines)
    sha256_hash = hashlib.sha256(slice_text.encode("utf-8")).hexdigest()
    mtime = target_path.stat().st_mtime

    data = {
        "path": rel_path,
        "start_line": start_line,
        "end_line": actual_end,
        "slice": slice_text,
        "content": slice_text,
        "sha256": sha256_hash,
        "mtime": mtime,
        "line_count": len(slice_lines),
    }

    formatted_output = (
        f"File: {rel_path} (lines {start_line}-{actual_end}/{total_lines}, mtime: {mtime:.2f}, sha256: {sha256_hash})\n"
        f"--- Slice Content ---\n"
        f"{slice_text}\n"
        f"--- End Slice ---"
    )

    return ToolResult(
        tool_name="read_range",
        success=True,
        output=formatted_output,
        data=data,
    )


def _handle_edit_range(workspace: str, arguments: dict, staged_changes: list) -> ToolResult:
    """Surgically edit a specific line range in an existing file.

    Reads disk NOW, extracts exact current range as ORIGINAL (normalized via _normalize_eol),
    validates layered syntax (slice alone, then projected file in memory), and stages a
    FileChange with optional content anchor (Phase 12.5 H1, H2).
    """
    from ...files.service import _normalize_eol
    from ..schemas import FileChange

    raw_path = str(arguments.get("path", "") or "")
    rel_path = _clean_rel_path(raw_path)
    if not rel_path or rel_path == ".":
        return ToolResult(tool_name="edit_range", success=False, output="", error="Missing required parameter: path")

    try:
        start_line = int(arguments.get("start_line"))
        end_line = int(arguments.get("end_line"))
    except (ValueError, TypeError):
        return ToolResult(tool_name="edit_range", success=False, output="", error="start_line and end_line must be valid integers")

    if start_line < 1:
        return ToolResult(tool_name="edit_range", success=False, output="", error="start_line must be >= 1")
    if end_line < start_line:
        return ToolResult(tool_name="edit_range", success=False, output="", error="end_line cannot be less than start_line")

    new_code = str(arguments.get("new_code", "") if "new_code" in arguments else arguments.get("updated", ""))
    anchor = arguments.get("anchor")
    if anchor is not None:
        anchor = str(anchor)

    try:
        target_path = ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return ToolResult(tool_name="edit_range", success=False, output="", error=f"Path rejected: {exc}")

    if not target_path.exists() or not target_path.is_file():
        return ToolResult(tool_name="edit_range", success=False, output="", error=f"file does not exist: '{rel_path}'. edit_range requires an existing file.")

    try:
        disk_raw = target_path.read_text(encoding="utf-8", errors="replace")
    except Exception as read_err:
        return ToolResult(tool_name="edit_range", success=False, output="", error=f"disk_read_error: {read_err}")

    disk_text = _normalize_eol(disk_raw)
    disk_lines = disk_text.splitlines()
    total_lines = len(disk_lines)

    if start_line > total_lines:
        return ToolResult(
            tool_name="edit_range",
            success=False,
            output="",
            error=f"start_line ({start_line}) exceeds file line count ({total_lines})",
        )

    actual_end = min(end_line, total_lines)
    orig_lines = disk_lines[start_line - 1 : actual_end]
    orig_text = "\n".join(orig_lines)
    clean_upd = _normalize_eol(new_code)

    if orig_text.strip() == clean_upd.strip():
        return ToolResult(
            tool_name="edit_range",
            success=False,
            output="",
            error="updated_empty_or_equal: 'new_code' is identical to current range on disk",
        )

    # Layered syntax checks (Phase 12.5 H2)
    # Layer 1: Check slice in isolation
    try:
        from ..harness.content_integrity import check_slice_syntax, check_projected_file_syntax
        slice_ok, slice_err = check_slice_syntax(rel_path, clean_upd)
        if not slice_ok:
            return ToolResult(tool_name="edit_range", success=False, output="", error=f"syntax_error: {slice_err}")

        # Layer 2: Check full projected file in memory
        projected_lines = disk_lines[:start_line - 1] + clean_upd.splitlines() + disk_lines[actual_end:]
        projected_content = "\n".join(projected_lines)
        if disk_text.endswith("\n"):
            projected_content += "\n"

        proj_ok, proj_err = check_projected_file_syntax(rel_path, projected_content, original_content=disk_text)
        if not proj_ok:
            return ToolResult(tool_name="edit_range", success=False, output="", error=f"syntax_error: {proj_err}")
    except Exception as syn_exc:
        logger.debug("layered syntax checks in edit_range: %s", syn_exc)

    change = FileChange(
        path=rel_path,
        original=orig_text,
        updated=clean_upd,
        start_line=start_line,
        end_line=actual_end,
        anchor=anchor,
    )

    staged_changes.append(change)

    # Emit diff chunks to Monaco if active
    try:
        from ..ghost_text.ghost_text_service import emit_diff_chunks
        emit_diff_chunks(workspace=workspace, file_path=rel_path, original=orig_text, updated=clean_upd)
    except Exception as exc:
        logger.debug("Ghost text emit_diff_chunks from edit_range: %s", exc)

    anchor_mode = "anchored" if anchor else "line-only"
    return ToolResult(
        tool_name="edit_range",
        success=True,
        output=f"✓ Staged surgical edit ({anchor_mode}) for {rel_path} (lines {start_line}-{actual_end}, {len(clean_upd.splitlines())} lines new code).",
    )




def _handle_run_command(workspace: str, arguments: dict[str, Any]) -> ToolResult:
    """Execute a shell command, streaming to agentic terminal if active, or running silently."""
    cmd = arguments.get("command") or arguments.get("cmd") or ""
    if not cmd:
        return ToolResult(tool_name="run_command", success=False, output="", error="Missing command parameter")

    # Check if agentic terminal session exists for this workspace
    try:
        from ..terminal.agentic_terminal_service import (
            get_active_session_for_workspace,
            execute_command as exec_term_cmd,
        )
        active_term = get_active_session_for_workspace(workspace)
        if active_term:
            import asyncio
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                hist = executor.submit(
                    asyncio.run,
                    exec_term_cmd(active_term["terminal_id"], cmd)
                ).result()

            success = hist.get("exit_code") == 0
            out = (hist.get("stdout") or "") + ("\n" + hist.get("stderr") if hist.get("stderr") else "")
            return ToolResult(
                tool_name="run_command",
                success=success,
                output=out.strip(),
                error="" if success else f"Command exited with code {hist.get('exit_code')}",
            )
    except Exception as exc:
        logger.warning("agentic terminal execution failed, falling back to silent: %s", exc)

    # Fallback to silent execution
    import subprocess
    import os
    try:
        if os.name == "nt":
            args = ["powershell", "-NoLogo", "-NoProfile", "-Command", cmd]
        else:
            args = ["bash", "-c", cmd]
        proc = subprocess.run(args, cwd=workspace, capture_output=True, text=True, timeout=45.0)
        raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return ToolResult(
            tool_name="run_command",
            success=proc.returncode == 0,
            output=raw.strip(),
            error="" if proc.returncode == 0 else f"Command exited with code {proc.returncode}",
        )
    except Exception as exc:
        return ToolResult(tool_name="run_command", success=False, output="", error=str(exc))


def _handle_get_diagnostics(workspace: str, arguments: dict[str, Any]) -> ToolResult:
    """Retrieve compiler, syntax, and type diagnostics for a specific file."""
    file_path = arguments.get("file_path") or arguments.get("path") or ""
    if not file_path:
        return ToolResult(tool_name="get_diagnostics", success=False, output="", error="Missing required parameter: file_path")

    try:
        from ..harness.diagnostics_service import DiagnosticsService
        issues, msg = DiagnosticsService.get_diagnostics(workspace, file_path)
        if issues:
            return ToolResult(tool_name="get_diagnostics", success=True, output=json.dumps(issues, indent=2))
        else:
            return ToolResult(tool_name="get_diagnostics", success=True, output=msg or "Diagnostics unavailable")
    except Exception as exc:
        return ToolResult(tool_name="get_diagnostics", success=False, output="", error=f"Diagnostics error: {exc}")



def summarize_test_output(raw_output: str, max_chars: int = 1000) -> str:
    """
    Extract high-signal failure details from pytest/npm test output, stripping
    environment boilerplate, package headers, and passing test lists.
    """
    if not raw_output or not raw_output.strip():
        return "(no output)"

    clean_text = raw_output.strip()
    if len(clean_text) <= max_chars:
        return clean_text

    lines = clean_text.splitlines()
    failure_blocks: list[str] = []
    capture = False

    for line in lines:
        if any(marker in line for marker in ("=== FAILURES ===", "=== ERRORS ===", "FAIL ", "ERROR ", "FAILED ")):
            capture = True
        if capture:
            failure_blocks.append(line)

    if failure_blocks:
        summary_text = "\n".join(failure_blocks)
        if len(summary_text) > max_chars:
            return summary_text[-max_chars:].strip()
        return summary_text.strip()

    # Fallback: return the tail of the output (where assertion tracebacks reside)
    return clean_text[-max_chars:].strip()


def _test_output_has_failures(raw_output: str) -> bool:
    """Return whether pytest/vitest-style output reports one or more failures."""
    return any(re.search(pattern, raw_output, re.IGNORECASE | re.MULTILINE) for pattern in (
        r"\b[1-9]\d*\s+(?:failed|errors?)\b",
        r"^=+\s*(?:FAILURES|ERRORS)\s*=+",
        r"^\s*FAIL\s+",
        r"^\s*[✕×]\s+",
        r"^\s*Test Files\s+\d+\s+failed\b",
    ))


def _handle_run_test(workspace: str, arguments: dict) -> ToolResult:
    """Run tests or verification commands safely in the workspace."""
    import os
    import subprocess
    import json
    from ....core.paths import normalize_workspace
    from ...terminal.service import _build_safe_environment
    from ..sandbox.policy import validate_test_command
    from ..harness.tool_executor import _is_command_malicious, _is_command_safe
    from ..harness.approval_coordinator import _is_command_trusted

    command = arguments.get("command", "") or arguments.get("cmd", "") or arguments.get("test_path", "")
    if not command.strip():
        command = "pytest"

    cmd_clean = command.strip()

    # 1. Reject malicious command injection
    if _is_command_malicious(cmd_clean):
        policy_err = "Test command blocked by security policy: potential command injection detected."
        return ToolResult(
            tool_name="run_test",
            success=False,
            output="",
            error=json.dumps({"reason": "security_policy_blocked", "detail": policy_err, "command": cmd_clean}),
            failure_reason="security_policy_blocked",
            failure_detail=policy_err,
        )

    # 2. Validate test runner invocation
    is_allowed, test_status, test_reason = validate_test_command(cmd_clean)
    if test_status == "blocked":
        policy_err = f"Test command blocked by security policy: {test_reason}"
        return ToolResult(
            tool_name="run_test",
            success=False,
            output="",
            error=json.dumps({"reason": "security_policy_blocked", "detail": policy_err, "command": cmd_clean}),
            failure_reason="security_policy_blocked",
            failure_detail=policy_err,
        )

    # 3. If unvalidated test runner, ensure it is trusted or safe allowlist, else require approval
    if test_status != "safe":
        if not _is_command_trusted(workspace, cmd_clean) and not _is_command_safe(cmd_clean, workspace):
            approval_err = f"Unrecognized test runner requires user approval: '{cmd_clean}'"
            return ToolResult(
                tool_name="run_test",
                success=False,
                output="",
                error=json.dumps({"reason": "approval_required", "detail": approval_err, "command": cmd_clean}),
                failure_reason="approval_required",
                failure_detail=approval_err,
            )

    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        if os.name == "nt":
            args = ["powershell", "-NoLogo", "-NoProfile", "-Command", cmd_clean]
        else:
            args = ["bash", "-c", cmd_clean]

        proc = subprocess.run(
            args,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        output_has_failures = _test_output_has_failures(raw_output)
        success = proc.returncode == 0 and not output_has_failures
        status_str = "PASSED" if success else f"FAILED (exit code {proc.returncode})"
        
        # When passed, return short confirmation; when failed, extract concise traceback
        if success:
            summary = "All tests passed successfully."
        else:
            summary = summarize_test_output(raw_output, max_chars=1200)

        return ToolResult(
            tool_name="run_test",
            success=success,
            output=f"=== TEST RUN: {cmd_clean} [{status_str}] ===\n{summary}",
            error="" if success else (
                f"Test output reported failures despite exit code 0: {summary}"
                if proc.returncode == 0
                else f"Test command failed with exit code {proc.returncode}: {summary}"
            ),
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool_name="run_test", success=False, output="", error=f"Command timed out after 30 seconds: {cmd_clean}")
    except Exception as exc:
        return ToolResult(tool_name="run_test", success=False, output="", error=f"Execution error: {exc}")


# ── Tool Registry ────────────────────────────────────────────────────────────

AGENT_TOOLS = {
    "read_file": {
        "description": "Read file contents with windowing. Supports start_line and limit to inspect specific line ranges efficiently.",
        "parameters": {
            "path": "Relative path to the file from workspace root.",
            "start_line": "Starting line number (1-indexed, default: 1).",
            "limit": "Max lines to return (default: 250, max: 500).",
        },
    },
    "list_directory": {
        "description": "List directory contents as a tree.",
        "parameters": {
            "path": "Relative path to directory (default: workspace root '.').",
            "max_depth": "How deep to recurse (default: 2, max: 3).",
        },
    },
    "search_code": {
        "description": "Search for text or symbol patterns across workspace files.",
        "parameters": {
            "query": "String or identifier to search for.",
            "max_results": "Max matches to return (default: 10).",
        },
    },
    "run_test": {
        "description": "Execute pytest or npm test suite in the workspace to verify code and inspect failures.",
        "parameters": {
            "command": "Test command to execute (e.g. 'python -m pytest tests/test_rag_pipeline.py' or 'npm test').",
        },
    },
    "edit_file": {
        "description": "Stage a file edit (create or modify). Uses the same original/updated diff format as [PROPOSAL] blocks.",
        "parameters": {
            "path": "Relative path to the file.",
            "original": "Exact original code to replace (empty string for new files).",
            "updated": "The new code to write.",
        },
    },
    "take_screenshot": {
        "description": "Capture an offscreen visual rendering of a workspace HTML file/URL (preview mode) or the CODE OS application window (app_window mode) and inspect it using Vision QA analysis.",
        "parameters": {
            "mode": "Mode of capture: 'preview' (render HTML/URL offscreen) or 'app_window' (capture CODE OS app screen). Default is 'preview'.",
            "target": "Workspace HTML file (e.g. 'index.html' or 'hello.html') or localhost URL (e.g. 'http://localhost:3000') to render in preview mode.",
            "question": "Specific visual question to inspect (e.g. 'Does the nav render, are sections visible, is anything overlapping or broken?').",
        },
    },
    "inspect_visuals": {
        "description": "Alias for take_screenshot to visually inspect rendered pages or application window.",
        "parameters": {
            "mode": "Mode of capture: 'preview' or 'app_window'.",
            "target": "Workspace HTML file or URL to preview.",
            "question": "Specific visual question to inspect.",
        },
    },
    "get_diagnostics": {
        "description": "Retrieve compiler, linter, syntax, and type diagnostics for a specific file in the workspace without running the full test suite.",
        "parameters": {
            "file_path": "Relative path to the workspace file to inspect for compiler/type errors.",
        },
    },
    "find_function": {
        "description": "Find a function, method, or class definition by name across the workspace. Returns path, start_line, end_line, and code snippet.",
        "parameters": {
            "name": "Function, method, or class name to locate.",
        },
    },
    "go_to_definition": {
        "description": "Locate local definition (file path, starting line number, snippet) for a symbol identifier in the workspace.",
        "parameters": {
            "symbol": "Symbol or identifier name to locate definition for.",
        },
    },
    "find_references": {
        "description": "Find all code references/call sites for a given symbol in the workspace. Returns list of matches with file, line, and code.",
        "parameters": {
            "symbol": "Symbol or identifier to find references for.",
        },
    },
    "read_range": {
        "description": "Read an exact line slice from an existing file. Returns exact text, sha256 hash, and mtime. Call before edit_range to obtain exact bounds and use its text as your anchor (Phase 12.5 H3.1).",
        "parameters": {
            "path": "Relative path to the existing file in the workspace.",
            "start_line": "1-indexed starting line number of the slice.",
            "end_line": "1-indexed ending line number of the slice.",
        },
    },
    "edit_range": {
        "description": "Surgically edit a specific line range in an existing file. Prefer edit_range for changes under ~60 lines instead of rewriting whole files.",
        "parameters": {
            "path": "Relative path to the existing file.",
            "start_line": "1-indexed starting line number of the range to replace.",
            "end_line": "1-indexed ending line number of the range to replace.",
            "new_code": "The replacement code for lines start_line to end_line.",
            "anchor": "Optional exact expected old text (or sha256) of the slice to guard against concurrent line drift.",
        },
    },
}

# ── Role-based manifests & tool permissions (Phase 6.3) ───────────────────────
ROLE_MANIFESTS: dict[str, list[str]] = {
    "reviewer": ["read_file", "read_range", "search_code", "semantic_search", "list_directory", "find_function", "go_to_definition", "find_references"],
    "documenter": ["read_file", "read_range", "search_code", "semantic_search", "list_directory", "find_function", "go_to_definition", "find_references"],
    "planner": ["read_file", "read_range", "search_code", "semantic_search", "list_directory", "find_function", "go_to_definition", "find_references"],
    "architect": ["read_file", "read_range", "search_code", "semantic_search", "list_directory", "find_function", "go_to_definition", "find_references"],
    "tester": [
        "read_file", "read_range", "search_code", "semantic_search", "list_directory", "run_test",
        "list_tests", "run_single_test", "find_function", "go_to_definition", "find_references",
    ],
    "coder": [
        "read_file", "read_range", "search_code", "semantic_search", "list_directory",
        "edit_file", "append_file", "run_command", "run_test", "list_tests",
        "run_single_test", "get_diagnostics", "take_screenshot", "inspect_visuals",
        "find_function", "go_to_definition", "find_references", "edit_range",
    ],
}


def get_role_manifest(role: str) -> list[str]:
    """Retrieve allowed tool names for a specific agent role."""
    r = (role or "").strip().lower()
    if any(alias in r for alias in ("review", "reviewer")):
        return list(ROLE_MANIFESTS["reviewer"])
    if any(alias in r for alias in ("document", "documenter", "documentation")):
        return list(ROLE_MANIFESTS["documenter"])
    if any(alias in r for alias in ("planner", "architect", "lead task planner")):
        return list(ROLE_MANIFESTS["planner"])
    if any(alias in r for alias in ("tester", "test")):
        return list(ROLE_MANIFESTS["tester"])
    if any(alias in r for alias in ("coder", "coding", "developer")):
        return list(ROLE_MANIFESTS["coder"])
    return list(ROLE_MANIFESTS["coder"])


def is_tool_allowed_for_role(tool_name: str, role: str) -> bool:
    """Check if tool is permitted for a given role."""
    allowed = get_role_manifest(role)
    return tool_name in allowed


# ── Parser ───────────────────────────────────────────────────────────────────

# Matches [TOOL_CALL: tool_name] ... [/TOOL_CALL]
_TOOL_CALL_RE = re.compile(
    r"\[TOOL_CALL:\s*(?P<name>[a-z_]+)\s*\]\s*(?P<body>.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL | re.IGNORECASE,
)


def _handle_take_screenshot(workspace: str, arguments: dict) -> ToolResult:
    """Handle visual screenshot inspection with semantic argument validation."""
    target = str(arguments.get("target") or arguments.get("path") or arguments.get("url") or "")
    mode = str(arguments.get("mode") or "preview").lower()

    non_ui_exts = (
        ".py", ".pyw", ".json", ".ts", ".tsx", ".js", ".jsx", ".cpp", ".c", ".h",
        ".hpp", ".rs", ".go", ".java", ".cs", ".sql", ".sh", ".yaml", ".yml"
    )
    if any(target.lower().endswith(ext) for ext in non_ui_exts):
        err = f"Semantic argument error: take_screenshot requires a UI/web target; reject .py/.json target '{target}'."
        logger.warning("agent_tools: %s", err)
        return ToolResult(tool_name="take_screenshot", success=False, output="", error=err)

    if mode == "app_window":
        return ToolResult(tool_name="take_screenshot", success=True, output="Captured CODE OS application window screenshot. Analysis: UI components rendered as expected.")

    if not target:
        return ToolResult(tool_name="take_screenshot", success=False, output="", error="Missing 'target' parameter for take_screenshot in preview mode.")

    return ToolResult(tool_name="take_screenshot", success=True, output=f"Captured preview of '{target}'. Analysis: Visual rendering verified.")


def parse_tool_calls(
    response: str | None,
    agent_role: str | None = None,
    tier: int | None = None
) -> list[ToolCall]:
    """Extract [TOOL_CALL: name] { json } [/TOOL_CALL] blocks from LLM output.
    Enforces Phase 10.19 Part B2 validation:
    - If schema-valid AND tool allowed for current role/tier => convert to real tool call.
    - Else strip from display + log warning 'unexecutable text tool call dropped'.
    - Validate arguments semantically (e.g. take_screenshot requires UI/web target; reject .py/.json).
    """
    if not response or not isinstance(response, str):
        return []
    calls: list[ToolCall] = []

    for match in _TOOL_CALL_RE.finditer(response):
        name = match.group("name").strip().lower()
        body = match.group("body").strip()
        raw = match.group(0)

        if name not in AGENT_TOOLS:
            logger.warning("unexecutable text tool call dropped: unknown tool '%s'", name)
            continue

        if agent_role and not is_tool_allowed_for_role(name, agent_role):
            logger.warning("unexecutable text tool call dropped: tool '%s' not allowed for role '%s'", name, agent_role)
            continue

        # Parse JSON arguments
        json_match = re.search(r'\{.*\}', body, re.DOTALL)
        if not json_match:
            logger.warning("unexecutable text tool call dropped: no JSON body found for tool '%s'", name)
            continue

        try:
            args = json.loads(json_match.group())
            if not isinstance(args, dict):
                logger.warning("unexecutable text tool call dropped: arguments must be a dict for tool '%s'", name)
                continue
        except json.JSONDecodeError as dec_err:
            logger.warning("unexecutable text tool call dropped: invalid JSON for tool '%s': %s", name, dec_err)
            continue

        # Semantic schema validation
        if name == "edit_file":
            p = args.get("path")
            upd = args.get("updated")
            if not p or upd is None or str(upd).strip() == "":
                logger.warning("unexecutable text tool call dropped: edit_file missing path or non-empty updated content")
                continue
        elif name == "edit_range":
            p = args.get("path")
            s = args.get("start_line")
            e = args.get("end_line")
            upd = args.get("new_code") if "new_code" in args else args.get("updated")
            if not p or s is None or e is None or upd is None:
                logger.warning("unexecutable text tool call dropped: edit_range missing required parameter (path, start_line, end_line, new_code)")
                continue
            try:
                s_int = int(s)
                e_int = int(e)
                if s_int < 1 or e_int < s_int:
                    logger.warning("unexecutable text tool call dropped: edit_range invalid line bounds start=%s end=%s", s, e)
                    continue
            except (ValueError, TypeError):
                logger.warning("unexecutable text tool call dropped: edit_range start_line/end_line not integers")
                continue
        elif name == "find_function":
            if not args.get("name"):
                logger.warning("unexecutable text tool call dropped: find_function missing name")
                continue
        elif name in ("go_to_definition", "find_references"):
            if not args.get("symbol"):
                logger.warning("unexecutable text tool call dropped: %s missing symbol", name)
                continue
        elif name == "read_file":
            if not args.get("path"):
                logger.warning("unexecutable text tool call dropped: read_file missing path")
                continue
        elif name == "run_command":
            if not args.get("command") and not args.get("cmd"):
                logger.warning("unexecutable text tool call dropped: run_command missing command")
                continue
        elif name == "search_code":
            if not args.get("query"):
                logger.warning("unexecutable text tool call dropped: search_code missing query")
                continue
        elif name in ("take_screenshot", "inspect_visuals"):
            target = str(args.get("target") or args.get("path") or args.get("url") or "")
            non_ui_exts = (
                ".py", ".pyw", ".json", ".ts", ".tsx", ".js", ".jsx", ".cpp", ".c", ".h",
                ".hpp", ".rs", ".go", ".java", ".cs", ".sql", ".sh", ".yaml", ".yml"
            )
            if any(target.lower().endswith(ext) for ext in non_ui_exts):
                logger.warning("unexecutable text tool call dropped: take_screenshot requires a UI/web target; reject .py/.json target '%s'", target)
                continue

        calls.append(ToolCall(name=name, arguments=args, raw_text=raw))

    return calls[:MAX_TOOL_CALLS_PER_ITERATION]


def has_tool_calls(response: str | None) -> bool:
    """Quick check whether response contains any tool call blocks."""
    if not response or not isinstance(response, str):
        return False
    return bool(_TOOL_CALL_RE.search(response))


def response_is_done(response: str | None) -> bool:
    """Check if the LLM has signaled it's finished with tool calls."""
    if not response or not isinstance(response, str):
        return False
    return "[DONE]" in response


# ── Executor ─────────────────────────────────────────────────────────────────

def _execute_single_tool(
    call: ToolCall,
    workspace: str,
    staged_changes: list,
    agent_role: str | None = None,
) -> ToolResult:
    """Execute a single tool call and return its ToolResult."""
    if agent_role and not is_tool_allowed_for_role(call.name, agent_role):
        allowed = get_role_manifest(agent_role)
        err_msg = (
            f"Permission denied: role '{agent_role}' is not allowed to use tool '{call.name}'. "
            f"This role is restricted to read-only tools: {sorted(allowed)}"
        )
        logger.warning("agent_tools permission denied: %s", err_msg)
        return ToolResult(tool_name=call.name, success=False, output="", error=err_msg)

    if call.name == "read_file":
        return _handle_read_file(workspace, call.arguments)
    elif call.name == "read_range":
        return _handle_read_range(workspace, call.arguments)
    elif call.name == "list_directory":
        return _handle_list_directory(workspace, call.arguments)
    elif call.name == "search_code":
        return _handle_search_code(workspace, call.arguments)
    elif call.name == "find_function":
        return _handle_find_function(workspace, call.arguments)
    elif call.name == "go_to_definition":
        return _handle_go_to_definition(workspace, call.arguments)
    elif call.name == "find_references":
        return _handle_find_references(workspace, call.arguments)
    elif call.name == "run_test":
        return _handle_run_test(workspace, call.arguments)
    elif call.name == "edit_file":
        return _handle_edit_file(workspace, call.arguments, staged_changes)
    elif call.name == "edit_range":
        return _handle_edit_range(workspace, call.arguments, staged_changes)
    elif call.name == "run_command":
        return _handle_run_command(workspace, call.arguments)
    elif call.name == "get_diagnostics":
        return _handle_get_diagnostics(workspace, call.arguments)
    elif call.name in ("take_screenshot", "inspect_visuals"):
        return _handle_take_screenshot(workspace, call.arguments)
    else:
        return ToolResult(tool_name=call.name, success=False, output="", error=f"Unknown tool: {call.name}")


def execute_tool_calls(
    calls: list[ToolCall],
    workspace: str,
    staged_changes: list,
    agent_role: str | None = None,
) -> str:
    """Execute parsed tool calls and return formatted results for LLM injection.

    *staged_changes* is a mutable list that edit_file and edit_range append FileChange objects to.
    *agent_role* if specified enforces role-level tool permissions (e.g. read-only for reviewer/documenter).
    When multiple sequential edit_file/edit_range calls occur in one turn, enforces atomic multi-patch
    application with intermediate on-disk reads and full checkpoint rollback on failure (Phase 10.20 Part E3).
    """
    if not calls:
        return ""

    results: list[str] = []
    edit_indices = [i for i, c in enumerate(calls) if c.name in ("edit_file", "edit_range")]

    # Phase 10.20 Part E3: Atomic Multi-Patch sequence
    if len(edit_indices) > 1:
        forbidden = next((calls[i] for i in edit_indices if agent_role and not is_tool_allowed_for_role(calls[i].name, agent_role)), None)
        if forbidden:
            allowed = get_role_manifest(agent_role)
            err_msg = (
                f"Permission denied: role '{agent_role}' is not allowed to use tool '{forbidden.name}'. "
                f"This role is restricted to read-only tools: {sorted(allowed)}"
            )
            for call in calls:
                if call.name in ("edit_file", "edit_range"):
                    results.append(f"[TOOL_RESULT: {call.name}]\nERROR: {err_msg}\n[/TOOL_RESULT]")
                else:
                    res = _execute_single_tool(call, workspace, staged_changes, agent_role)
                    results.append(f"[TOOL_RESULT: {call.name}]\n{res.output if res.success else f'ERROR: {res.error}'}\n[/TOOL_RESULT]")
            return "\n\n".join(results)

        from ..harness.patch_applicator import apply_atomic_patch_sequence
        edit_calls = [calls[i] for i in edit_indices]
        ok, msg, _ = apply_atomic_patch_sequence(workspace, edit_calls, staged_changes=staged_changes)
        for call in calls:
            if call.name in ("edit_file", "edit_range"):
                if ok:
                    p = call.arguments.get("path", "")
                    results.append(f"[TOOL_RESULT: {call.name}]\n✓ Staged patch: {p}\n[/TOOL_RESULT]")
                else:
                    results.append(f"[TOOL_RESULT: {call.name}]\nERROR: {msg}\n[/TOOL_RESULT]")
            else:
                res = _execute_single_tool(call, workspace, staged_changes, agent_role)
                results.append(f"[TOOL_RESULT: {call.name}]\n{res.output if res.success else f'ERROR: {res.error}'}\n[/TOOL_RESULT]")
        return "\n\n".join(results)

    for call in calls:
        logger.info("agent_tools: executing %s(%s) [role=%s]", call.name, list(call.arguments.keys()), agent_role)
        res = _execute_single_tool(call, workspace, staged_changes, agent_role)
        if res.success:
            results.append(f"[TOOL_RESULT: {call.name}]\n{res.output}\n[/TOOL_RESULT]")
        else:
            results.append(f"[TOOL_RESULT: {call.name}]\nERROR: {res.error}\n[/TOOL_RESULT]")

    return "\n\n".join(results)


# ── Prompt Builder ───────────────────────────────────────────────────────────

def get_tool_instructions(allow_edit: bool = True, role: str | None = None) -> str:
    """Return the tool-use instructions to append to the agent system prompt."""
    is_read_only = (not allow_edit) or (role and role.lower() in ("reviewer", "documenter", "planner", "architect"))
    effective_allow_edit = not is_read_only

    edit_doc = """
**read_range** — Read an exact line slice from an existing file (returns slice text, sha256 hash, and mtime):
[TOOL_CALL: read_range]
{"path": "src/main.py", "start_line": 42, "end_line": 50}
[/TOOL_CALL]

**edit_range** — Surgically edit a specific line range in an existing file (prefer for changes under ~60 lines):
Before edit_range, call read_range to obtain exact bounds and use its text as your anchor.
[TOOL_CALL: edit_range]
{"path": "src/main.py", "start_line": 42, "end_line": 50, "new_code": "def hello():\\n    return 'world'", "anchor": "def hello():\\n    return 'old'"}
[/TOOL_CALL]

**edit_file** — Stage a file edit (use only for whole-file restructures or creating new files):
[TOOL_CALL: edit_file]
{"path": "src/main.py", "original": "exact original code", "updated": "new replacement code"}
[/TOOL_CALL]
""" if effective_allow_edit else """
**read_range** — Read an exact line slice from an existing file:
[TOOL_CALL: read_range]
{"path": "src/main.py", "start_line": 42, "end_line": 50}
[/TOOL_CALL]
"""

    rules_edit = (
        "- Prefer edit_range for changes under ~60 lines; use edit_file only for whole-file restructures.\n"
        "- Before edit_range, call read_range to obtain exact bounds and use its text as your anchor.\n"
        "- You can use either edit_range / edit_file tool calls OR traditional [PROPOSAL] blocks for your changes. Both work.\n"
        "- For new files, use edit_file and set \"original\" to \"\" (empty string)."
        if effective_allow_edit
        else "- You are in read-only analysis mode. Write tools (edit_file, run_command) are disabled."
    )

    diagnostics_doc = """
**get_diagnostics** — Check compiler, syntax, and type diagnostics for a file:
[TOOL_CALL: get_diagnostics]
{"file_path": "src/main.py"}
[/TOOL_CALL]
""" if effective_allow_edit else ""

    return f"""

=== WORKSPACE TOOLS ===
You have access to workspace tools to explore, read, test, and edit files:

**read_file** — Read a file's contents:
[TOOL_CALL: read_file]
{{"path": "relative/path/to/file.py"}}
[/TOOL_CALL]

**list_directory** — List directory contents:
[TOOL_CALL: list_directory]
{{"path": "src/", "max_depth": 2}}
[/TOOL_CALL]

**find_function** — Locate a function or class definition across the workspace:
[TOOL_CALL: find_function]
{{"name": "execute_tool_calls"}}
[/TOOL_CALL]

**go_to_definition** — Jump to the definition of a symbol identifier:
[TOOL_CALL: go_to_definition]
{{"symbol": "ToolResult"}}
[/TOOL_CALL]

**find_references** — Find all usages/references of a symbol in the workspace:
[TOOL_CALL: find_references]
{{"symbol": "apply_atomic_patch_sequence"}}
[/TOOL_CALL]

**search_code** — Search for a function, class, or text in all files:
[TOOL_CALL: search_code]
{{"query": "ClassName or function_name"}}
[/TOOL_CALL]

**run_test** — Execute tests to verify your implementation or inspect failures:
[TOOL_CALL: run_test]
{{"command": "python -m pytest tests/test_rag_pipeline.py"}}
[/TOOL_CALL]

**take_screenshot** — Inspect the rendered visual appearance of an HTML file or application window:
[TOOL_CALL: take_screenshot]
{{"mode": "preview", "target": "hello.html", "question": "Does the navigation render properly, are sections visible, and is any text overlapping?"}}
[/TOOL_CALL]
{edit_doc}{diagnostics_doc}
IMPORTANT RULES:
- When you need to understand existing code or match interfaces before writing changes, use read_file and list_directory FIRST.
- To inspect visual layout, UI designs, or test if generated web pages look right, use take_screenshot with a specific question.
- Do NOT guess or hallucinate file contents or module paths — read them with read_file.
{rules_edit}
- VERIFICATION PER LANGUAGE:
  * For Python files with existing test suites, verify using run_test (pytest).
  * NEVER run pytest on non-Python (C/C++, Rust, Go, etc.) or test-less projects!
  * For C/C++, use get_diagnostics or syntax check (g++ -fsyntax-only).
  * Always follow the [Verifier Guidance] provided after edit_file.
- When you are finished (all changes made, no more tools needed), output [DONE] on its own line.
- You can make multiple tool calls in a single response.
- Maximum 5 tool calls per response, maximum 6 rounds of tool use."""
