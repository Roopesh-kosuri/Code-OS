import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ...core.paths import normalize_path

logger = logging.getLogger(__name__)


@dataclass
class TerminalSession:
    id: str
    name: str
    cwd: str
    shell: str
    processes: list[asyncio.subprocess.Process]


sessions: dict[str, TerminalSession] = {}


def create_session(cwd: str, shell: str | None = None) -> TerminalSession:
    logger.info("terminal.create requested cwd=%s shell=%s", cwd, shell)
    cwd_path = normalize_path(cwd)
    if not cwd_path.is_dir():
        logger.error("terminal.create cwd not found cwd=%s", cwd_path)
        raise HTTPException(status_code=404, detail="Working directory not found")
    session = TerminalSession(
        id=str(uuid.uuid4()),
        name="Terminal",
        cwd=str(cwd_path),
        shell=shell or ("powershell" if os.name == "nt" else "bash"),
        processes=[],
    )
    sessions[session.id] = session
    logger.info("terminal.create session_id=%s cwd=%s", session.id, session.cwd)
    return session


# ---------------------------------------------------------------------------
# Environment allowlist for terminal subprocess execution.
#
# SECURITY: We use an ALLOWLIST (not a blacklist) to control which environment
# variables are passed to processes spawned by the terminal.  A blacklist is
# broken by design: pattern-matching on substrings like "key" would kill
# legitimate variables such as SSH_AUTH_SOCK, KEYBOARD_LAYOUT, GPG_KEY_ID,
# MONKEY_PATCH, etc.
#
# Only variables that are operationally necessary for a shell to function are
# forwarded.  Secrets (API keys, cloud credentials, database passwords, tokens)
# are never forwarded even if they happen to be present in the parent process.
# ---------------------------------------------------------------------------

# Variables passed through unconditionally (exact name, case-insensitive on
# Windows but exact-case on POSIX because Unix env vars are case-sensitive).
_ALLOWED_ENV_VARS: frozenset[str] = frozenset({
    # Shell / session identity
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "USERNAME",          # Windows equivalent of USER
    "USERPROFILE",       # Windows home directory
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_MESSAGES",
    "LC_CTYPE",
    "LANGUAGE",
    "TERM",
    "TERM_PROGRAM",
    "COLORTERM",
    "COLUMNS",
    "LINES",

    # SSH agent forwarding (the socket path is not a secret)
    "SSH_AUTH_SOCK",
    "SSH_AGENT_PID",

    # GPG agent
    "GPG_AGENT_INFO",

    # Python runtime
    "PYTHONPATH",
    "PYTHONIOENCODING",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",

    # Node/npm toolchain
    "NVM_DIR",
    "NODE_PATH",
    "NPM_CONFIG_PREFIX",

    # Rust toolchain
    "CARGO_HOME",
    "RUSTUP_HOME",

    # Go toolchain
    "GOPATH",
    "GOROOT",

    # Java
    "JAVA_HOME",

    # macOS specifics
    "TMPDIR",
    "XDG_RUNTIME_DIR",

    # Windows specifics
    "COMSPEC",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMDATA",
    "COMPUTERNAME",

    # Display / Wayland / X11
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_SESSION_TYPE",
    "DBUS_SESSION_BUS_ADDRESS",
})


def _build_safe_environment() -> dict[str, str]:
    """
    Return a copy of the environment containing ONLY the variables in
    _ALLOWED_ENV_VARS.  This prevents secrets (API keys, cloud credentials,
    tokens, passwords) from leaking into terminal subprocesses — including
    commands executed automatically by the AI agent.
    """
    safe: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _ALLOWED_ENV_VARS:
            safe[key] = value
    # Always inject a sane TERM value so TUI programs behave correctly.
    safe.setdefault("TERM", "xterm-256color")
    return safe


def _is_cd_command(command: str) -> bool:
    cmd_lower = command.strip().lower()
    return cmd_lower == "cd" or cmd_lower.startswith("cd ") or cmd_lower.startswith("cd\t")


