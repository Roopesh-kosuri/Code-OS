"""
chat_harness_routes.py — FastAPI routes for the lightweight chat agent harness.

Provides SSE streaming endpoint, health/boot endpoint, user interactive response endpoint,
approval/rejection endpoints, per-turn undo endpoint, runtime freshness indicator, and
workspace trusted commands management.
This is a dedicated router — does NOT modify any existing Agent Console routes.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

BOOT_TIMESTAMP = time.time()


# ── Request / Response schemas ───────────────────────────────────────────────

class ChatAgentStreamRequest(BaseModel):
    """Request body for the chat agent SSE stream."""
    provider: str = "auto"
    model: str = ""
    base_url: str | None = None
    temperature: float = 0.2
    api_key_provider: str | None = None
    messages: list[dict] = Field(default_factory=list)  # [{role, content}]
    workspace: str = ""
    attached_paths: list[str] = Field(default_factory=list)
    attached_images: list[dict] = Field(default_factory=list)  # [{name, dataUrl, size}]
    agent_mode: bool = False  # Default OFF, Agent toggle enables manual override
    vision_model: str | None = None
    vision_provider: str | None = None
    vision_base_url: str | None = None


class ApprovalResponse(BaseModel):
    success: bool
    message: str = ""


class ApprovalRequestPayload(BaseModel):
    always_allow: bool = False
    trust_pattern: str | None = None


class UserAnswerRequest(BaseModel):
    answer: str


class UndoTurnRequest(BaseModel):
    workspace: str
    commit_hash: str
    touched_files: list[str] = Field(default_factory=list)


class UndoTurnResponse(BaseModel):
    success: bool
    message: str
    restored_files: list[str] = Field(default_factory=list)


class FreshnessResponse(BaseModel):
    boot_timestamp: float
    boot_iso: str
    uptime_seconds: float
    is_stale: bool
    latest_source_mtime: float
    changed_files: list[str] = Field(default_factory=list)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/chat-agent/health")
async def chat_agent_health() -> dict:
    """Return backend health and boot timestamp for stale-process discipline."""
    return {
        "status": "ok",
        "boot_timestamp": BOOT_TIMESTAMP,
        "uptime_seconds": time.time() - BOOT_TIMESTAMP,
    }


@router.get("/chat-agent/freshness", response_model=FreshnessResponse)
async def backend_freshness() -> FreshnessResponse:
    """Return backend process freshness and detect on-disk code newer than the running process."""
    now = time.time()
    backend_app_dir = Path(__file__).resolve().parent.parent.parent  # app
    backend_dir = backend_app_dir.parent  # backend
    max_mtime = BOOT_TIMESTAMP
    changed_files: list[str] = []

    try:
        for py_file in backend_app_dir.rglob("*.py"):
            try:
                st = py_file.stat()
                if st.st_mtime > max_mtime:
                    max_mtime = max(max_mtime, st.st_mtime)
                if st.st_mtime > BOOT_TIMESTAMP + 0.5:
                    rel = py_file.relative_to(backend_dir)
                    changed_files.append(str(rel).replace("\\", "/"))
            except Exception:
                pass
    except Exception as exc:
        logger.warning("freshness check error: %s", exc)

    is_stale = len(changed_files) > 0
    return FreshnessResponse(
        boot_timestamp=BOOT_TIMESTAMP,
        boot_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(BOOT_TIMESTAMP)),
        uptime_seconds=now - BOOT_TIMESTAMP,
        is_stale=is_stale,
        latest_source_mtime=max_mtime,
        changed_files=changed_files[:20],
    )


@router.post("/chat-agent/stream")
async def chat_agent_stream(payload: ChatAgentStreamRequest) -> StreamingResponse:
    """Stream SSE events from the chat agent harness.
    
    Runs adaptive tiered execution (Tier 0 Fast Answer, Tier 1 Quick Task, Tier 2 Deep Task)
    with tool execution, budgeted RAG, DAG planning, and verification.
    """
    from app.core.rate_limiter import rate_limiter
    rate_limiter.check("chat_agent_stream", max_requests=30, window_seconds=60.0)
    
    from .chat_harness import run_chat_agent, ChatAgentRequest
    
    agent_request = ChatAgentRequest(
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        temperature=payload.temperature,
        api_key_provider=payload.api_key_provider,
        messages=payload.messages,
        workspace=payload.workspace,
        attached_paths=payload.attached_paths,
        attached_images=payload.attached_images,
        is_agent_mode=payload.agent_mode,
        vision_model=payload.vision_model,
        vision_provider=payload.vision_provider,
        vision_base_url=payload.vision_base_url,
    )
    
    return StreamingResponse(
        run_chat_agent(agent_request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat-agent/approve/{action_id}", response_model=ApprovalResponse)
async def approve_agent_action(action_id: str, payload: ApprovalRequestPayload | None = None) -> ApprovalResponse:
    """Approve a pending agent action (e.g., command execution or file edit proposal)."""
    from .chat_harness import approve_action
    
    always = payload.always_allow if payload else False
    pattern = payload.trust_pattern if payload else None
    success = await approve_action(action_id, always_allow=always, trust_pattern=pattern)
    if success:
        return ApprovalResponse(success=True, message=f"Action {action_id} approved")
    raise HTTPException(status_code=404, detail=f"No pending action with ID {action_id}")


@router.post("/chat-agent/reject/{action_id}", response_model=ApprovalResponse)
async def reject_agent_action(action_id: str) -> ApprovalResponse:
    """Reject a pending agent action."""
    from .chat_harness import reject_action
    
    success = await reject_action(action_id)
    if success:
        return ApprovalResponse(success=True, message=f"Action {action_id} rejected")
    raise HTTPException(status_code=404, detail=f"No pending action with ID {action_id}")


@router.post("/chat-agent/respond/{action_id}", response_model=ApprovalResponse)
async def respond_to_agent_question(action_id: str, payload: UserAnswerRequest) -> ApprovalResponse:
    """Respond to an ask_user question posed by Rony Agent."""
    from .chat_harness import respond_to_user_question
    
    success = respond_to_user_question(action_id, payload.answer)
    if success:
        return ApprovalResponse(success=True, message=f"Response submitted for action {action_id}")
    raise HTTPException(status_code=404, detail=f"No pending user question with ID {action_id}")


@router.post("/chat-agent/undo-turn", response_model=UndoTurnResponse)
async def undo_turn_checkpoint(payload: UndoTurnRequest) -> UndoTurnResponse:
    """Restore ONLY the agent-touched files from a pre-turn checkpoint commit."""
    from .chat_harness import undo_turn_files
    
    success, message, restored = undo_turn_files(payload.workspace, payload.commit_hash, payload.touched_files)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return UndoTurnResponse(success=True, message=message, restored_files=restored)


@router.get("/chat-agent/trusted-commands")
async def get_trusted_commands(workspace: str = "") -> dict:
    """List trusted terminal command patterns for the workspace."""
    from .chat_harness import _load_trusted_commands
    cmds = _load_trusted_commands(workspace)
    return {"workspace": workspace, "trusted_commands": cmds}


class AddTrustedCommandRequest(BaseModel):
    workspace: str = ""
    pattern: str = ""


@router.post("/chat-agent/trusted-commands")
async def add_trusted_command(payload: AddTrustedCommandRequest) -> dict:
    """Add a trusted command pattern for the workspace."""
    from .chat_harness import _save_trusted_command
    ok = _save_trusted_command(payload.workspace, payload.pattern)
    return {"workspace": payload.workspace, "pattern": payload.pattern, "added": ok}


@router.delete("/chat-agent/trusted-commands")
async def delete_trusted_command(workspace: str = "", pattern: str = "") -> dict:
    """Revoke a trusted command pattern for the workspace."""
    from .chat_harness import _remove_trusted_command
    ok = _remove_trusted_command(workspace, pattern)
    return {"workspace": workspace, "pattern": pattern, "removed": ok}


@router.post("/chat-agent/cancel", response_model=ApprovalResponse)
async def cancel_agent_run() -> ApprovalResponse:
    """Cancel active run and clear all pending approval/ask_user cards."""
    from .chat_harness import clear_all_pending
    cleared = clear_all_pending()
    return ApprovalResponse(success=True, message=f"Run cancelled and {cleared} pending items cleared.")


# ── Checkpoint-Resume Routes ────────────────────────────────────────────────

@router.get("/chat-agent/interrupted-state")
async def get_interrupted_state(workspace: str = "") -> dict:
    """Check for interrupted agent loop state in workspace."""
    from .chat_harness import _load_interrupted_state
    state = _load_interrupted_state(workspace)
    return {
        "workspace": workspace,
        "has_interrupted": state is not None,
        "state": state,
    }


class ResumeAgentRequest(BaseModel):
    workspace: str = ""
    provider: str = "auto"
    model: str = ""
    base_url: str | None = None
    temperature: float = 0.2
    api_key_provider: str | None = None


@router.post("/chat-agent/resume")
async def resume_agent_stream(payload: ResumeAgentRequest) -> StreamingResponse:
    """Resume execution of an interrupted agent loop from saved state."""
    from .chat_harness import _load_interrupted_state, run_chat_agent, ChatAgentRequest
    import json
    state = _load_interrupted_state(payload.workspace)
    if not state:
        raise HTTPException(status_code=404, detail="No interrupted state found to resume.")

    req = ChatAgentRequest(
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        temperature=payload.temperature,
        api_key_provider=payload.api_key_provider,
        messages=state.get("messages", []),
        workspace=payload.workspace,
        is_agent_mode=True,
    )

    async def event_generator():
        step_num = state.get("iteration", 0) + 1
        yield f"event: status\ndata: {json.dumps({'type': 'resume', 'message': f'Resuming interrupted task from step {step_num}...'})}\n\n"
        async for sse in run_chat_agent(req):
            yield sse

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/chat-agent/interrupted-state")
async def delete_interrupted_state(workspace: str = "") -> dict:
    """Discard interrupted state."""
    from .chat_harness import _clear_interrupted_state
    cleared = _clear_interrupted_state(workspace)
    return {"workspace": workspace, "cleared": cleared}


# ── Activity Timeline Routes ────────────────────────────────────────────────

@router.get("/chat-agent/activity-log")
async def get_activity_log(
    workspace: str = "",
    search: str = "",
    filter_type: str = "all",
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Retrieve filtered activity timeline entries for workspace with pagination."""
    from .chat_harness import _load_activity_log
    limit = min(max(1, limit), 1000)
    offset = max(0, offset)
    meta = _load_activity_log(
        workspace,
        search=search,
        filter_type=filter_type,
        limit=limit,
        offset=offset,
        return_metadata=True,
    )
    return {
        "workspace": workspace,
        "entries": meta["entries"],
        "total": meta["total"],
        "has_more": meta["has_more"],
        "limit": limit,
        "offset": offset,
    }


