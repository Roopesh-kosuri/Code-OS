"""
Sandbox execution package for CODE OS.
Provides containerized (Docker), virtualized (Windows Sandbox), and resource-governed command execution.
"""
from .executor import (
    SandboxExecutor,
    SandboxUnavailableError,
    _monitor_process_governor,
    _detect_container_runtime,
    _detect_windows_sandbox,
    _generate_wsb_config,
    _launch_windows_sandbox,
    _execute_command_async,
    _execute_command_sandboxed,
)

__all__ = [
    "SandboxExecutor",
    "SandboxUnavailableError",
    "_monitor_process_governor",
    "_detect_container_runtime",
    "_detect_windows_sandbox",
    "_generate_wsb_config",
    "_launch_windows_sandbox",
    "_execute_command_async",
    "_execute_command_sandboxed",
]