def _sanitize_env(env_dict: dict[str, str] | None = None) -> dict[str, str]:
    if env_dict is None:
        env_dict = dict(os.environ)
    safe: dict[str, str] = {}
    for key, value in env_dict.items():
        if key in _ALLOWED_ENV_VARS:
            safe[key] = value
    safe.setdefault("TERM", "xterm-256color")
    return safe


# Keep the old name as an alias so call-sites don't need updating yet.
def _sanitize_environment() -> dict[str, str]:
    return _build_safe_environment()


async def run_command(session_id: str, command: str, background: bool) -> tuple[str, int | None, bool]:
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Terminal session not found")
    if not command.strip():
        return "", 0, False

    if _is_cd_command(command):
        return _change_directory(session, command, workspace_root=session.cwd)


    if os.name == "nt":
        args = [session.shell, "-NoLogo", "-NoProfile", "-Command", command]
    else:
        args = [session.shell, "-lc", command]

    sanitized_env = _sanitize_environment()
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=session.cwd,
        env=sanitized_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    session.processes.append(process)

    if background:
        return f"Started background process {process.pid}", None, True

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=60.0)
        return stdout.decode("utf-8", errors="replace"), process.returncode, False
    except asyncio.TimeoutError:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        return f"Command timed out after 60 seconds: {command}", 124, False



def _change_directory(session: TerminalSession, command: str, workspace_root: str | None = None) -> tuple[str, int | None, bool]:
    parts = command.strip().split(maxsplit=1)
    if len(parts) > 1:
        raw_target = parts[1].strip("\"'")
        target = raw_target if os.path.isabs(raw_target) else os.path.join(session.cwd, raw_target)
        # Do NOT call expanduser on client-supplied paths.
        next_dir = normalize_path(target)
    else:
        # bare 'cd' — in a sandboxed terminal we stay in the workspace root
        # rather than navigating to the user's home directory.
        if workspace_root:
            next_dir = normalize_path(workspace_root)
        else:
            next_dir = normalize_path(session.cwd)
    if not next_dir.is_dir():
        return f"Directory not found: {next_dir}", 1, False
    session.cwd = str(next_dir)
    return f"{session.cwd}", 0, False


def clear_session(session_id: str) -> None:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Terminal session not found")


def rename_session(session_id: str, name: str) -> TerminalSession:
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Terminal session not found")
    session.name = name.strip() or session.name
    return session


def kill_session(session_id: str) -> None:
    session = sessions.pop(session_id, None)
    if not session:
        raise HTTPException(status_code=404, detail="Terminal session not found")
    for process in session.processes:
        if process.returncode is None:
            process.kill()


def list_sessions() -> list[TerminalSession]:
    return list(sessions.values())
# ── Interactive PTY sessions for WebSocket fallback ───────────────────────
# Upgrade: Using a real PTY via pywinpty (Windows) or ptyprocess (Unix)
# to allow interactive CLI applications (vim, git, npm, etc.) in browser mode.

import queue
import sys
import threading
from typing import Optional

if sys.platform == "win32":
    import winpty
    PtyProcessClass = winpty.PtyProcess
else:
    import ptyprocess
    PtyProcessClass = ptyprocess.PtyProcess


def _resolve_shell_cmd() -> list[str]:
  """Return [executable] for the best available interactive shell."""
  import shutil
  if sys.platform == "win32":
    for candidate in ["pwsh.exe", "powershell.exe", "cmd.exe"]:
      if shutil.which(candidate):
        return [candidate]
    return ["cmd.exe"]
  # Unix
  shell = os.environ.get("SHELL", "/bin/bash")
  return [shell]


@dataclass
class PtySession:
  id: str
  cwd: str
  proc: Optional[Any] = field(default=None, repr=False)
  output_queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
  _reader_thread: Optional[threading.Thread] = field(default=None, repr=False)


pty_sessions: dict[str, PtySession] = {}


def _start_reader(session: PtySession) -> None:
  """Background thread: read stdout and push lines into the output queue."""
  assert session.proc
  try:
    while session.proc.isalive():
      chunk = session.proc.read(1024)
      if not chunk:
        break
      if isinstance(chunk, bytes):
        chunk = chunk.decode(errors="replace")
      session.output_queue.put(chunk)
  except EOFError:
    logger.debug("reader thread: EOF reached")
  except Exception as exc:
    logger.debug("reader thread exit: %s", exc)
  finally:
    session.output_queue.put(None)  # sentinel – stream ended


