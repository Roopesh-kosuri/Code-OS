from __future__ import annotations
_file_read_cache: dict[str, tuple[float, str]] = {}
"""
tool_executor.py - Execution handlers for chat agent workspace tools.
"""

import difflib
import json
import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.ai.schemas import FileChange
from .compaction_manager import _generate_diff_summary

logger = logging.getLogger(__name__)

PROJECT_MEMORY_MAX_CHARS = 4000

# ── Constants & Limits ───────────────────────────────────────────────────────

# Leashes cap one task's tool turns; they do not cap total file size because
# large files are produced through sequential append_file turns.
MAX_AGENT_ITERATIONS = 50
MAX_HUGE_TASK_ITERATIONS = 150
MAX_QUICK_TASK_ITERATIONS = 10
MAX_TOOL_CALLS_PER_ITERATION = 5
MAX_RETRY_BEFORE_ESCALATE = 3
SEMANTIC_SEARCH_TOP_K = 10
COMMAND_APPROVAL_TIMEOUT_SECONDS = 60.0
EDIT_APPROVAL_TIMEOUT_SECONDS = 300.0
APPROVAL_TIMEOUT_SECONDS = 120.0
COMPACTION_THRESHOLD_TURNS = 5

# Strict allowlist for terminal commands that can run without interactive approval.
# Fail CLOSED: anything not on this list requires explicit user approval.
SAFE_COMMAND_ALLOWLIST = frozenset({
    "cat", "type",          # read file contents
    "ls", "dir",            # list directory
    "grep", "findstr",      # search
    "head", "tail",         # partial reads
    "wc",                   # word count
    "pwd", "cd",            # navigation
    "echo",                 # print
    "which", "where",       # locate commands
    "git status", "git log", "git diff", "git branch", "git show",
    "git rev-parse",        # git read-only inspection
    "python --version", "python3 --version",
    "node --version", "npm --version",
    "pip list", "pip show", "pip freeze",
    "npm list", "npm ls",
    "tree",                 # directory tree
    "env", "printenv", "set",  # environment
    "whoami",               # identity
    "date",                 # time
    "uname",                # system info
    "file",                 # file type detection
})

SAFE_COMMAND_PREFIXES = tuple(sorted([
    "cat ", "type ", "ls ", "dir ", "grep ", "findstr ",
    "head ", "tail ", "wc ", "echo ", "which ", "where ",
    "git status", "git log", "git diff", "git branch", "git show",
    "git rev-parse",
    "pip list", "pip show", "pip freeze",
    "npm list", "npm ls",
    "tree ", "file ",
    "python --version", "python3 --version",
    "node --version", "npm --version",
], key=lambda x: -len(x)))

MALICIOUS_COMMAND_PATTERNS = [
    r"curl\s+.*\|\s*(bash|sh|zsh|powershell|pwsh|cmd)",
    r"wget\s+.*\|\s*(bash|sh|zsh|powershell|pwsh|cmd)",
    r"eval\s+\$\(.*\)",
    r"curl\s+.*-o\s+(/tmp/|C:\\Windows\\Temp\\|%TEMP%|[A-Za-z]:\\[^ \t\n\r]+\.exe)",
    r"(?i)\b(?:Invoke-Expression|iex)\b[^;\r\n|&]{0,250}\b(?:Invoke-WebRequest|iwr|curl|wget)\b",
    r"powershell.*-enc\s+[A-Za-z0-9+/=]{20,}",
]




from app.features.ai.agents.agent_tools import (
    _handle_read_file,
    _handle_list_directory,
    _handle_search_code,
    _handle_run_test,
    parse_tool_calls,
    has_tool_calls,
    ToolCall,
    ToolResult,
    summarize_test_output,
    _clean_rel_path,
    AGENT_TOOLS,
)

