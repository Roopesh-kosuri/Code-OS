"""
executor.py — Multi-tier isolated execution engine for terminal commands in CODE OS.

Provides:
- Resource Governor (Memory cap: 512MB, CPU timeout: 60s)
- Host-async execution with safe environment variables
- Container Sandboxing (Docker / Alpine / WSL2) with strict fail-closed policy
- Windows Sandbox (.wsb) XML generation and launch isolation
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ....core.paths import normalize_workspace
from ....core.monitoring import monitor
from ...terminal.service import _build_safe_environment
from ..agents.agent_tools import ToolResult

logger = logging.getLogger(__name__)

# Resource governor constants
MAX_COMMAND_TIMEOUT_SECONDS = 60.0
MAX_COMMAND_MEMORY_BYTES = 512 * 1024 * 1024  # 512MB RAM cap


class SandboxUnavailableError(RuntimeError):
    """Raised when container sandbox execution is required but no container runtime is available."""
    pass


async def _monitor_process_governor(
    proc: asyncio.subprocess.Process,
    max_memory_bytes: int = MAX_COMMAND_MEMORY_BYTES,
    poll_interval: float = 0.05,
) -> tuple[bool, str]:
    """
    Actively monitors process and its children for memory usage.
    If RAM usage exceeds 512MB, aggressively kills the process tree and flags resource violation.
    """
    try:
        import psutil
        p = psutil.Process(proc.pid)
        while proc.returncode is None:
            try:
                # Sum memory of parent + all descendants
                total_mem = p.memory_info().rss
                for child in p.children(recursive=True):
                    try:
                        total_mem += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                if total_mem > max_memory_bytes:
                    try:
                        for child in p.children(recursive=True):
                            child.kill()
                        p.kill()
                    except Exception:
                        pass
                    return True, "Command exceeded resource limit (512MB memory / 60s CPU)"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            await asyncio.sleep(poll_interval)
    except ImportError:
        while proc.returncode is None:
            await asyncio.sleep(0.1)
    except Exception:
        pass
    return False, ""


def _detect_container_runtime() -> dict[str, Any]:
    """Detect presence of Docker and WSL2 on the host system."""
    docker_available = False
    docker_version = ""
    wsl_available = False
    wsl_distros: list[str] = []

    try:
        res = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0 and "Docker version" in res.stdout:
            docker_available = True
            docker_version = res.stdout.strip()
    except Exception:
        docker_available = False

    try:
        res = subprocess.run(["wsl", "--list"], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0:
            wsl_available = True
            wsl_distros = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        wsl_available = False

    return {
        "docker_available": docker_available,
        "docker_version": docker_version,
        "wsl_available": wsl_available,
        "wsl_distros": wsl_distros,
        "primary_runtime": "docker" if docker_available else ("wsl" if wsl_available else "native"),
    }


def _detect_windows_sandbox() -> bool:
    """Check if Windows Sandbox is enabled on the current Windows host."""
    if os.name != "nt":
        return False
    wsb_exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsSandbox.exe"
    return wsb_exe.is_file()


def _generate_wsb_config(workspace: str) -> str:
    """Generate .wsb configuration XML with mapped workspace folder."""
    norm_ws = str(Path(workspace).resolve())
    return f"""<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Disable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{norm_ws}</HostFolder>
      <SandboxFolder>C:\\Users\\WDAGUtilityAccount\\Desktop\\workspace</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell -ExecutionPolicy Bypass -Command "Write-Host 'CODE OS Untrusted Project Sandbox Initialized at Desktop\\workspace'"</Command>
  </LogonCommand>
