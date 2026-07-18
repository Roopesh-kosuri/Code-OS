from fastapi import APIRouter, WebSocket, HTTPException

from backend.app.features.terminal.schemas import (
  CommandResult, TerminalCommandRequest, TerminalCreateRequest,
  TerminalRenameRequest, TerminalSessionDto
)
from backend.app.features.terminal.service import (
  clear_session, create_session, kill_session, list_sessions,
  rename_session, run_command, handle_terminal_websocket
)

router = APIRouter()


async def _ensure_trusted(workspace: str):
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. Terminal execution is disabled.")


@router.get("/sessions", response_model=list[TerminalSessionDto])
async def sessions() -> list[TerminalSessionDto]:
    return [TerminalSessionDto(id=session.id, name=session.name, cwd=session.cwd, shell=session.shell) for session in list_sessions()]


@router.post("/sessions", response_model=TerminalSessionDto)
async def create(payload: TerminalCreateRequest) -> TerminalSessionDto:
    await _ensure_trusted(payload.cwd)
    session = create_session(payload.cwd, payload.shell)
    return TerminalSessionDto(id=session.id, name=session.name, cwd=session.cwd, shell=session.shell)


@router.post("/sessions/{session_id}/command", response_model=CommandResult)
async def command(session_id: str, payload: TerminalCommandRequest) -> CommandResult:
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
    return TerminalSessionDto(id=session.id, name=session.name, cwd=session.cwd, shell=session.shell)


@router.post("/sessions/{session_id}/kill")
async def kill(session_id: str) -> dict[str, str]:
    kill_session(session_id)
    return {"status": "killed"}


@router.websocket("/ws")
async def terminal_websocket(websocket: WebSocket) -> None:
    cwd = websocket.query_params.get("cwd")
    if cwd:
        from backend.app.features.workspaces.trust_service import get_workspace_trust
        trust = await get_workspace_trust(cwd)
        if not trust.get("trusted", False):
            await websocket.accept()
            await websocket.send_text("\r\n\x1b[31m[Workspace is in Restricted Mode. Terminal execution is disabled.]\x1b[0m\r\n")
            await websocket.close(code=4003)
            return
    await handle_terminal_websocket(websocket)
