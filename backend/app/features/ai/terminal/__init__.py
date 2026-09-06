"""
terminal package for AI features — Agentic Terminal with real-time streaming.
"""

from .agentic_terminal_service import (
    create_session,
    get_session,
    close_session,
    execute_command,
    send_signal,
    stream_output,
    list_active_sessions,
    get_active_session_for_workspace,
    get_active_session_for_job,
    clear_all_sessions,
)
from .agentic_terminal_routes import router as agentic_terminal_router

__all__ = [
    "create_session",
    "get_session",
    "close_session",
    "execute_command",
    "send_signal",
    "stream_output",
    "list_active_sessions",
    "get_active_session_for_workspace",
    "get_active_session_for_job",
    "clear_all_sessions",
    "agentic_terminal_router",
]
