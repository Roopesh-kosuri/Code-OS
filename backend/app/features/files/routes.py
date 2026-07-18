from fastapi import APIRouter, Query

from backend.app.features.files.schemas import (
    CreateRequest,
    DeleteRequest,
    DuplicateRequest,
    FileReadResponse,
    MoveRequest,
    RenameRequest,
    TreeResponse,
    WriteRequest,
)
from backend.app.features.files.service import (
    build_tree,
    create_entry,
    delete_entry,
    duplicate_entry,
    move_entry,
    read_file,
    rename_entry,
    write_file,
)

router = APIRouter()


async def _ensure_trusted(workspace: str):
    from fastapi import HTTPException
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. File modifications are disabled.")



@router.get("/tree", response_model=TreeResponse)
async def tree(workspace: str = Query(...), max_depth: int = Query(4, ge=1, le=8)) -> TreeResponse:
    return TreeResponse(root=build_tree(workspace, max_depth))


@router.get("/read", response_model=FileReadResponse)
async def read(workspace: str = Query(...), path: str = Query(...)) -> FileReadResponse:
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
    await _ensure_trusted(payload.workspace)
    write_file(payload.workspace, payload.path, payload.content)
    return {"status": "written"}