HARNESS_TOOLS = {
    **AGENT_TOOLS,
    "list_tests": {
        "description": "Discover all pytest test node IDs in the workspace without executing them (runs pytest --collect-only -q). Read-only, no approval needed.",
        "parameters": {},
    },
    "run_single_test": {
        "description": "Run a single specific test by its pytest node ID (e.g. 'tests/test_foo.py::test_bar') rather than executing the entire test suite.",
        "parameters": {
            "node_id": "The test node ID to execute (e.g. 'tests/test_foo.py::test_bar').",
        },
    },
    "append_file": {
        "description": "Append text content to a staged or existing file without requiring verbatim original. Used for chunked large-file generation.",
        "parameters": {
            "path": "Relative path to the file.",
            "content": "Content chunk to append to the file.",
        },
    },
    "semantic_search": {
        "description": "Search workspace files by concept/meaning using TF-IDF ranking. Best when exact symbol or filename is unknown.",
        "parameters": {
            "query": "Natural language query describing the desired logic or component.",
        },
    },
    "run_command": {
        "description": "Execute a terminal command in the workspace. Safe read-only commands (ls, cat, grep, git status) run immediately. Other commands trigger an interactive user approval card. Set require_sandbox=True to force container isolation.",
        "parameters": {
            "command": "The terminal command string to execute.",
            "require_sandbox": "Optional boolean: when True, forces execution inside a Docker container sandbox (fails closed if container runtime is unavailable).",
        },
    },
    "memory_write": {
        "description": "Save a persistent project convention, user preference, or architectural rule to RONY.md.",
        "parameters": {
            "fact": "The rule, convention, or preference to remember for this project.",
        },
    },
    "ask_user": {
        "description": "Ask the user a clarifying question with quick-reply options when requirements are ambiguous or underspecified.",
        "parameters": {
            "question": "The clarifying question to ask.",
            "options": "List of 2-4 quick-reply options for the user to choose from.",
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
    "find_references": {
        "description": "Find all usages, call sites, and references of a symbol (function, class, variable, constant) across all files in the workspace.",
        "parameters": {
            "symbol": "The identifier/symbol name to find references for.",
        },
    },
    "go_to_definition": {
        "description": "Locate the defining file, line number, and signature for a symbol (function, class, constant).",
        "parameters": {
            "symbol": "The symbol/identifier name to locate.",
        },
    },
    "server_session": {
        "description": "Manage background server processes and perform live HTTP requests for full-stack API verification. Actions: 'start' (command, port), 'request' (method, path, body), 'stop' (session_id), 'list'.",
        "parameters": {
            "action": "Action to perform: 'start', 'request', 'stop', or 'list'.",
            "command": "Server startup command (e.g. 'python -m uvicorn app.main:app --port 8000' or 'node server.js'). Required for 'start'.",
            "port": "Port to bind/request (e.g. 8000, 3000, 5000).",
            "method": "HTTP method for 'request' (GET, POST, PUT, DELETE). Default GET.",
            "path": "HTTP path to hit (e.g. '/api/items', '/health'). Default '/'.",
            "body": "JSON payload or string for POST/PUT requests.",
            "session_id": "Session ID returned from start, required for 'stop' or targeting specific session in 'request'.",
        },
    },
    "git_diff": {
        "description": "Get structured git diff and file change summary compared to the last checkpoint commit or specific revision.",
        "parameters": {
            "since_commit": "Commit hash to compare against. If omitted, compares to the latest rony-turn-N checkpoint or HEAD.",
            "paths": "Optional list of file paths to limit diff scope.",
        },
    },
    "find_dead_code": {
        "description": "Analyze workspace dependency graph and detect unreferenced or orphan source files with zero incoming imports.",
        "parameters": {
            "paths": "Optional list of paths to scan.",
        },
    },
    "update_architecture_doc": {
        "description": "Scan workspace structure and generate/update ARCHITECTURE.md with module map and key entry points.",
        "parameters": {
            "reason": "Reason for updating the architecture documentation.",
        },
    },
    "browser_open": {
        "description": "Open a URL in an isolated Playwright browser instance, returning page title and HTTP status code.",
        "parameters": {
            "url": "Target URL (e.g. 'http://localhost:3000' or 'http://localhost:8000').",
        },
    },
    "browser_screenshot": {
        "description": "Capture a visual screenshot of the current browser page, returning PNG filepath and base64 image encoding.",
        "parameters": {
            "filename": "Optional custom filename for the screenshot.",
        },
    },
    "browser_console_logs": {
        "description": "Retrieve JavaScript console messages, warnings, and errors from the current browser page.",
        "parameters": {
            "level": "Log level filter: 'error', 'warning', or 'all'. Default is 'error'.",
        },
    },
    "browser_network_errors": {
        "description": "Retrieve failed network requests (HTTP 4xx/5xx or dropped connections) from the current browser page.",
        "parameters": {},
    },
    "browser_click": {
        "description": "Click an element matching the specified CSS selector on the active browser page.",
        "parameters": {
            "selector": "CSS selector of the element to click.",
        },
    },
    "browser_type": {
        "description": "Type text into an input element matching the specified CSS selector on the active browser page.",
        "parameters": {
            "selector": "CSS selector of the target input.",
            "text": "Text content to type into the element.",
        },
    },
    "browser_wait_for": {
        "description": "Wait for an element matching the CSS selector to be visible and ready in the DOM.",
        "parameters": {
            "selector": "CSS selector to wait for.",
            "timeout": "Maximum seconds to wait (default 10.0).",
        },
    },
    "browser_scroll": {
        "description": "Scroll the active browser viewport up or down.",
        "parameters": {
            "direction": "Scroll direction: 'down' or 'up'. Default is 'down'.",
        },
    },
    "browser_close": {
        "description": "Close the active browser instance and release resources.",
        "parameters": {},
    },
    "screen_screenshot": {
        "description": "Capture a desktop screenshot of the primary display (opt-in, requires approval).",
        "parameters": {},
    },
    "mouse_click": {
        "description": "Move mouse and click desktop coordinates (opt-in, requires explicit approval).",
        "parameters": {
            "x": "X coordinate on the desktop screen.",
            "y": "Y coordinate on the desktop screen.",
            "button": "Mouse button: 'left', 'right', or 'middle'. Default is 'left'.",
            "clicks": "Number of clicks (default 1).",
        },
    },
    "keyboard_type": {
        "description": "Type text directly to the active desktop window (opt-in, requires explicit approval).",
        "parameters": {
            "text": "The string text to type.",
        },
    },
    "hotkey": {
        "description": "Press a desktop keyboard shortcut combination (opt-in, requires explicit approval).",
        "parameters": {
            "keys": "List of key names to press together (e.g. ['ctrl', 's'] or ['alt', 'f4']).",
        },
    },
    "open_app": {
        "description": "Launch a desktop application by name or path (opt-in, requires explicit approval).",
        "parameters": {
            "name": "Application name or path (e.g. 'notepad', 'calc').",
        },
    },
    "list_windows": {
        "description": "List open application window titles on the desktop.",
        "parameters": {},
    },
    "focus_window": {
        "description": "Bring an open window to the foreground by its title.",
        "parameters": {
            "title": "Title or partial title of the target window.",
        },
    },
}

OPENAI_HARNESS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Create a new file or edit an existing file in the workspace. To create a new file, set original to ''.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file inside the workspace (e.g. 'src/Calculator.java').",
                    },
                    "original": {
                        "type": "string",
                        "description": "The exact verbatim text snippet to replace in the file, or '' if creating a new file.",
                    },
                    "updated": {
                        "type": "string",
                        "description": "The complete replacement content for the file or snippet.",
                    },
                },
                "required": ["path", "original", "updated"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append text content to a staged or existing file without requiring verbatim original. Used for chunked large-file generation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file inside the workspace.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content chunk to append to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents from the workspace with optional pagination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file inside the workspace.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Line number to start reading from (1-indexed). Default 1.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read (default 250, max 500).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to directory inside workspace. Use '' or '.' for root.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Perform fast ripgrep/regex search across workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text pattern or regex to search for.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell or terminal command in the workspace directory (e.g. 'javac Calculator.java && java Calculator', 'pytest', 'npm test').",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact shell command line string to execute.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_test",
            "description": "Run the test suite or a specific test file/command in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Test command to execute (e.g. 'pytest', 'npm test', 'mvn test').",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tests",
            "description": "Discover all pytest test node IDs in the workspace without executing them (runs pytest --collect-only -q). Read-only.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_single_test",
            "description": "Run a single specific test by its pytest node ID (e.g. 'tests/test_foo.py::test_bar').",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_node_id": {
                        "type": "string",
                        "description": "The pytest node ID to run (e.g. tests/test_foo.py::test_bar)",
                    },
                },
                "required": ["test_node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Capture visual rendering screenshot of active HTML preview or application window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["preview", "app_window"],
                        "description": "Target rendering mode ('preview' for HTML or 'app_window' for desktop shell).",
                    },
                    "target": {
                        "type": "string",
                        "description": "Relative path to the HTML file or URL to preview.",
                    },
                    "question": {
                        "type": "string",
                        "description": "Visual question to analyze.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a clarifying multiple-choice or confirmation question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of options for user selection.",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "Persist a long-term user preference or project convention into .code-os/MEMORY.md.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The project fact, rule, or preference to remember.",
                    },
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_references",
            "description": "Find all code references for a given symbol in the workspace AST index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol name to find references for.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "go_to_definition",
            "description": "Locate definition location (file, line, column) for a given symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol name to locate definition for.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Get structured git diff of uncommitted workspace changes.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": "Open a URL in an isolated Playwright browser instance, returning page title and HTTP status code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Target URL to navigate to (e.g. 'http://localhost:3000').",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Capture visual screenshot of current browser page, returning PNG filepath and base64.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Optional custom filename for the screenshot.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_console_logs",
            "description": "Retrieve JavaScript console messages, warnings, and errors from current browser page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["error", "warning", "all"],
                        "description": "Log level filter: 'error', 'warning', or 'all'. Default is 'error'.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_network_errors",
            "description": "Retrieve failed network requests (HTTP 4xx/5xx or dropped connections) from browser.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element matching the specified CSS selector on active browser page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element to click.",
                    },
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into an input element matching the specified CSS selector on active browser page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of target input element.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text content to type.",
                    },
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait_for",
            "description": "Wait for an element matching CSS selector to be visible and ready in DOM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to wait for.",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Maximum seconds to wait (default 10.0).",
                    },
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll active browser viewport up or down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["down", "up"],
                        "description": "Scroll direction: 'down' or 'up'. Default is 'down'.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": "Close active browser instance and release resources.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_screenshot",
            "description": "Capture desktop screen of primary display (opt-in, requires approval).",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_click",
            "description": "Move mouse and click desktop coordinates (opt-in, requires explicit approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate on screen."},
                    "y": {"type": "integer", "description": "Y coordinate on screen."},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button."},
                    "clicks": {"type": "integer", "description": "Number of clicks."},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyboard_type",
            "description": "Type text directly to active desktop window (opt-in, requires explicit approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The string text to type."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hotkey",
            "description": "Press desktop keyboard shortcut combination (opt-in, requires explicit approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of key names to press together.",
                    },
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Launch desktop application by name or path (opt-in, requires explicit approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name or path."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "List open application window titles on desktop.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Bring an open window to foreground by its title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of window to focus."},
                },
                "required": ["title"],
            },
        },
    },
]

