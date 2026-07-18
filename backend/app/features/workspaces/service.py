from pathlib import Path
import logging

from backend.app.core.paths import ensure_directory, normalize_path
from backend.app.db.database import get_connection
from backend.app.features.indexing.service import index_manager
from backend.app.features.workspaces.file_watcher import watcher
from backend.app.features.workspaces.schemas import WorkspaceDto

logger = logging.getLogger(__name__)


async def open_workspace(path: str) -> WorkspaceDto:
    logger.info("workspace.open requested path=%s", path)
    workspace_path = normalize_path(path)
    ensure_directory(workspace_path)
    logger.info("workspace.open validated path=%s exists=%s", workspace_path, workspace_path.exists())
    db = await get_connection()
    try:
        await db.execute(
            """
            INSERT INTO workspaces(path, name, last_opened_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(path) DO UPDATE SET last_opened_at = CURRENT_TIMESTAMP
            """,
            (str(workspace_path), workspace_path.name),
        )
        await db.commit()
    finally:
        await db.close()

    watcher.watch(workspace_path)
    await index_manager.schedule(str(workspace_path), reason="workspace-open")
    logger.info("workspace.open stored and watcher requested path=%s", workspace_path)
    return WorkspaceDto(path=str(workspace_path), name=workspace_path.name, last_opened_at="now")


async def list_recent_workspaces() -> list[WorkspaceDto]:
    db = await get_connection()
    try:
        rows = await db.execute_fetchall(
            "SELECT path, name, last_opened_at FROM workspaces ORDER BY last_opened_at DESC LIMIT 12"
        )
    finally:
        await db.close()
    existing: list[WorkspaceDto] = []
    missing: list[str] = []
    for row in rows:
        if Path(row["path"]).exists() and Path(row["path"]).is_dir():
            existing.append(WorkspaceDto(path=row["path"], name=row["name"], last_opened_at=row["last_opened_at"]))
        else:
            missing.append(row["path"])
    if missing:
        logger.warning("workspace.recent removing missing paths=%s", missing)
        await remove_workspaces(missing)
    return existing


async def get_last_workspace() -> WorkspaceDto | None:
    recent = await list_recent_workspaces()
    return recent[0] if recent else None


async def remove_workspaces(paths: list[str]) -> None:
    if not paths:
        return
    db = await get_connection()
    try:
        await db.executemany("DELETE FROM workspaces WHERE path = ?", [(path,) for path in paths])
        await db.commit()
    finally:
        await db.close()


def workspace_name(path: str) -> str:
    return Path(path).name
