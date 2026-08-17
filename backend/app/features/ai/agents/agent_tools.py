"""
agent_tools.py — File-system tool definitions for CODE OS agents.

Provides read_file, list_directory, search_code, and edit_file tools that agents can invoke
via structured [TOOL_CALL: ...] blocks in their LLM output.  Tool results are
injected back into the conversation so the LLM can iterate.

Security: All file access goes through core.paths.ensure_within_workspace().
"""

import json
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

        return ToolResult(tool_name="read_file", success=True, output=f"{header}\n{content}{truncated_hint}")
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

    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS or part.startswith(".") for part in path.parts):
            continue
        if path.is_file():
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

    raw_path = arguments.get("path", "")
    rel_path = _clean_rel_path(raw_path)
    original = arguments.get("original", "")
    updated = arguments.get("updated", "")

    if not rel_path or rel_path == ".":
        return ToolResult(tool_name="edit_file", success=False, output="", error="Missing required parameter: path")
    if not updated and not original:
        return ToolResult(tool_name="edit_file", success=False, output="", error="Both 'original' and 'updated' are empty — nothing to do")

    # Validate path is within workspace
    try:
        ensure_within_workspace(workspace, rel_path)
    except Exception as exc:
        return ToolResult(tool_name="edit_file", success=False, output="", error=f"Path rejected: {exc}")

    change = FileChange(path=rel_path, original=original, updated=updated)
    staged_changes.append(change)

    action = "create new file" if not original else "edit"
    return ToolResult(
        tool_name="edit_file",
        success=True,
        output=f"✓ Staged {action}: {rel_path} ({len(updated)} chars)"
    )


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


def _handle_run_test(workspace: str, arguments: dict) -> ToolResult:
    """Run tests or verification commands safely in the workspace."""
    import os
    import subprocess
    from ....core.paths import normalize_workspace
    from ...terminal.service import _build_safe_environment

    command = arguments.get("command", "") or arguments.get("cmd", "")
    if not command.strip():
        command = "python -m pytest"

    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        if os.name == "nt":
            args = ["powershell", "-NoLogo", "-NoProfile", "-Command", command]
        else:
            args = ["bash", "-c", command]

        proc = subprocess.run(
            args,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        status_str = "PASSED" if proc.returncode == 0 else f"FAILED (exit code {proc.returncode})"
        
        # When passed, return short confirmation; when failed, extract concise traceback
        if proc.returncode == 0:
            summary = "All tests passed successfully."
        else:
            summary = summarize_test_output(raw_output, max_chars=1200)

        return ToolResult(
            tool_name="run_test",
            success=True,
            output=f"=== TEST RUN: {command} [{status_str}] ===\n{summary}"
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool_name="run_test", success=False, output="", error=f"Command timed out after 30 seconds: {command}")
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
}


# ── Parser ───────────────────────────────────────────────────────────────────

# Matches [TOOL_CALL: tool_name] ... [/TOOL_CALL]
_TOOL_CALL_RE = re.compile(
    r"\[TOOL_CALL:\s*(?P<name>[a-z_]+)\s*\]\s*(?P<body>.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL | re.IGNORECASE,
)


def parse_tool_calls(response: str) -> list[ToolCall]:
    """Extract [TOOL_CALL: name] { json } [/TOOL_CALL] blocks from LLM output."""
    calls: list[ToolCall] = []

    for match in _TOOL_CALL_RE.finditer(response):
        name = match.group("name").strip().lower()
        body = match.group("body").strip()
        raw = match.group(0)

        if name not in AGENT_TOOLS:
            logger.warning("agent_tools: unknown tool '%s' — skipping", name)
            continue

        # Parse JSON arguments
        try:
            # Try to extract JSON object from the body
            json_match = re.search(r'\{.*\}', body, re.DOTALL)
            if json_match:
                args = json.loads(json_match.group())
            else:
                # Fallback: treat the whole body as a single path argument
                args = {"path": body.strip().strip("\"'")}
        except json.JSONDecodeError:
            logger.warning("agent_tools: failed to parse JSON for tool '%s': %s", name, body[:100])
            args = {"path": body.strip().strip("\"'")}

        calls.append(ToolCall(name=name, arguments=args, raw_text=raw))

    return calls[:MAX_TOOL_CALLS_PER_ITERATION]


def has_tool_calls(response: str) -> bool:
    """Quick check whether response contains any tool call blocks."""
    return bool(_TOOL_CALL_RE.search(response))


def response_is_done(response: str) -> bool:
    """Check if the LLM has signaled it's finished with tool calls."""
    return "[DONE]" in response


# ── Executor ─────────────────────────────────────────────────────────────────

def execute_tool_calls(
    calls: list[ToolCall],
    workspace: str,
    staged_changes: list,
) -> str:
    """Execute parsed tool calls and return formatted results for LLM injection.

    *staged_changes* is a mutable list that edit_file appends FileChange objects to.
    """
    if not calls:
        return ""

    results: list[str] = []

    for call in calls:
        logger.info("agent_tools: executing %s(%s)", call.name, list(call.arguments.keys()))

        if call.name == "read_file":
            result = _handle_read_file(workspace, call.arguments)
        elif call.name == "list_directory":
            result = _handle_list_directory(workspace, call.arguments)
        elif call.name == "search_code":
            result = _handle_search_code(workspace, call.arguments)
        elif call.name == "run_test":
            result = _handle_run_test(workspace, call.arguments)
        elif call.name == "edit_file":
            result = _handle_edit_file(workspace, call.arguments, staged_changes)
        else:
            result = ToolResult(tool_name=call.name, success=False, output="", error=f"Unknown tool: {call.name}")

        if result.success:
            results.append(f"[TOOL_RESULT: {call.name}]\n{result.output}\n[/TOOL_RESULT]")
        else:
            results.append(f"[TOOL_RESULT: {call.name}]\nERROR: {result.error}\n[/TOOL_RESULT]")

    return "\n\n".join(results)


# ── Prompt Builder ───────────────────────────────────────────────────────────

def get_tool_instructions(allow_edit: bool = True) -> str:
    """Return the tool-use instructions to append to the agent system prompt."""
    edit_doc = """
**edit_file** — Stage a file edit (same as [PROPOSAL] blocks):
[TOOL_CALL: edit_file]
{"path": "src/main.py", "original": "exact original code", "updated": "new replacement code"}
[/TOOL_CALL]
""" if allow_edit else ""

    rules_edit = "- You can use either edit_file tool calls OR traditional [PROPOSAL] blocks for your changes. Both work.\n- For new files, set \"original\" to \"\" (empty string)." if allow_edit else "- You are in read-only analysis mode."

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

**search_code** — Search for a function, class, or text in all files:
[TOOL_CALL: search_code]
{{"query": "ClassName or function_name"}}
[/TOOL_CALL]

**run_test** — Execute tests to verify your implementation or inspect failures:
[TOOL_CALL: run_test]
{{"command": "python -m pytest tests/test_rag_pipeline.py"}}
[/TOOL_CALL]
{edit_doc}
IMPORTANT RULES:
- When you need to understand existing code or match interfaces before writing changes, use read_file and list_directory FIRST.
- Do NOT guess or hallucinate file contents or module paths — read them with read_file.
{rules_edit}
- When you are finished (all changes made, no more tools needed), output [DONE] on its own line.
- You can make multiple tool calls in a single response.
- Maximum 5 tool calls per response, maximum 6 rounds of tool use."""