def _is_command_malicious(command: str) -> bool:
    """Detect injection / remote code execution payloads in terminal commands."""
    cmd_strip = command.strip()
    return any(re.search(pattern, cmd_strip, re.IGNORECASE) for pattern in MALICIOUS_COMMAND_PATTERNS)


def _is_command_safe(command: str, workspace: str = "") -> bool:
    """Check if a terminal command is on the strict safe allowlist and path-contained.

    Returns True ONLY for commands explicitly allowlisted and operating within workspace.
    Everything else returns False (fail closed).
    """
    cmd = command.strip()
    if not cmd:
        return False

    # Reject compound operators (pipes, chains, redirects, subshells)
    if any(op in cmd for op in ("|", "&&", "||", ";", ">", ">>", "<", "`", "$(")):
        return False

    cmd_lower = cmd.lower()
    # Exact match
    if cmd_lower in SAFE_COMMAND_ALLOWLIST:
        return True

    # Prefix match
    is_allowlisted_prefix = False
    for prefix in SAFE_COMMAND_PREFIXES:
        if cmd_lower.startswith(prefix):
            is_allowlisted_prefix = True
            break

    if not is_allowlisted_prefix:
        return False

    # Path argument containment verification for commands with path args
    if workspace:
        file_cmd_prefixes = ("cat ", "type ", "ls ", "dir ", "head ", "tail ", "grep ", "findstr ")
        if any(cmd_lower.startswith(pfx) for pfx in file_cmd_prefixes):
            args = cmd.split()[1:]
            for raw_arg in args:
                arg = raw_arg.strip().strip("\"'")
                if not arg or arg.startswith("-"):
                    continue
                # Explicitly reject absolute paths, drive letters, and parent traversals
                if arg.startswith("/") or arg.startswith("\\") or (len(arg) >= 2 and arg[1] == ":") or ".." in arg.replace("\\", "/").split("/"):
                    return False
                try:
                    target_path = Path(workspace) / arg
                    if not ensure_within_workspace(workspace, str(target_path)):
                        return False
                except Exception:
                    return False
        else:
            parts = cmd.split(maxsplit=1)
            if len(parts) > 1:
                arg = parts[1].strip().strip("\"'")
                if not arg.startswith("-"):  # skip flags like -la
                    try:
                        target_path = Path(arg)
                        if target_path.is_absolute():
                            norm_ws = normalize_workspace(workspace)
                            try:
                                target_path.resolve().relative_to(norm_ws.resolve())
                            except ValueError:
                                return False
                        elif ".." in arg.replace("\\", "/").split("/"):
                            ensure_within_workspace(workspace, arg)
                    except Exception:
                        return False

    return True