</Configuration>
"""


def _launch_windows_sandbox(workspace: str) -> tuple[bool, str]:
    """Write .wsb file and launch Windows Sandbox."""
    if not _detect_windows_sandbox():
        return False, "Windows Sandbox (Containers-DisposableClientVMs) is not enabled or available on this system."
    try:
        wsb_dir = Path(workspace) / ".code_os"
        wsb_dir.mkdir(parents=True, exist_ok=True)
        wsb_file = wsb_dir / "untrusted_project.wsb"
        wsb_content = _generate_wsb_config(workspace)
        wsb_file.write_text(wsb_content, encoding="utf-8")

        subprocess.Popen(["WindowsSandbox.exe", str(wsb_file)])
        return True, f"Windows Sandbox launched with configuration `{wsb_file.name}`."
    except Exception as exc:
        return False, f"Failed to launch Windows Sandbox: {exc}"


async def _execute_command_async(
    workspace: str,
    command: str,
    timeout: float = MAX_COMMAND_TIMEOUT_SECONDS,
    max_output_chars: int = 3000,
) -> ToolResult:
    """Execute a single terminal command asynchronously on the host with Resource Governor."""
    start_t = time.time()
    try:
        norm_ws = normalize_workspace(workspace)
        env = _build_safe_environment()

        effective_command = command.strip()
        if os.name == "nt":
            if effective_command.startswith("pytest ") or effective_command == "pytest":
                effective_command = "python -m " + effective_command
            elif effective_command.startswith("python3 ") or effective_command == "python3":
                effective_command = "python " + effective_command[8:]
            args = ["powershell", "-NoLogo", "-NoProfile", "-Command", effective_command]
        else:
            args = ["bash", "-c", effective_command]

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(norm_ws),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        gov_task = asyncio.create_task(_monitor_process_governor(proc, max_memory_bytes=MAX_COMMAND_MEMORY_BYTES))
        communicate_task = asyncio.create_task(proc.communicate())

        limit_hit = False
        limit_msg = ""
        try:
            done, pending = await asyncio.wait(
                [communicate_task, gov_task],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if gov_task in done:
                limit_hit, limit_msg = gov_task.result()
                if limit_hit:
                    for t in pending:
                        t.cancel()
                    try:
                        if proc.returncode is None:
                            proc.kill()
                            await proc.wait()
                    except Exception:
                        pass
                    return ToolResult(
                        tool_name="run_command",
                        success=False,
                        output="",
                        error=json.dumps({"reason": "governor_kill", "detail": limit_msg, "command": command}),
                        failure_reason="governor_kill",
                        failure_detail=limit_msg,
                    )

            if communicate_task in done:
                stdout, stderr = communicate_task.result()
            else:
                for t in pending:
                    t.cancel()
                try:
                    import psutil
                    p = psutil.Process(proc.pid)
                    for child in p.children(recursive=True):
                        try:
                            child.kill()
                        except Exception:
                            pass
                    p.kill()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    pass
                exec_detail = f"Command ran {int(timeout)}s and was killed."
                return ToolResult(
                    tool_name="run_command",
                    success=False,
                    output="",
                    error=json.dumps({"reason": "execution_timeout", "detail": exec_detail, "command": command}),
                    failure_reason="execution_timeout",
                    failure_detail=exec_detail,
                )
        finally:
            if not gov_task.done():
                gov_task.cancel()

        raw_output = (stdout.decode("utf-8", errors="replace") or "") + \
                     ("\n" + stderr.decode("utf-8", errors="replace") if stderr else "")
        status_str = "SUCCESS" if proc.returncode == 0 else f"EXIT {proc.returncode}"

        if len(raw_output) > max_output_chars:
            raw_output = raw_output[:max_output_chars] + "\n... [Output truncated to preserve token efficiency]"

        dur_ms = (time.time() - start_t) * 1000.0
        monitor.record_metric("command_execution", dur_ms)

        if proc.returncode == 0:
            return ToolResult(
                tool_name="run_command",
                success=True,
                output=f"=== COMMAND: {command} [{status_str}] ===\n{raw_output.strip() or '(no output)'}",
                error="",
            )

        lower_out = raw_output.lower()
        is_not_found = (
            proc.returncode in (127, 9009)
            or "is not recognized as an internal or external command" in lower_out
            or "commandnotfoundexception" in lower_out
            or "cannot find the path" in lower_out
            or "no such file or directory" in lower_out
            or ": not found" in lower_out
            or ": command not found" in lower_out
        )
        fail_reason = "not_found" if is_not_found else "exit_code"
        fail_detail = (
            f"Command not found: {command}"
            if is_not_found
            else f"Process exited with code {proc.returncode}"
        )
        return ToolResult(
            tool_name="run_command",
            success=False,
            output=f"=== COMMAND: {command} [{status_str}] ===\n{raw_output.strip() or '(no output)'}",
            error=json.dumps({
                "reason": fail_reason,
                "detail": fail_detail,
                "exit_code": proc.returncode,
                "command": command,
                "output": raw_output.strip()[:500],
            }),
            failure_reason=fail_reason,
            failure_detail=fail_detail,
        )
    except Exception as exc:
        monitor.capture_exception(exc, context={"workspace": workspace, "command": command})
        is_fnf = isinstance(exc, FileNotFoundError)
        exc_reason = "not_found" if is_fnf else "exit_code"
        exc_detail = f"Execution error: {exc}"
        return ToolResult(
            tool_name="run_command",
            success=False,
            output="",
            error=json.dumps({
                "reason": exc_reason,
                "detail": exc_detail,
                "command": command,
            }),
            failure_reason=exc_reason,
            failure_detail=exc_detail,
        )


async def _execute_command_sandboxed(
    workspace: str,
    command: str,
    network: str = "none",
    image: str = "python:3.11-alpine",
) -> ToolResult:
    """Execute a command inside an isolated, disposable Docker container."""
    from ....core.paths import normalize_workspace
    norm_ws = normalize_workspace(workspace)
    ws_str = str(norm_ws.resolve())

    docker_args = [
        "docker", "run", "--rm",
        "-i",
        f"--network={network}",
        "-m", "512m",
        "--cpus", "1.0",
        "--pids-limit", "64",
        "--security-opt", "no-new-privileges",
        "-v", f"{ws_str}:/workspace:rw",
        "-w", "/workspace",
        image,
        "sh", "-c", command,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=35.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            exec_detail = "Command ran 35s and was killed."
            return ToolResult(
                tool_name="run_command",
                success=False,
                output="",
                error=json.dumps({
                    "reason": "execution_timeout",
                    "detail": exec_detail,
                    "command": command,
                }),
                failure_reason="execution_timeout",
                failure_detail=exec_detail,
            )

        raw_output = (stdout.decode("utf-8", errors="replace") or "") + \
                     ("\n" + stderr.decode("utf-8", errors="replace") if stderr else "")
        status_str = "SUCCESS" if proc.returncode == 0 else f"EXIT {proc.returncode}"

        if proc.returncode == 0:
            return ToolResult(
                tool_name="run_command",
                success=True,
                output=f"=== CONTAINER SANDBOX (docker) [{status_str}] ===\n{raw_output.strip() or '(no output)'}",
                error="",
            )

        lower_out = raw_output.lower()
        is_not_found = proc.returncode in (127, 9009) or "not found" in lower_out
        fail_reason = "not_found" if is_not_found else "exit_code"
        fail_detail = f"Container process exited with code {proc.returncode}"
        return ToolResult(
            tool_name="run_command",
            success=False,
            output=f"=== CONTAINER SANDBOX (docker) [{status_str}] ===\n{raw_output.strip() or '(no output)'}",
            error=json.dumps({
                "reason": fail_reason,
                "detail": fail_detail,
                "exit_code": proc.returncode,
                "command": command,
                "output": raw_output.strip()[:500],
            }),
            failure_reason=fail_reason,
            failure_detail=fail_detail,
        )
    except Exception as exc:
        exc_reason = "not_found" if isinstance(exc, FileNotFoundError) else "exit_code"
        exc_detail = f"Container execution error: {exc}"
        return ToolResult(
            tool_name="run_command",
            success=False,
            output="",
            error=json.dumps({
                "reason": exc_reason,
                "detail": exc_detail,
                "command": command,
            }),
            failure_reason=exc_reason,
            failure_detail=exc_detail,
        )


class SandboxExecutor:
    """Class wrapper providing a unified interface for sandboxed & resource-governed command execution."""

    def __init__(self):
        pass

    async def execute_command(
        self,
        workspace: str,
        command: str,
        sandboxed: bool = False,
        require_sandbox: bool = False,
        timeout: float = MAX_COMMAND_TIMEOUT_SECONDS,
    ) -> ToolResult:
        """Execute command either in strict container sandbox or on host with governor."""
        if sandboxed or require_sandbox:
            return await _execute_command_sandboxed(workspace, command)
        return await _execute_command_async(workspace, command, timeout=timeout)

    def check_capabilities(self) -> dict[str, Any]:
        """Inspect host virtualization and container runtimes."""
        caps = _detect_container_runtime()
        caps["windows_sandbox_available"] = _detect_windows_sandbox()
        return caps

    def cleanup(self) -> None:
        """No persistent background state for executor."""
        pass
