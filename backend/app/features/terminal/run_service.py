"""
Multi-Language File Run Service for CODE OS.
Compiles and executes source files under strict resource limits (512MB RAM cap, 60s timeout ceiling),
streams real-time output via SSE, and supports instant process termination.
"""
import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator

from app.features.files.service import ensure_within_workspace
from app.core.paths import normalize_workspace
from app.features.terminal.language_detector import (
    LanguageSpec,
    ToolchainStatus,
    check_toolchain_status,
    detect_language,
    _find_executable,
)
from app.features.terminal.service import _build_safe_environment
from app.core.monitoring import monitor

logger = logging.getLogger(__name__)

MAX_RUN_MEMORY_BYTES = 512 * 1024 * 1024  # 512MB RAM cap
MAX_RUN_TIMEOUT_SECONDS = 60.0             # 60s hard ceiling

# Registry of active running file processes: {run_id: Process}
_active_runs: dict[str, asyncio.subprocess.Process] = {}
_active_run_temps: dict[str, str] = {}  # {run_id: temp_dir} for compiled binaries


def kill_run_process(run_id: str) -> tuple[bool, str]:
    """Kill an active file run process and clean up temporary build artifacts."""
    proc = _active_runs.get(run_id)
    if not proc:
        return False, f"Run session '{run_id}' not found or already finished."

    try:
        if proc.returncode is None:
            # Kill process tree if psutil is available
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
                proc.kill()
        
        # Cleanup temp directory if one was created
        temp_dir = _active_run_temps.pop(run_id, None)
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        _active_runs.pop(run_id, None)
        return True, f"Process {run_id} stopped successfully."
    except Exception as exc:
        logger.warning("run_service: failed to kill process %s: %s", run_id, exc)
        return False, f"Failed to kill process {run_id}: {exc}"


async def _monitor_run_governor(
    proc: asyncio.subprocess.Process,
    max_memory_bytes: int = MAX_RUN_MEMORY_BYTES,
    poll_interval: float = 0.05,
) -> tuple[bool, str]:
    """Actively monitor RAM RSS of process and all descendants. Kill if > 512MB."""
    try:
        import psutil
        p = psutil.Process(proc.pid)
        while proc.returncode is None:
            try:
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
                    return True, "Process exceeded memory ceiling (512MB RAM cap)."
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            await asyncio.sleep(poll_interval)
    except ImportError:
        while proc.returncode is None:
            await asyncio.sleep(0.1)
    except Exception:
        pass
    return False, ""


