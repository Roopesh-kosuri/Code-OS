# Ghost Text Package
from .ghost_text_service import (
    register_editor,
    unregister_editor,
    get_active_editors,
    stream_inline_diff,
    emit_diff_chunks,
    stage_ghost_text,
    accept_ghost_text,
    reject_ghost_text,
    get_pending_ghost_text,
)
from .ghost_text_routes import router as ghost_text_router

__all__ = [
    "register_editor",
    "unregister_editor",
    "get_active_editors",
    "stream_inline_diff",
    "emit_diff_chunks",
    "stage_ghost_text",
    "accept_ghost_text",
    "reject_ghost_text",
    "get_pending_ghost_text",
    "ghost_text_router",
]
