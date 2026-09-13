"""
agentic_terminal_service.py — Real-time Agentic Terminal Service.

Provides:
- In-memory terminal session management per job_id and workspace
- Subprocess execution with live line-by-line stdout/stderr streaming
- Server-Sent Events (SSE) broadcasting with replay buffer:
    * input: agent typing command
    * output: stdout/stderr line streaming
    * exit: exit code and duration
- Process tracking integration with process_tracker (Phase 3A) for orphan reaping
- 300s timeout enforcement and signal handling (SIGINT/SIGTERM)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.core.paths import normalize_path
from app.features.process_tracker import track_spawned_process, untrack_process

logger = logging.getLogger(__name__)

# Terminal session storage: terminal_id -> session dict
_TERMINAL_SESSIONS: Dict[str, Dict[str, Any]] = {}

# Event queues for SSE streaming: terminal_id -> list[asyncio.Queue]
_EVENT_QUEUES: Dict[str, List[asyncio.Queue]] = {}

# Running processes: terminal_id -> asyncio.subprocess.Process
_ACTIVE_PROCESSES: Dict[str, asyncio.subprocess.Process] = {}

# Max execution timeout (seconds)
COMMAND_TIMEOUT_SECONDS = 300.0

# A process signal must never leave a terminal request waiting indefinitely for
# asyncio's subprocess transport to observe the exit.
PROCESS_EXIT_GRACE_SECONDS = 2.0

# Reader tasks and stop events are kept separately from the public process map
# so close/signal paths can reliably finish an in-flight execute_command call.
_READER_TASKS: Dict[str, List[asyncio.Task]] = {}
_PROCESS_STOP_EVENTS: Dict[str, asyncio.Event] = {}


def create_session(job_id: str, workspace: str) -> str:
    """Create a new agentic terminal session."""
    terminal_id = f"term_{uuid.uuid4().hex[:12]}"
    norm_ws = str(normalize_path(workspace))

    session = {
        "terminal_id": terminal_id,
        "job_id": job_id,
        "workspace": norm_ws,
        "status": "idle",
        "created_at": time.time(),
        "history": [],
        "recent_events": [],
    }

    _TERMINAL_SESSIONS[terminal_id] = session
    _EVENT_QUEUES[terminal_id] = []
    logger.info("Created agentic terminal session %s for job %s in %s", terminal_id, job_id, norm_ws)
    return terminal_id


def get_session(terminal_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve session details by terminal_id."""
    return _TERMINAL_SESSIONS.get(terminal_id)


def get_active_session_for_workspace(workspace: str) -> Optional[Dict[str, Any]]:
    """Return the most recently created active session for a workspace, if any."""
    norm_ws = str(normalize_path(workspace))
    for session in reversed(list(_TERMINAL_SESSIONS.values())):
        if session.get("workspace") == norm_ws and session.get("status") != "closed":
            return session
    return None