def _read_file_cached(full_path: Path) -> str:
    """Read file content, reusing cached result if file mtime hasn't changed."""
    str_path = str(full_path.resolve())
    try:
        mtime = full_path.stat().st_mtime
    except Exception:
        mtime = 0.0
    cached = _file_read_cache.get(str_path)
    if cached and cached[0] == mtime:
        return cached[1]
    content = full_path.read_text(encoding="utf-8", errors="replace")
    if len(_file_read_cache) >= 1000:
        _file_read_cache.pop(next(iter(_file_read_cache)), None)
    _file_read_cache[str_path] = (mtime, content)
    return content


def _load_project_memory(workspace: str) -> str:
    """Load persistent user preferences & project conventions from RONY.md."""
    try:
        if not workspace:
            return ""
        p = Path(workspace) / "RONY.md"
        if p.is_file():
            content = p.read_text(encoding="utf-8", errors="replace").strip()
            return content[:PROJECT_MEMORY_MAX_CHARS]
    except Exception as exc:
        logger.warning("chat_harness: failed to load RONY.md: %s", exc)
    return ""


def _handle_memory_write(workspace: str, arguments: dict) -> tuple[bool, str]:
    """Append a user-stated preference or project convention to RONY.md."""
    fact = arguments.get("fact") or arguments.get("memory") or arguments.get("content") or ""
    if not fact or not str(fact).strip():
        return False, "Parameter 'fact' cannot be empty"
    try:
        p = Path(workspace) / "RONY.md"
        fact_str = str(fact).strip()
        if fact_str.startswith(("- ", "* ")):
            fact_str = fact_str[2:].strip()

        raw_existing = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "# Project Memory (RONY.md)\n\n"
        lines = [line.rstrip() for line in raw_existing.splitlines()]

        # Separate headers from bullets
        header_lines = [l for l in lines if not l.strip().startswith(("-", "*"))]
        if not header_lines:
            header_lines = ["# Project Memory (RONY.md)"]

        bullet_lines = [l for l in lines if l.strip().startswith(("-", "*"))]

        # Deduplication check
        existing_facts = {l.strip().lstrip("-* ").strip().lower() for l in bullet_lines}
        if fact_str.lower() not in existing_facts:
            bullet_lines.append(f"- {fact_str}")

        # Cap at 50 bullets
        if len(bullet_lines) > 50:
            bullet_lines = bullet_lines[-50:]

        content_parts = header_lines + [""] + bullet_lines
        final_content = "\n".join(content_parts).strip() + "\n"
        p.write_text(final_content, encoding="utf-8")
        return True, f"Saved to project memory: '{fact_str}'"
    except Exception as exc:
        return False, f"Failed to update RONY.md: {exc}"