def _write_to_pty(proc: Any, data: str) -> None:
  """Write data to process stdin in platform-appropriate format."""
  if sys.platform == "win32":
    proc.write(data)
  else:
    proc.write(data.encode())
    try:
      proc.flush()
    except AttributeError:
      pass


def create_pty_session(cwd: str, session_id: str) -> PtySession:
  """Create and start a real PTY session (sync, thread-safe)."""
  cwd_path = normalize_path(cwd)
  if not cwd_path.is_dir():
    raise HTTPException(status_code=404, detail="Working directory not found")

  cmd = _resolve_shell_cmd()
  logger.info("terminal.ws.create session_id=%s shell=%s cwd=%s", session_id, cmd[0], cwd_path)

  # Spawn using the platform-specific PtyProcess class
  proc = PtyProcessClass.spawn(cmd, cwd=str(cwd_path))
  session = PtySession(id=session_id, cwd=str(cwd_path), proc=proc)
  t = threading.Thread(target=_start_reader, args=(session,), daemon=True)
  t.start()
  session._reader_thread = t
  pty_sessions[session_id] = session
  return session


def kill_pty_session(session_id: str) -> None:
  session = pty_sessions.pop(session_id, None)
  if session and session.proc:
    try:
      if session.proc.isalive():
        session.proc.close()
    except Exception as exc:
      logger.warning("Error closing PTY session %s: %s", session_id, exc)


async def handle_terminal_websocket(websocket: WebSocket) -> None:
  await websocket.accept()
  # The route handler guarantees cwd is present and trusted before calling us.
  cwd = websocket.query_params.get("cwd")
  if not cwd:
    await websocket.send_text("\r\n\x1b[31m[Internal error: no workspace path in WebSocket session.]\x1b[0m\r\n")
    await websocket.close()
    return
  session_id = websocket.query_params.get("session_id", f"ws-term-{uuid.uuid4()}")

  loop = asyncio.get_event_loop()

  try:
    # Spawn subprocess synchronously (no asyncio subprocess needed)
    session = await loop.run_in_executor(
      None, lambda: create_pty_session(cwd, session_id)
    )
  except HTTPException as exc:
    await websocket.send_text(f"\r\n\x1b[31m[Error: {exc.detail}]\x1b[0m\r\n")
    await websocket.close()
    return
  except Exception as exc:
    await websocket.send_text(f"\r\n\x1b[31m[Failed to start shell: {exc}]\x1b[0m\r\n")
    await websocket.close()
    return

  async def drain_output() -> None:
    """Forward subprocess output → WebSocket using a thread-safe queue."""
    while True:
      chunk: Optional[str] = await loop.run_in_executor(
        None, session.output_queue.get
      )
      if chunk is None:  # sentinel – process exited
        try:
          await websocket.send_text("\r\n\x1b[33m[Process exited]\x1b[0m\r\n")
        except Exception:
          pass
        break
      try:
        await websocket.send_text(chunk)
      except Exception:
        break

  drain_task = asyncio.create_task(drain_output())

  try:
    while True:
      try:
        raw = await websocket.receive_text()
      except WebSocketDisconnect:
        break
      except Exception as exc:
        logger.debug("ws receive error: %s", exc)
        break

      try:
        msg = json.loads(raw)
        if not isinstance(msg, dict):
          msg = {"type": "input", "data": raw}
      except Exception:
        msg = {"type": "input", "data": raw}


      if msg.get("type") == "input" and msg.get("data") and session.proc:
        try:
          _write_to_pty(session.proc, msg["data"])
        except Exception as exc:
          logger.debug("pty write error: %s", exc)
      elif msg.get("type") == "resize":
        rows = msg.get("rows")
        cols = msg.get("cols")
        if rows is not None and cols is not None and session.proc:
          try:
            session.proc.setwinsize(rows, cols)
          except Exception as exc:
            logger.debug("pty resize error: %s", exc)
  finally:
    drain_task.cancel()
    kill_pty_session(session_id)