def get_active_session_for_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return the active session for a specific job_id, if any."""
    for session in reversed(list(_TERMINAL_SESSIONS.values())):
        if session.get("job_id") == job_id and session.get("status") != "closed":
            return session
    return None


def list_active_sessions() -> List[Dict[str, Any]]:
    """List all non-closed terminal sessions."""
    return [s for s in _TERMINAL_SESSIONS.values() if s.get("status") != "closed"]


def clear_all_sessions() -> None:
    """Clear all sessions (for tests)."""
    _TERMINAL_SESSIONS.clear()
    _EVENT_QUEUES.clear()
    _ACTIVE_PROCESSES.clear()
    _READER_TASKS.clear()
    _PROCESS_STOP_EVENTS.clear()


async def close_session(terminal_id: str) -> bool:
    """Close terminal session, kill any active process, and cleanup queues."""
    session = _TERMINAL_SESSIONS.get(terminal_id)
    if not session:
        return False

    session["status"] = "closed"

    # Kill active process if still running
    proc = _ACTIVE_PROCESSES.get(terminal_id)
    stopping_process = bool(proc and proc.returncode is None)
    if stopping_process:
        try:
            await _kill_process_tree(proc)
        except Exception as exc:
            logger.warning("Error killing process for terminal %s: %s", terminal_id, exc)
        finally:
            stop_event = _PROCESS_STOP_EVENTS.get(terminal_id)
            if stop_event:
                stop_event.set()

    await _cancel_and_wait_reader_tasks(
        terminal_id,
        drain=not stopping_process,
    )
    _ACTIVE_PROCESSES.pop(terminal_id, None)

    # Notify listeners that session is closed
    await _broadcast_event(terminal_id, {"type": "session_closed", "terminal_id": terminal_id})

    _EVENT_QUEUES.pop(terminal_id, None)
    return True


async def _broadcast_event(terminal_id: str, event: Dict[str, Any]) -> None:
    """Push event to all active subscriber queues for this terminal and buffer it."""
    session = _TERMINAL_SESSIONS.get(terminal_id)
    if session:
        recent = session.setdefault("recent_events", [])
        recent.append(event)
        if len(recent) > 200:
            session["recent_events"] = recent[-100:]

    queues = _EVENT_QUEUES.get(terminal_id, [])
    for q in queues:
        try:
            q.put_nowait(event)
        except Exception:
            pass


async def execute_command(
    terminal_id: str,
    command: str,
    args: Optional[List[str]] = None,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Execute command in the terminal workspace, capturing stdout/stderr line-by-line
    and broadcasting SSE events in real-time.
    """
    session = _TERMINAL_SESSIONS.get(terminal_id)
    if not session:
        raise ValueError(f"Terminal session {terminal_id} not found")

    workspace = session["workspace"]
    import shlex
    import shutil
    import sys
    from app.features.terminal.service import _build_safe_environment

    # Build argv without unsanitized shell concatenation
    if args is not None:
        argv = [command] + [str(a) for a in args]
    else:
        try:
            argv = shlex.split(command)
        except Exception:
            argv = command.split()

    if not argv:
        return {
            "stdout": "",
            "stderr": "Empty command",
            "exit_code": 1,
            "duration_ms": 0,
        }

    display_cmd = " ".join(shlex.quote(a) for a in argv)
    full_cmd = display_cmd
    session["status"] = "running"

    t0 = time.perf_counter()
    # 1. Emit input event (agent typing command)
    input_event = {
        "type": "input",
        "command": full_cmd,
        "timestamp": time.time(),
    }
    await _broadcast_event(terminal_id, input_event)

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []
    exit_code: Optional[int] = None
    proc: Optional[asyncio.subprocess.Process] = None
    reader_tasks: List[asyncio.Task] = []
    stop_event = _PROCESS_STOP_EVENTS.setdefault(terminal_id, asyncio.Event())

    # Handle built-ins or emulate printenv/echo if not installed natively
    exec_argv = list(argv)
    cmd_name = exec_argv[0].lower()
    if cmd_name in ("python", "python3", "py"):
        exec_argv[0] = sys.executable
    elif cmd_name == "printenv" and not shutil.which("printenv"):
        exec_argv = [
            sys.executable,
            "-c",
            "import os, sys\n"
            "if len(sys.argv) > 1:\n"
            "    v = os.environ.get(sys.argv[1])\n"
            "    if v is not None: print(v)\n"
            "else:\n"
            "    for k, v in sorted(os.environ.items()):\n"
            "        print(f'{k}={v}')\n"
        ] + exec_argv[1:]
    elif cmd_name == "echo" and not shutil.which("echo"):
        exec_argv = [
            sys.executable,
            "-c",
            "import sys; print(' '.join(sys.argv[1:]))"
        ] + exec_argv[1:]
    else:
        which_path = shutil.which(exec_argv[0])
        if which_path:
            exec_argv[0] = which_path

    try:
        # Spawn subprocess with sanitized environment (prevent secret / API key leaks)
        safe_env = _build_safe_environment()
        spawn_kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            # Isolate the command in a process group. taskkill /T below then
            # tears down the complete tree without touching unrelated jobs.
            spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = await asyncio.create_subprocess_exec(
            *exec_argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            env=safe_env,
            **spawn_kwargs,
        )
        _ACTIVE_PROCESSES[terminal_id] = proc

        # Register child PID with Phase 3A process_tracker (with short timeout so DB lock never stalls)
        if proc.pid:
            try:
                await asyncio.wait_for(track_spawned_process(proc.pid, "agentic_terminal", workspace), timeout=0.5)
            except Exception as e:
                logger.warning("Failed to track process %s: %s", proc.pid, e)

        async def read_stream(stream: Optional[asyncio.StreamReader], stream_name: str, accumulator: List[str]):
            if not stream:
                return
            try:
                while True:
                    line_bytes = await stream.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                    accumulator.append(line)
                    # Broadcast output line
                    out_event = {
                        "type": "output",
                        "line": line,
                        "stream": stream_name,
                        "timestamp": time.time(),
                    }
                    await _broadcast_event(terminal_id, out_event)
            except asyncio.CancelledError:
                pass

        # Run stdout/stderr reader tasks with timeout
        stdout_task = asyncio.create_task(read_stream(proc.stdout, "stdout", stdout_lines))
        stderr_task = asyncio.create_task(read_stream(proc.stderr, "stderr", stderr_lines))
        reader_tasks = [stdout_task, stderr_task]
        _READER_TASKS[terminal_id] = reader_tasks

        process_wait_task = asyncio.create_task(proc.wait())
        stop_wait_task = asyncio.create_task(stop_event.wait())

        try:
            done, _ = await asyncio.wait_for(
                asyncio.wait(
                    {process_wait_task, stop_wait_task},
                    return_when=asyncio.FIRST_COMPLETED,
                ),
                timeout=timeout,
            )
            if stop_wait_task in done and proc.returncode is None:
                exit_code = -1
            else:
                exit_code = proc.returncode if proc.returncode is not None else 0
        except asyncio.TimeoutError:
            logger.warning("Command '%s' timed out after %ss in terminal %s", full_cmd, timeout, terminal_id)
            # Auto-kill hung process tree
            await _kill_process_tree(proc)
            stop_event.set()
            exit_code = -1
            timeout_msg = f"Command timed out after {timeout}s"
            stderr_lines.append(timeout_msg)
            await _broadcast_event(terminal_id, {
                "type": "output",
                "line": timeout_msg,
                "stream": "stderr",
                "timestamp": time.time(),
            })
        finally:
            for wait_task in (process_wait_task, stop_wait_task):
                if not wait_task.done():
                    wait_task.cancel()
            await asyncio.gather(process_wait_task, stop_wait_task, return_exceptions=True)

    except Exception as exc:
        logger.error("Error executing command in terminal %s: %s", terminal_id, exc)
        exit_code = 1
        err_msg = str(exc)
        stderr_lines.append(err_msg)
        await _broadcast_event(terminal_id, {
            "type": "output",
            "line": err_msg,
            "stream": "stderr",
            "timestamp": time.time(),
        })
    finally:
        await _cancel_and_wait_reader_tasks(
            terminal_id,
            reader_tasks,
            drain=not stop_event.is_set(),
        )
        if proc and proc.pid:
            try:
                await asyncio.wait_for(untrack_process(proc.pid), timeout=0.5)
            except Exception:
                pass
        if _ACTIVE_PROCESSES.get(terminal_id) is proc:
            _ACTIVE_PROCESSES.pop(terminal_id, None)
        if _PROCESS_STOP_EVENTS.get(terminal_id) is stop_event:
            _PROCESS_STOP_EVENTS.pop(terminal_id, None)
        if session.get("status") != "closed":
            session["status"] = "idle"

    duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    # 3. Emit exit event
    exit_event = {
        "type": "exit",
        "code": exit_code if exit_code is not None else 0,
        "duration_ms": duration_ms,
        "timestamp": time.time(),
    }
    await _broadcast_event(terminal_id, exit_event)

    # Record in history
    history_entry = {
        "command": full_cmd,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "timestamp": time.time(),
    }
    session["history"].append(history_entry)

    return history_entry