@router.get("/chat-agent/activity-log/export")
async def export_activity_log(workspace: str = ""):
    """Export raw activity_log.jsonl for workspace as a downloadable file."""
    if not workspace:
        raise HTTPException(status_code=400, detail="Workspace parameter required.")
    p = Path(workspace) / ".code_os" / "activity_log.jsonl"
    if not p.is_file():
        return Response(content="", media_type="text/plain", headers={"Content-Disposition": "attachment; filename=activity_log.jsonl"})
    content = p.read_text(encoding="utf-8", errors="replace")
    return Response(
        content=content,
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": "attachment; filename=activity_log.jsonl"},
    )


# ── Phase 4: Structure & Differentiation Endpoints ─────────────────────────

@router.get("/chat-agent/symbols/references")
async def get_symbol_references(workspace: str = "", symbol: str = "") -> dict:
    """Find all usages and references of a symbol across workspace files."""
    if not workspace or not symbol:
        raise HTTPException(status_code=400, detail="workspace and symbol parameters required.")
    from .chat_harness import _handle_find_references
    res = _handle_find_references(workspace, {"symbol": symbol})
    return {"workspace": workspace, "symbol": symbol, "output": res.output, "success": res.success, "error": res.error}


@router.get("/chat-agent/symbols/definition")
async def get_symbol_definition(workspace: str = "", symbol: str = "") -> dict:
    """Find definition location for a symbol across workspace files."""
    if not workspace or not symbol:
        raise HTTPException(status_code=400, detail="workspace and symbol parameters required.")
    from .chat_harness import _handle_go_to_definition
    res = _handle_go_to_definition(workspace, {"symbol": symbol})
    return {"workspace": workspace, "symbol": symbol, "output": res.output, "success": res.success, "error": res.error}