def _find_mismatch_context(current_content: str, original: str) -> str:
    """Find the first differing line between the expected original and the file on disk."""
    curr_lines = current_content.splitlines()
    orig_lines = original.splitlines()
    if not orig_lines:
        return "Original snippet is empty."
    
    first_orig_line = orig_lines[0].strip()
    candidate_indices = [i for i, line in enumerate(curr_lines) if first_orig_line in line]
    
    if not candidate_indices:
        close_matches = difflib.get_close_matches(first_orig_line, curr_lines, n=1, cutoff=0.6)
        if close_matches:
            match_line = close_matches[0]
            line_no = curr_lines.index(match_line) + 1
            return (
                f"First differing line at line {line_no}:\n"
                f"Line 1 of original snippet was not found verbatim.\n"
                f"Closest matching line in file is line {line_no}:\n"
                f"  Actual:   '{match_line}'\n"
                f"  Expected: '{orig_lines[0]}'"
            )
        else:
            return f"First line of original snippet was not found anywhere in the file:\n  Expected: '{orig_lines[0]}'"

    best_match_idx = candidate_indices[0]
    mismatch_rel_idx = 0
    for rel_idx, o_line in enumerate(orig_lines):
        target_file_idx = best_match_idx + rel_idx
        if target_file_idx >= len(curr_lines):
            return (
                f"Mismatch at snippet line {rel_idx + 1}: expected file content beyond end-of-file.\n"
                f"  Expected: '{o_line}'"
            )
        c_line = curr_lines[target_file_idx]
        if c_line != o_line:
            mismatch_rel_idx = rel_idx
            line_no = target_file_idx + 1
            start_ctx = max(0, line_no - 3)
            end_ctx = min(len(curr_lines), line_no + 2)
            context_lines = [
                f"  {'>>' if i == line_no - 1 else '  '} Line {i+1}: {curr_lines[i]}"
                for i in range(start_ctx, end_ctx)
            ]
            return (
                f"First differing line at line {line_no}:\n"
                f"First mismatch at snippet line {mismatch_rel_idx + 1} (File line {line_no}):\n"
                f"  Expected snippet line: '{o_line}'\n"
                f"  Actual file line:      '{c_line}'\n"
                f"Surrounding file context:\n" + "\n".join(context_lines)
            )

    return "Whitespace or formatting divergence prevented exact verbatim replacement."