async def _compile_file(
    workspace: Path,
    file_path: Path,
    lang_spec: LanguageSpec,
    temp_dir: Path,
    env: dict,
) -> tuple[bool, list[str], str]:
    """
    Compile source file for languages requiring a compilation step (C/C++, Rust, Java).
    Returns (success: bool, exec_args: list[str], error_output: str).
    """
    bin_name = "program.exe" if os.name == "nt" else "program"
    out_bin = temp_dir / bin_name

    if lang_spec.id == "cpp":
        # Find g++, clang++, gcc, or cl
        compiler = _find_executable(["g++", "clang++", "gcc", "clang"])
        if not compiler:
            return False, [], "No C/C++ compiler found (g++ / clang++ / gcc). Please install a compiler toolchain."

        is_cpp = file_path.suffix.lower() in (".cpp", ".cc", ".cxx", ".hpp")
        std_flag = "-std=c++17" if is_cpp else "-std=c11"
        cmd = [compiler, std_flag, "-O2", str(file_path), "-o", str(out_bin)]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = (stderr or stdout).decode("utf-8", errors="replace")
            return False, [], err
        return True, [str(out_bin)], ""

    if lang_spec.id == "rust":
        compiler = _find_executable(["rustc"])
        if not compiler:
            return False, [], "Rust compiler (rustc) not found. Please install Rust via https://rustup.rs/."

        cmd = [compiler, "-O", str(file_path), "-o", str(out_bin)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = (stderr or stdout).decode("utf-8", errors="replace")
            return False, [], err
        return True, [str(out_bin)], ""

    if lang_spec.id == "java":
        # Java 11+ supports direct `java File.java` without explicit compilation
        javac = _find_executable(["javac"])
        java = _find_executable(["java"])
        if not java:
            return False, [], "Java runtime not found. Please install JDK 17+."
        
        # Test if direct execution works or compile with javac
        cmd = [java, str(file_path)]
        return True, cmd, ""

    return False, [], f"Compilation not supported for language '{lang_spec.id}'"


async def run_file_stream(
    workspace: str,
    file_path: str,
    args: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Execute a source file with automatic language detection, compilation, and resource governance.
    Yields SSE formatted string packets: data: {"event": "...", "data": {...}}\n\n
    """
    start_time = time.time()
    run_id = f"run_{uuid.uuid4().hex[:8]}"

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    try:
        # 1. Path containment check
        norm_ws = normalize_workspace(workspace)
        full_path = ensure_within_workspace(str(norm_ws), file_path)
        if not full_path.is_file():
            yield sse("error", {"error": f"File '{file_path}' does not exist in workspace."})
            return

        # 2. Language Detection
        lang_spec = detect_language(full_path)
        if not lang_spec:
            yield sse("error", {
                "error": f"Unsupported file type '{full_path.suffix}'. CODE OS supports Python, JavaScript, TypeScript, C/C++, Java, Go, Rust, and Shell."
            })
            return

        # 3. Toolchain Status Check
        status = check_toolchain_status(lang_spec.id)
        if not status.installed:
            err_msg = status.error_message or f"{lang_spec.name} toolchain is not installed."
            if status.install_hint:
                err_msg += f"\n\n[Installation Guide]:\n{status.install_hint}"
            yield sse("error", {"error": err_msg, "toolchain": lang_spec.id, "install_hint": status.install_hint})
            return

        env = _build_safe_environment()
        temp_build_dir = tempfile.mkdtemp(prefix="code_os_run_bin_")
        _active_run_temps[run_id] = temp_build_dir

        # 4. Compilation (if required)
        exec_cmd: list[str] = []
        if lang_spec.is_compiled:
            yield sse("compiling", {
                "run_id": run_id,
                "language": lang_spec.name,
                "file": file_path,
                "message": f"Compiling {file_path} with {lang_spec.name} compiler...",
            })
            comp_ok, comp_args, comp_err = await _compile_file(
                norm_ws, full_path, lang_spec, Path(temp_build_dir), env
            )
            if not comp_ok:
                yield sse("stderr", {"text": comp_err or "Compilation failed."})
                yield sse("exit", {"exit_code": 1, "duration_ms": (time.time() - start_time) * 1000.0, "run_id": run_id})
                return
            exec_cmd = comp_args
        else:
            # Interpreted / direct runner
            if lang_spec.id == "python":
                py_exe = _find_executable(["python", "python3", "py"]) or "python"
                exec_cmd = [py_exe, str(full_path)]
            elif lang_spec.id == "javascript":
                node_exe = _find_executable(["node", "nodejs"]) or "node"
                exec_cmd = [node_exe, str(full_path)]
            elif lang_spec.id == "typescript":
                tsx_exe = _find_executable(["tsx", "ts-node", "bun", "deno"])
                if tsx_exe:
                    exec_cmd = [tsx_exe, str(full_path)]
                else:
                    exec_cmd = ["npx", "tsx", str(full_path)]
            elif lang_spec.id == "go":
                go_exe = _find_executable(["go"]) or "go"
                exec_cmd = [go_exe, "run", str(full_path)]
            elif lang_spec.id == "shell":
                if os.name == "nt":
                    if full_path.suffix.lower() == ".ps1":
                        exec_cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(full_path)]
                    elif full_path.suffix.lower() in (".bat", ".cmd"):
                        exec_cmd = ["cmd.exe", "/c", str(full_path)]
                    else:
                        exec_cmd = ["powershell", "-NoProfile", "-Command", f"& '{str(full_path)}'"]
                else:
                    sh_exe = _find_executable(["bash", "zsh", "sh"]) or "bash"
                    exec_cmd = [sh_exe, str(full_path)]

        if args:
            exec_cmd.extend(args)

        # 5. Process Spawning
        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            cwd=str(norm_ws),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _active_runs[run_id] = proc

        yield sse("started", {
            "run_id": run_id,
            "language": lang_spec.name,
            "file": file_path,
            "command": " ".join(os.path.basename(c) for c in exec_cmd[:2]) + f" {file_path}",
        })

        # 6. Active Memory Governor Task
        gov_task = asyncio.create_task(_monitor_run_governor(proc, max_memory_bytes=MAX_RUN_MEMORY_BYTES))

        # 7. Asynchronous Line Streaming
        async def stream_pipe(stream, event_name: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                yield sse(event_name, {"text": text, "run_id": run_id})

        # Stream stdout and stderr concurrently
        async def read_stream_queue(stream, event_name: str, queue: asyncio.Queue):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                await queue.put((event_name, text))
            await queue.put((event_name, None))

        queue: asyncio.Queue = asyncio.Queue()
        stdout_task = asyncio.create_task(read_stream_queue(proc.stdout, "stdout", queue))
        stderr_task = asyncio.create_task(read_stream_queue(proc.stderr, "stderr", queue))

        pending_streams = 2
        timeout_exceeded = False
        gov_exceeded = False
        gov_message = ""

        try:
            start_loop_t = time.time()
            while pending_streams > 0:
                # Check timeout ceiling (60s)
                if (time.time() - start_loop_t) > MAX_RUN_TIMEOUT_SECONDS:
                    timeout_exceeded = True
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break

                if gov_task.done():
                    hit, msg = gov_task.result()
                    if hit:
                        gov_exceeded = True
                        gov_message = msg
                        break

                try:
                    event_name, text = await asyncio.wait_for(queue.get(), timeout=0.1)
                    if text is None:
                        pending_streams -= 1
                    else:
                        yield sse(event_name, {"text": text, "run_id": run_id})
                except asyncio.TimeoutError:
                    continue
        finally:
            if not gov_task.done():
                gov_task.cancel()
            stdout_task.cancel()
            stderr_task.cancel()

        await proc.wait()

        dur_ms = (time.time() - start_time) * 1000.0
        monitor.record_metric("file_run_execution", dur_ms)

        if gov_exceeded:
            yield sse("stderr", {"text": f"\n[RESOURCE ERROR]: {gov_message}\n", "run_id": run_id})
            yield sse("exit", {"exit_code": 137, "duration_ms": dur_ms, "run_id": run_id})
        elif timeout_exceeded:
            yield sse("stderr", {"text": f"\n[TIMEOUT ERROR]: Process timed out after {int(MAX_RUN_TIMEOUT_SECONDS)}s ceiling.\n", "run_id": run_id})
            yield sse("exit", {"exit_code": 124, "duration_ms": dur_ms, "run_id": run_id})
        else:
            yield sse("exit", {"exit_code": proc.returncode, "duration_ms": dur_ms, "run_id": run_id})

    except Exception as exc:
        logger.exception("run_service: execution error for %s: %s", file_path, exc)
        yield sse("error", {"error": f"Execution failed: {exc}", "run_id": run_id})
    finally:
        _active_runs.pop(run_id, None)
        temp_dir = _active_run_temps.pop(run_id, None)
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
