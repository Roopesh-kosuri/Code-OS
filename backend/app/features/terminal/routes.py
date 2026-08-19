from typing import Any
from fastapi import APIRouter, WebSocket, HTTPException
from fastapi.responses import StreamingResponse

from .schemas import (
  CommandResult, TerminalCommandRequest, TerminalCreateRequest,
  TerminalRenameRequest, TerminalSessionDto,
  RunRequest, RunKillRequest, ToolchainInfo, ToolchainsResponse
)
from .service import (
  clear_session, create_session, kill_session, list_sessions,
  rename_session, run_command, handle_terminal_websocket
)
from .run_service import run_file_stream, kill_run_process
from .language_detector import get_all_toolchains

router = APIRouter()


async def _ensure_trusted(workspace: str):
    from ..workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. Terminal execution is disabled.")


@router.get("/sessions", response_model=list[TerminalSessionDto])
async def sessions() -> list[TerminalSessionDto]:
    return [TerminalSessionDto(id=session.id, name=session.name, cwd=session.cwd, shell=session.shell) for session in list_sessions()]  # nosec B604


@router.post("/sessions", response_model=TerminalSessionDto)
async def create(payload: TerminalCreateRequest) -> TerminalSessionDto:
    await _ensure_trusted(payload.cwd)
    session = create_session(payload.cwd, payload.shell)
    return TerminalSessionDto(id=session.id, name=session.name, cwd=session.cwd, shell=session.shell)  # nosec B604


@router.post("/sessions/{session_id}/command", response_model=CommandResult)
async def command(session_id: str, payload: TerminalCommandRequest) -> CommandResult:
    from app.core.rate_limiter import rate_limiter
    rate_limiter.check("terminal_exec", max_requests=10, window_seconds=10.0)
    session = next((s for s in list_sessions() if s.id == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Terminal session not found")
    await _ensure_trusted(session.cwd)
    output, exit_code, background = await run_command(session_id, payload.command, payload.background)
    return CommandResult(output=output, exit_code=exit_code, background=background, cwd=session.cwd)



@router.post("/sessions/{session_id}/clear")
async def clear(session_id: str) -> dict[str, str]:
    clear_session(session_id)
    return {"status": "cleared"}


@router.post("/sessions/{session_id}/rename", response_model=TerminalSessionDto)
async def rename(session_id: str, payload: TerminalRenameRequest) -> TerminalSessionDto:
    session = rename_session(session_id, payload.name)
    return TerminalSessionDto(id=session.id, name=session.name, cwd=session.cwd, shell=session.shell)  # nosec B604


@router.post("/sessions/{session_id}/kill")
async def kill(session_id: str) -> dict[str, str]:
    kill_session(session_id)
    return {"status": "killed"}


@router.websocket("/ws")
async def terminal_websocket(websocket: WebSocket) -> None:
    cwd = websocket.query_params.get("cwd")
    # SECURITY: reject WebSocket connections that do not supply a workspace path.
    # Without a cwd we cannot determine trust, so granting a shell would be a
    # trust-check bypass.
    if not cwd:
        await websocket.accept()
        await websocket.send_text("\r\n\x1b[31m[No workspace path provided. Terminal connection rejected.]\x1b[0m\r\n")
        await websocket.close(code=4003)
        return
    from ..workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(cwd)
    if not trust.get("trusted", False):
        await websocket.accept()
        await websocket.send_text("\r\n\x1b[31m[Workspace is in Restricted Mode. Terminal execution is disabled.]\x1b[0m\r\n")
        await websocket.close(code=4003)
        return
    await handle_terminal_websocket(websocket)
 
 
@router.post("/run")
async def run_file(payload: RunRequest):
    """Execute a source file with automatic language detection, compilation, and SSE streaming output."""
    from app.core.rate_limiter import rate_limiter
    rate_limiter.check("terminal_run", max_requests=20, window_seconds=10.0)
    await _ensure_trusted(payload.workspace)
    return StreamingResponse(
        run_file_stream(payload.workspace, payload.file_path, payload.args),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/run/kill")
async def kill_run(payload: RunKillRequest) -> dict[str, Any]:
    """Terminate an active running file process."""
    success, message = kill_run_process(payload.run_id)
    return {"success": success, "message": message, "run_id": payload.run_id}


@router.get("/toolchains", response_model=ToolchainsResponse)
async def toolchains() -> ToolchainsResponse:
    """Inspect and return installed language compilers and runtimes on the host."""
    items = get_all_toolchains()
    return ToolchainsResponse(toolchains=[
        ToolchainInfo(
            id=t.id,
            name=t.name,
            installed=t.installed,
            version=t.version,
            command_path=t.command_path,
            compile_command_path=t.compile_command_path,
            install_hint=t.install_hint,
            error_message=t.error_message,
        ) for t in items
    ])