async def _cancel_and_wait_reader_tasks(
    terminal_id: str,
    tasks: Optional[List[asyncio.Task]] = None,
    *,
    drain: bool = True,
) -> None:
    """Cancel and join stream readers so no subprocess gather can outlive a command."""
    reader_tasks = tasks if tasks is not None else _READER_TASKS.pop(terminal_id, [])
    if reader_tasks and drain:
        # A reaped process normally closes both pipes immediately. Let readers
        # consume that final data before cancellation, but never wait forever.
        try:
            await asyncio.wait_for(
                asyncio.gather(*reader_tasks, return_exceptions=True),
                timeout=PROCESS_EXIT_GRACE_SECONDS,
            )
        except asyncio.TimeoutError:
            pass
    for task in reader_tasks:
        task.cancel()
    if reader_tasks:
        await asyncio.gather(*reader_tasks, return_exceptions=True)
    if _READER_TASKS.get(terminal_id) is reader_tasks:
        _READER_TASKS.pop(terminal_id, None)


async def _wait_for_process_exit(proc: asyncio.subprocess.Process) -> bool:
    """Wait for asyncio's process transport with a bounded timeout."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=PROCESS_EXIT_GRACE_SECONDS)
        return True
    except asyncio.TimeoutError:
        return False


async def _taskkill_process_tree(pid: int) -> None:
    """Run taskkill asynchronously so the event loop can reconcile proc.wait()."""
    taskkill = await asyncio.create_subprocess_exec(
        "taskkill",
        "/F",
        "/T",
        "/PID",
        str(pid),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(taskkill.wait(), timeout=PROCESS_EXIT_GRACE_SECONDS)
    except asyncio.TimeoutError:
        taskkill.kill()
        await asyncio.gather(taskkill.wait(), return_exceptions=True)


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a process tree and bound both exit observation and escalation."""
    if proc.returncode is not None:
        return

    try:
        if os.name == "nt" and proc.pid:
            await _taskkill_process_tree(proc.pid)
        else:
            proc.terminate()
    except (ProcessLookupError, FileNotFoundError):
        pass
    except Exception as exc:
        logger.debug("Failed to terminate process tree for PID %s: %s", getattr(proc, "pid", None), exc)

    if await _wait_for_process_exit(proc):
        return

    # Record the one permitted escalation. On Windows the first taskkill has
    # already terminated descendants; kill() forces asyncio to reconcile the
    # tracked root process if its transport did not observe that exit.
    logger.warning(
        "Process PID %s did not exit within %.1fs; escalating once",
        getattr(proc, "pid", None),
        PROCESS_EXIT_GRACE_SECONDS,
    )
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    except Exception as exc:
        logger.debug("Failed to escalate kill for PID %s: %s", getattr(proc, "pid", None), exc)

    if not await _wait_for_process_exit(proc):
        logger.error(
            "Process PID %s remained unreaped after bounded termination",
            getattr(proc, "pid", None),
        )