def _should_audit_staged_changes(staged_changes: list[FileChange], user_query: str) -> bool:
    """Determine if staged changes require structural quality auditing (generation/creation tasks)."""
    if not staged_changes:
        return False
    if any(c.original == "" for c in staged_changes):
        return True
    q_lower = user_query.lower()
    return any(term in q_lower for term in ("build", "create", "generate", "write", "portfolio", "html", "website", "app", "make", "new file"))


def _validate_smart_edit(
    workspace: str,
    arguments: dict,
) -> tuple[bool, str, FileChange | None]:
    """Pre-validate edit_file arguments before creating a proposal."""
    path = arguments.get("path")
    original = arguments.get("original", "")
    updated = arguments.get("updated")
    
    if not path or updated is None:
        return False, "Missing required parameters: 'path' and 'updated' are mandatory", None
    
    try:
        clean_path = _clean_rel_path(path)
        full_path = ensure_within_workspace(workspace, clean_path)
    except Exception as exc:
        return False, f"Invalid file path: {exc}", None

    if not original:
        return True, "", FileChange(path=clean_path, original="", updated=updated)

    if not full_path.is_file():
        return False, f"File does not exist: '{clean_path}'. To create a new file, pass original=''", None

    current_content = _read_file_cached(full_path)
    if original not in current_content:
        diagnostic = _find_mismatch_context(current_content, original)
        err_msg = (
            f"Exact-match pre-validation failed for '{clean_path}'. "
            f"The 'original' snippet does not match verbatim in the existing file.\n"
            f"[Mismatch Diagnostic]:\n{diagnostic}\n\n"
            "Action Required: Use `read_file` to inspect the latest file content and supply the exact matching lines."
        )
        return False, err_msg, None

    return True, "", FileChange(path=clean_path, original=original, updated=updated)


