"""
server_manager.py — Background Server Session Manager for CODE OS.

Provides:
- Spawn background server processes (e.g., FastAPI, Express, Vite, Flask, Django)
- Port-binding detection via socket connection polling
- Standard I/O ring buffer capture
- HTTP dispatching (GET/POST/PUT/DELETE) directly to running servers
- Guaranteed process termination and orphan cleanup on exit
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

from ....core.paths import normalize_workspace
from ...terminal.service import _build_safe_environment
from ..agents.agent_tools import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ActiveServerSession:
    session_id: str
    command: str
    port: int
    process: subprocess.Popen
    workspace: str
    started_at: float
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)


_active_server_sessions: dict[str, ActiveServerSession] = {}


def _server_session_start(workspace: str, command: str, port: int, host: str = "127.0.0.1", timeout: float = 12.0) -> ToolResult:
    """Start a background server process, capture stdout/stderr, and wait for port binding."""
    if not command or not port:
        return ToolResult(tool_name="server_session", success=False, output="", error="Missing command or port")
    
    session_id = f"srv_{port}_{uuid.uuid4().hex[:6]}"
    norm_ws = normalize_workspace(workspace)
    env = _build_safe_environment()

    # SECURITY: restrict host to localhost only to prevent SSRF.
    _ALLOWED_HOSTS = frozenset({'127.0.0.1', 'localhost', '::1'})
    if host.lower() not in _ALLOWED_HOSTS:
        return ToolResult(
            tool_name='server_session',
            success=False,
            output='',
            error=f'Security violation: host {host!r} is not allowed. Only 127.0.0.1/localhost are permitted.',
        )

    # SECURITY: basic command safety — reject obviously destructive patterns.
    _DANGEROUS_PATTERNS = ('rm -rf', 'mkfs', 'dd if=', '> /dev/', 'chmod 777 /', ':(){:|:&};:')
    cmd_lower = command.strip().lower()
    if any(pat in cmd_lower for pat in _DANGEROUS_PATTERNS):
        return ToolResult(
            tool_name='server_session',
            success=False,
            output='',
            error=f'Security violation: command contains a dangerous pattern and was rejected.',
        )

    effective_command = command.strip()
    if os.name == "nt":
        if effective_command.startswith("pytest ") or effective_command == "pytest":
            effective_command = "python -m " + effective_command
        elif effective_command.startswith("python3 ") or effective_command == "python3":
            effective_command = "python " + effective_command[8:]
        args = ["powershell", "-NoLogo", "-NoProfile", "-Command", effective_command]
    else:
        args = ["bash", "-c", effective_command]

    try:
        proc = subprocess.Popen(
            args,
            cwd=str(norm_ws),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        session = ActiveServerSession(
            session_id=session_id,
            command=command,
            port=port,
            process=proc,
            workspace=workspace,
            started_at=time.time(),
        )

        def _read_stdout():
            if proc.stdout:
                for l in proc.stdout:
                    session.stdout_lines.append(l.rstrip())
                    if len(session.stdout_lines) > 200:
                        session.stdout_lines.pop(0)

        def _read_stderr():
            if proc.stderr:
                for l in proc.stderr:
                    session.stderr_lines.append(l.rstrip())
                    if len(session.stderr_lines) > 200:
                        session.stderr_lines.pop(0)

        threading.Thread(target=_read_stdout, daemon=True).start()
        threading.Thread(target=_read_stderr, daemon=True).start()

        _active_server_sessions[session_id] = session

        # Wait until port is open or process exits
        start_wait = time.time()
        bound = False
        while time.time() - start_wait < timeout:
            if proc.poll() is not None:
                err_snippet = "\n".join(session.stderr_lines[-10:])
                out_snippet = "\n".join(session.stdout_lines[-10:])
                _active_server_sessions.pop(session_id, None)
                return ToolResult(
                    tool_name="server_session",
                    success=False,
                    output="",
                    error=f"Server process terminated prematurely with code {proc.returncode}.\nOutput: {out_snippet}\nErrors: {err_snippet}"
                )
            try:
                with socket.create_connection((host, port), timeout=0.3):
                    bound = True
                    break
            except Exception:
                time.sleep(0.3)

        status_str = "BOUND & LISTENING" if bound else "STARTED (Port check timed out, process alive)"
        return ToolResult(
            tool_name="server_session",
            success=True,
            output=(
                f"=== SERVER SESSION STARTED ===\n"
                f"Session ID: {session_id}\n"
                f"Command: {command}\n"
                f"Port: {port} ({status_str})\n"
                f"PID: {proc.pid}\n"
                f"Status: active"
            )
        )
    except Exception as exc:
        return ToolResult(tool_name="server_session", success=False, output="", error=f"Failed to start server: {exc}")


def _server_session_request(
    workspace: str,
    session_id: str | None = None,
    port: int | None = None,
    method: str = "GET",
    path: str = "/",
    body: Any = None,
    headers: dict | None = None,
    timeout: float = 10.0,
) -> ToolResult:
    """Send HTTP request to a running server session and return response."""
    target_port = port
    if not target_port and session_id:
        sess = _active_server_sessions.get(session_id)
        if sess:
            target_port = sess.port

    if not target_port:
        return ToolResult(tool_name="server_session", success=False, output="", error="No port or active session_id specified")

    clean_path = "/" + path.lstrip("/")
    url = f"http://127.0.0.1:{target_port}{clean_path}"

    req_headers = headers.copy() if headers else {}
    req_data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            req_data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        else:
            req_data = str(body).encode("utf-8")

    req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method.upper())
    start_req = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            dur = (time.perf_counter() - start_req) * 1000.0
            raw_body = resp.read().decode("utf-8", errors="replace")
            status_code = resp.status
            try:
                formatted_body = json.dumps(json.loads(raw_body), indent=2)
            except Exception:
                formatted_body = raw_body

            out = (
                f"=== HTTP RESPONSE ({method.upper()} {clean_path}) ===\n"
                f"Status: {status_code} ({resp.reason})\n"
                f"Duration: {dur:.2f}ms\n"
                f"Body:\n{formatted_body[:2000]}"
            )
            return ToolResult(tool_name="server_session", success=True, output=out)
    except urllib.error.HTTPError as exc:
        dur = (time.perf_counter() - start_req) * 1000.0
        err_body = exc.read().decode("utf-8", errors="replace")
        out = (
            f"=== HTTP RESPONSE ({method.upper()} {clean_path}) ===\n"
            f"Status: {exc.code} ({exc.reason})\n"
            f"Duration: {dur:.2f}ms\n"
            f"Body:\n{err_body[:1000]}"
        )
        return ToolResult(tool_name="server_session", success=True, output=out)
    except Exception as exc:
        return ToolResult(tool_name="server_session", success=False, output="", error=f"Request to {url} failed: {exc}")


def _server_session_stop(session_id: str) -> ToolResult:
    """Stop and terminate a server session process."""
    if not session_id or session_id not in _active_server_sessions:
        return ToolResult(tool_name="server_session", success=False, output="", error=f"Session ID '{session_id}' not found or already stopped.")

    sess = _active_server_sessions.pop(session_id)
    try:
        proc = sess.process
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
        return ToolResult(tool_name="server_session", success=True, output=f"Server session '{session_id}' (port {sess.port}, command '{sess.command}') stopped cleanly.")
    except Exception as exc:
        return ToolResult(tool_name="server_session", success=False, output="", error=f"Failed to terminate server: {exc}")


def _server_session_list() -> ToolResult:
    """List all currently active server sessions."""
    if not _active_server_sessions:
        return ToolResult(tool_name="server_session", success=True, output="No active server sessions running.")
    lines = ["=== ACTIVE SERVER SESSIONS ==="]
    now = time.time()
    for sid, sess in _active_server_sessions.items():
        alive = sess.process.poll() is None
        lines.append(f"- ID: `{sid}` | Port: `{sess.port}` | Uptime: `{int(now - sess.started_at)}s` | Status: `{'running' if alive else 'exited'}` | Command: `{sess.command}`")
    return ToolResult(tool_name="server_session", success=True, output="\n".join(lines))


def _cleanup_server_sessions(workspace: str | None = None) -> int:
    """Clean up all active server sessions to guarantee no zombie processes remain."""
    stopped = 0
    for sid, sess in list(_active_server_sessions.items()):
        if not workspace or sess.workspace == workspace:
            _server_session_stop(sid)
            stopped += 1
    return stopped


def _handle_server_session(workspace: str, arguments: dict) -> ToolResult:
    """Dispatch server_session tool actions."""
    action = (arguments.get("action") or "start").lower().strip()
    if action == "start":
        cmd = arguments.get("command") or arguments.get("cmd") or ""
        port = int(arguments.get("port") or 8000)
        host = arguments.get("host") or "127.0.0.1"
        timeout = float(arguments.get("timeout") or 12.0)
        return _server_session_start(workspace, cmd, port, host, timeout)
    elif action in ("request", "req", "http"):
        sid = arguments.get("session_id")
        port = int(arguments["port"]) if arguments.get("port") else None
        method = arguments.get("method") or "GET"
        path = arguments.get("path") or "/"
        body = arguments.get("body")
        headers = arguments.get("headers")
        return _server_session_request(workspace, sid, port, method, path, body, headers)
    elif action == "stop":
        sid = arguments.get("session_id") or ""
        return _server_session_stop(sid)
    elif action in ("list", "status"):
        return _server_session_list()
    else:
        return ToolResult(tool_name="server_session", success=False, output="", error=f"Unknown server_session action: '{action}'. Use start, request, stop, or list.")


# Cleanup hook on Python interpreter exit
atexit.register(_cleanup_server_sessions)


class ServerSessionManager:
    """Class wrapper providing structured lifecycle management for background dev server sessions."""

    def __init__(self):
        pass

    def start(self, workspace: str, command: str, port: int, host: str = "127.0.0.1", timeout: float = 12.0) -> ToolResult:
        return _server_session_start(workspace, command, port, host, timeout)

    def request(
        self,
        workspace: str,
        session_id: str | None = None,
        port: int | None = None,
        method: str = "GET",
        path: str = "/",
        body: Any = None,
        headers: dict | None = None,
        timeout: float = 10.0,
    ) -> ToolResult:
        return _server_session_request(workspace, session_id, port, method, path, body, headers, timeout)

    def stop(self, session_id: str) -> ToolResult:
        return _server_session_stop(session_id)

    def list_active(self) -> ToolResult:
        return _server_session_list()

    def cleanup_all(self, workspace: str | None = None) -> int:
        return _cleanup_server_sessions(workspace)