@router.get("/chat-agent/style-conventions")
async def get_style_conventions(workspace: str = "") -> dict:
    """Extract or load workspace style conventions (naming, imports, error handling, comments)."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter required.")
    from .chat_harness import _extract_style_conventions
    conventions = _extract_style_conventions(workspace)
    return {"workspace": workspace, "conventions": conventions}


@router.get("/chat-agent/dead-code")
async def scan_dead_code(workspace: str = "") -> dict:
    """Detect unreferenced / orphaned files in workspace."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter required.")
    from .chat_harness import _find_dead_code
    res = _find_dead_code(workspace)
    return {"workspace": workspace, "output": res.output, "success": res.success}


@router.get("/chat-agent/architecture-doc")
async def get_architecture_doc(workspace: str = "") -> dict:
    """Load or generate ARCHITECTURE.md for workspace."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter required.")
    from .chat_harness import _load_architecture_doc, _update_architecture_doc
    content = _load_architecture_doc(workspace)
    if not content:
        res = _update_architecture_doc(workspace, reason="Initial auto-generation")
        content = _load_architecture_doc(workspace)
    return {"workspace": workspace, "content": content}


@router.post("/chat-agent/server-session")
async def handle_server_session_endpoint(payload: dict) -> dict:
    """Manage background server sessions (start, request, stop, list)."""
    ws = payload.get("workspace", "")
    from .chat_harness import _handle_server_session
    res = _handle_server_session(ws, payload)
    return {"success": res.success, "output": res.output, "error": res.error}


# ── Phase 5: OS-Level Sandboxing & Production Hardening Endpoints ───────────

@router.get("/chat-agent/sandbox/capabilities")
async def get_sandbox_capabilities() -> dict:
    """Detect Docker, WSL2, and Windows Sandbox capabilities on host system."""
    from .chat_harness import _detect_container_runtime, _detect_windows_sandbox
    caps = _detect_container_runtime()
    caps["windows_sandbox_available"] = _detect_windows_sandbox()
    return caps


@router.post("/chat-agent/sandbox/launch-wsb")
async def launch_wsb_sandbox(payload: dict) -> dict:
    """Generate .wsb config and launch Windows Sandbox for untrusted project mode."""
    workspace = payload.get("workspace", "")
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter required.")
    from .chat_harness import _launch_windows_sandbox
    success, msg = _launch_windows_sandbox(workspace)
    return {"success": success, "message": msg}


@router.post("/chat-agent/backup/create")
async def create_backup(payload: dict) -> dict:
    """Create timestamped zip backup of workspace .code_os/ directory."""
    workspace = payload.get("workspace", "")
    reason = payload.get("reason", "manual")
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter required.")
    from .backup_service import create_workspace_backup
    backup_path = create_workspace_backup(workspace, reason=reason)
    return {"workspace": workspace, "success": bool(backup_path), "backup_path": backup_path}


@router.post("/chat-agent/backup/restore")
async def restore_backup(payload: dict) -> dict:
    """Restore workspace .code_os/ directory from a backup archive."""
    workspace = payload.get("workspace", "")
    filename = payload.get("filename")
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter required.")
    from .backup_service import restore_workspace_backup
    success = restore_workspace_backup(workspace, backup_filename=filename)
    return {"workspace": workspace, "success": success}


@router.get("/chat-agent/backup/list")
async def list_backups(workspace: str = "") -> dict:
    """List available backup archives for workspace."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace parameter required.")
    from .backup_service import list_workspace_backups
    backups = list_workspace_backups(workspace)
    return {"workspace": workspace, "backups": backups}


@router.get("/chat-agent/rate-limit/status")
async def get_rate_limit_status(workspace: str = "") -> dict:
    """Get current monthly token usage and rate limit status."""
    from ...core.rate_limiter import rate_limiter
    key = workspace or "default_user"
    return rate_limiter.get_token_status(key)


