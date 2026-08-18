"""
Background server session management package for CODE OS.
Provides lifecycle tracking, port polling, HTTP request dispatching, and process cleanup.
"""
from .server_manager import (
    ActiveServerSession,
    ServerSessionManager,
    _active_server_sessions,
    _server_session_start,
    _server_session_request,
    _server_session_stop,
    _server_session_list,
    _cleanup_server_sessions,
    _handle_server_session,
)

__all__ = [
    "ActiveServerSession",
    "ServerSessionManager",
    "_active_server_sessions",
    "_server_session_start",
    "_server_session_request",
    "_server_session_stop",
    "_server_session_list",
    "_cleanup_server_sessions",
    "_handle_server_session",
]