def _handle_append_file(
    workspace: str,
    arguments: dict,
    staged_changes: list[FileChange],
) -> tuple[bool, str, FileChange | None]:
    """Append content chunk to a staged or existing file."""
    path = arguments.get("path")
    content = arguments.get("content") or arguments.get("updated") or ""
    
    if not path:
        return False, "Missing required parameter: 'path' is mandatory", None
    if content is None:
        return False, "Missing required parameter: 'content' is mandatory", None
    
    try:
        clean_path = _clean_rel_path(path)
        full_path = ensure_within_workspace(workspace, clean_path)
    except Exception as exc:
        return False, f"Invalid file path: {exc}", None

    existing_staged = next((c for c in staged_changes if c.path == clean_path), None)
    if existing_staged:
        existing_staged.updated += ("\n" if existing_staged.updated and not existing_staged.updated.endswith("\n") else "") + content
        return True, "", existing_staged

    if full_path.is_file():
        current_content = _read_file_cached(full_path)
        new_content = current_content + ("\n" if current_content and not current_content.endswith("\n") else "") + content
        change = FileChange(path=clean_path, original=current_content, updated=new_content)
        staged_changes.append(change)
        return True, "", change

    change = FileChange(path=clean_path, original="", updated=content)
    staged_changes.append(change)
    return True, "", change


def _handle_list_tests(workspace: str, arguments: dict | None = None) -> ToolResult:
    """Discover pytest test node IDs in the workspace (runs pytest --collect-only -q). Read-only, no approval needed."""
    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        cmd = ["python", "-m", "pytest", "--collect-only", "-q"]
        proc = subprocess.run(
            cmd,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=20.0,
        )
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

        node_ids: list[str] = []
        for line in raw_output.splitlines():
            line_str = line.strip()
            if "::" in line_str and not line_str.startswith("="):
                node_ids.append(line_str)

        total_count = len(node_ids)
        if total_count == 0:
            if proc.returncode != 0 and ("error" in raw_output.lower() or "exception" in raw_output.lower()):
                return ToolResult(
                    tool_name="list_tests",
                    success=False,
                    output="",
                    error=f"Test collection failed (exit code {proc.returncode}):\n{raw_output[:500]}",
                )
            return ToolResult(
                tool_name="list_tests",
                success=True,
                output="No tests collected in workspace (pytest found 0 tests).",
            )

        capped_nodes = node_ids[:50]
        header = f"=== COLLECTED TESTS ({total_count} total" + (f", showing first {len(capped_nodes)}" if total_count > 50 else "") + ") ==="
        body = "\n".join(capped_nodes)
        if total_count > 50:
            body += f"\n... and {total_count - 50} more tests"

        return ToolResult(
            tool_name="list_tests",
            success=True,
            output=f"{header}\n{body}",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool_name="list_tests", success=False, output="", error="pytest --collect-only timed out after 20s")
    except Exception as exc:
        return ToolResult(tool_name="list_tests", success=False, output="", error=f"Failed to list tests: {exc}")


