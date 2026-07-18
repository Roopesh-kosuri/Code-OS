from fastapi import APIRouter, Query

from backend.app.features.indexing.schemas import IndexStatusDto, IndexSummaryDto
from backend.app.features.indexing.service import get_index_status, get_index_summary, index_manager
from backend.app.features.indexing.repo_service import get_repo_summary, get_repo_graph

router = APIRouter()


@router.post("/run")
async def run_index(workspace: str = Query(...)) -> dict[str, str]:
    await index_manager.schedule(workspace, reason="manual")
    return {"status": "queued"}


@router.get("/status", response_model=IndexStatusDto | None)
async def status(workspace: str = Query(...)) -> IndexStatusDto | None:
    value = await get_index_status(workspace)
    return IndexStatusDto(**value) if value else None


@router.get("/summary", response_model=IndexSummaryDto)
async def summary(workspace: str = Query(...), limit: int = Query(50, ge=1, le=500)) -> IndexSummaryDto:
    value = await get_index_summary(workspace, limit)
    return IndexSummaryDto(**value)


@router.get("/repo/summary")
async def repo_summary(workspace: str = Query(...)) -> dict:
    return await get_repo_summary(workspace)


@router.get("/repo/graph")
async def repo_graph(workspace: str = Query(...)) -> dict:
    return await get_repo_graph(workspace)
