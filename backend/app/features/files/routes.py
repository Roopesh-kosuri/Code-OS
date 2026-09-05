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

from ...core.trust import ensure_workspace_trusted as _ensure_trusted


@router.get("/tree", response_model=TreeResponse)
async def tree(
    workspace: str = Query(...),
    max_depth: int = Query(4, ge=1, le=8),
    path: str | None = Query(None),
    depth: int | None = Query(None),
) -> TreeResponse:
    await _ensure_trusted(workspace)
    return TreeResponse(root=build_tree(workspace, max_depth=max_depth, path=path, depth=depth))


@router.get("/read", response_model=FileReadResponse)
async def read(workspace: str = Query(...), path: str = Query(...)) -> FileReadResponse:
    await _ensure_trusted(workspace)
    content, language = read_file(workspace, path)
    return FileReadResponse(path=path, content=content, language=language)


@router.post("/create")
async def create(payload: CreateRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    target = create_entry(payload.workspace, payload.path, payload.type)
    return {"path": str(target), "status": "created"}


@router.post("/delete")
async def delete(payload: DeleteRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    delete_entry(payload.workspace, payload.path)
    return {"status": "ok"}


@router.post("/rename")
async def rename(payload: RenameRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    target = rename_entry(payload.workspace, payload.path, payload.new_name)
    return {"path": str(target), "status": "created"}


@router.post("/move")
async def move(payload: MoveRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    target = move_entry(payload.workspace, payload.source, payload.destination)
    return {"path": str(target), "status": "created"}


@router.post("/duplicate")
async def duplicate(payload: DuplicateRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    target = duplicate_entry(payload.workspace, payload.path, payload.destination)
    return {"path": str(target), "status": "created"}


@router.post("/write")
async def write(payload: WriteRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    write_file(payload.workspace, payload.path, payload.content)
    return {"status": "ok"}


@router.post("/reveal")
async def reveal(payload: RevealRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    reveal_entry(payload.workspace, payload.path)
    return {"status": "ok"}