async def send_signal(terminal_id: str, sig_name: str = "SIGINT") -> bool:
    """Send signal / terminate running process in terminal."""
    proc = _ACTIVE_PROCESSES.get(terminal_id)
    if not proc or proc.returncode is not None:
        return False

    try:
        await _kill_process_tree(proc)
        stop_event = _PROCESS_STOP_EVENTS.get(terminal_id)
        if stop_event:
            stop_event.set()
        logger.info("Terminated process PID %s in terminal %s", proc.pid, terminal_id)
        return True
    except ProcessLookupError:
        return False
    except Exception as exc:
        logger.warning("Failed to terminate process in terminal %s: %s", terminal_id, exc)
        return False


async def stream_output(terminal_id: str) -> AsyncGenerator[str, None]:
    """SSE generator yielding events for the terminal session."""
    session = _TERMINAL_SESSIONS.get(terminal_id)
    if not session:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Terminal {terminal_id} not found'})}\n\n"
        return

    queue: asyncio.Queue = asyncio.Queue()
    if terminal_id not in _EVENT_QUEUES:
        _EVENT_QUEUES[terminal_id] = []
    _EVENT_QUEUES[terminal_id].append(queue)

    # Send initial connection event
    yield f"data: {json.dumps({'type': 'connected', 'terminal_id': terminal_id, 'job_id': session.get('job_id')})}\n\n"

    # Send any recent buffered events for immediate synchronization
    for past_event in list(session.get("recent_events", [])):
        yield f"data: {json.dumps(past_event)}\n\n"

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "session_closed":
                    break
            except asyncio.TimeoutError:
                # Keep-alive heartbeat
                yield ": keep-alive\n\n"
    finally:
        if terminal_id in _EVENT_QUEUES and queue in _EVENT_QUEUES[terminal_id]:
            _EVENT_QUEUES[terminal_id].remove(queue)