def _handle_run_single_test(workspace: str, arguments: dict) -> ToolResult:
    """Run a single targeted pytest test by its node ID (e.g. tests/test_parser.py::test_empty_input)."""
    node_id = arguments.get("node_id", "") or arguments.get("test", "") or arguments.get("test_id", "")
    if not node_id or not str(node_id).strip():
        return ToolResult(tool_name="run_single_test", success=False, output="", error="Missing required parameter: node_id")

    node_id_clean = str(node_id).strip().strip("\"'")
    if any(ch in node_id_clean for ch in [";", "&", "|", "`", "$", "<", ">", "\n", "\r"]):
        return ToolResult(tool_name="run_single_test", success=False, output="", error=f"Invalid node_id: '{node_id_clean}'")

    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        cmd = ["python", "-m", "pytest", node_id_clean, "-q"]
        proc = subprocess.run(
            cmd,
            cwd=str(norm_ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        raw_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        status_str = "PASSED" if proc.returncode == 0 else f"FAILED (exit code {proc.returncode})"

        if proc.returncode == 0:
            summary = f"1 test passed: {node_id_clean}"
            lines = [l.strip() for l in raw_output.splitlines() if "passed" in l.lower() or "===" in l]
            if lines:
                summary += f" ({lines[-1]})"
        else:
            summary = summarize_test_output(raw_output, max_chars=1200)

        return ToolResult(
            tool_name="run_single_test",
            success=True,
            output=f"=== TEST RUN: pytest {node_id_clean} [{status_str}] ===\n{summary}",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool_name="run_single_test", success=False, output="", error=f"Test timed out after 30s: {node_id_clean}")
    except Exception as exc:
        return ToolResult(tool_name="run_single_test", success=False, output="", error=f"Execution error: {exc}")

async def handle_rate_limit_or_circuit_break(job_id: str, task_id: str, exc: Exception) -> bool:
    """
    Detects 429 rate limit or open circuit breaker errors and transitions the task/job
    to 'paused' status instead of 'failed'.
    """
    from ..provider_health import CircuitOpenError, RateLimitError
    from ..job_service import pause_job, add_job_log

    is_rate_limit = isinstance(exc, RateLimitError) or "429" in str(exc) or "rate limit" in str(exc).lower()
    is_circuit_open = isinstance(exc, CircuitOpenError) or "circuit" in str(exc).lower() and "open" in str(exc).lower()
    is_disk_full = (isinstance(exc, OSError) and (getattr(exc, "errno", None) == 28 or "space" in str(exc).lower())) or "disk full" in str(exc).lower()

    if is_rate_limit or is_circuit_open or is_disk_full:
        retry_after = getattr(exc, "retry_after", 60.0)
        if is_disk_full:
            pause_reason = f"Disk full: {exc}"
        else:
            pause_reason = f"Provider rate limit or circuit open: {exc}"
        await pause_job(job_id, pause_reason, retry_after=retry_after)
        await add_job_log(job_id, f"[PAUSED] Task paused due to {pause_reason}. Retry after: {retry_after}s.")
        return True

    return False

from dataclasses import dataclass, asdict

@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "data": self.data or {},
        }


async def execute_tool_idempotent(
    task_id: str,
    job_id: str,
    step_num: int,
    tool_name: str,
    tool_args: dict,
    executor_fn: Optional[Any] = None,
) -> ToolResult:
    """Execute a tool with hash-based idempotency check and write-ahead logging."""
    import hashlib
    import asyncio
    step_id = f"step_{task_id}_{step_num}"
    payload = {"tool": tool_name, "args": tool_args}
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    
    from app.db.database import get_pool
    pool = await get_pool()
    
    # 1. Check if this exact step was already completed in task_steps
    rows = await pool.read_query(
        "SELECT result_json FROM task_steps WHERE task_id = ? AND payload_hash = ? AND status = 'completed'",
        (task_id, payload_hash)
    )
    if rows and rows[0]["result_json"]:
        logger.info("Step %d for task %s already completed, returning cached result", step_num, task_id)
        try:
            res_dict = json.loads(rows[0]["result_json"])
            return ToolResult(
                success=res_dict.get("success", True),
                output=res_dict.get("output", ""),
                error=res_dict.get("error", ""),
                data=res_dict.get("data", {}),
            )
        except Exception:
            pass

    # 2. Write-ahead log: pending -> running
    from ..step_tracker import log_step_pending, mark_step_running, mark_step_completed, mark_step_failed
    await log_step_pending(task_id, job_id, step_num, "tool_call", payload)
    await mark_step_running(step_id)

    try:
        if executor_fn is not None:
            if asyncio.iscoroutinefunction(executor_fn):
                raw_res = await executor_fn(tool_name, tool_args)
            else:
                raw_res = executor_fn(tool_name, tool_args)
        else:
            raw_res = ToolResult(success=True, output=f"Executed {tool_name} successfully", data=tool_args)

        if isinstance(raw_res, ToolResult):
            result = raw_res
        elif isinstance(raw_res, dict):
            result = ToolResult(
                success=raw_res.get("success", True),
                output=raw_res.get("output", str(raw_res)),
                error=raw_res.get("error", ""),
                data=raw_res,
            )
        else:
            result = ToolResult(success=True, output=str(raw_res))

        await mark_step_completed(step_id, result.to_dict())
        return result
    except Exception as exc:
        await mark_step_failed(step_id, str(exc))
        # Check if rate limit or circuit break to pause task gracefully
        await handle_rate_limit_or_circuit_break(job_id, task_id, exc)
        raise
