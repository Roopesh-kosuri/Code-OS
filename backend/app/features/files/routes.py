from fastapi import APIRouter, Query, HTTPException


from .schemas import (
    CreateRequest,
    DeleteRequest,
    DuplicateRequest,
    FileReadResponse,
    MoveRequest,
    RenameRequest,
    RevealRequest,
    TreeResponse,
    WriteRequest,
)
from .service import (
    build_tree,
    create_entry,
    delete_entry,
    duplicate_entry,
    move_entry,
    read_file,
    rename_entry,
    reveal_entry,
    write_file,
)

router = APIRouter()


async def _ensure_trusted(workspace: str):
    from fastapi import HTTPException
    from ..workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode.")



@router.get("/tree", response_model=TreeResponse)
async def tree(workspace: str = Query(...), max_depth: int = Query(4, ge=1, le=8)) -> TreeResponse:
    await _ensure_trusted(workspace)
    return TreeResponse(root=build_tree(workspace, max_depth))


@router.get("/read", response_model=FileReadResponse)
async def read(workspace: str = Query(...), path: str = Query(...)) -> FileReadResponse:
    await _ensure_trusted(workspace)
    content, language = read_file(workspace, path)
    return FileReadResponse(path=path, content=content, language=language)


@router.post("/create")
async def create(payload: CreateRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    create_entry(payload.workspace, payload.path, payload.type)
    return {"status": "created"}


@router.post("/delete")
async def delete(payload: DeleteRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    delete_entry(payload.workspace, payload.path)
    return {"status": "deleted"}


@router.post("/rename")
async def rename(payload: RenameRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    destination = rename_entry(payload.workspace, payload.path, payload.new_name)
    return {"status": "renamed", "path": str(destination)}


@router.post("/move")
async def move(payload: MoveRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    destination = move_entry(payload.workspace, payload.source, payload.destination)
    return {"status": "moved", "path": str(destination)}


@router.post("/duplicate")
async def duplicate(payload: DuplicateRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    destination = duplicate_entry(payload.workspace, payload.path, payload.destination)
    return {"status": "duplicated", "path": str(destination)}


@router.post("/write")
async def write(payload: WriteRequest) -> dict[str, str]:
    from app.core.rate_limiter import rate_limiter
    rate_limiter.check("files_write", max_requests=60, window_seconds=60.0)
    await _ensure_trusted(payload.workspace)
    write_file(payload.workspace, payload.path, payload.content)
    return {"status": "written"}


@router.post("/reveal")
async def reveal(payload: RevealRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    reveal_entry(payload.workspace, payload.path)
    return {"status": "revealed"}


