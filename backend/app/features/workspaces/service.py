from pathlib import Path
from datetime import datetime, timezone
import logging

from ...core.paths import ensure_directory, normalize_path
from ...db.database import get_db
from ..indexing.service import index_manager
from .file_watcher import watcher
from .schemas import WorkspaceDto

logger = logging.getLogger(__name__)


async def open_workspace(path: str) -> WorkspaceDto:
    logger.info("workspace.open requested path=%s", path)
    workspace_path = normalize_path(path)
    ensure_directory(workspace_path)
    logger.info("workspace.open validated path=%s exists=%s", workspace_path, workspace_path.exists())
    now_iso = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    await db.execute(
        """
        INSERT INTO workspaces(path, name, last_opened_at)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET last_opened_at = excluded.last_opened_at
        """,
        (str(workspace_path), workspace_path.name, now_iso),
    )
    await db.commit()

    watcher.watch(workspace_path)
    await index_manager.schedule(str(workspace_path), reason="workspace-open")
    logger.info("workspace.open stored and watcher requested path=%s", workspace_path)
    return WorkspaceDto(path=str(workspace_path), name=workspace_path.name, last_opened_at=now_iso)


async def list_recent_workspaces() -> list[WorkspaceDto]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT path, name, last_opened_at FROM workspaces ORDER BY last_opened_at DESC LIMIT 12"
    )
    existing: list[WorkspaceDto] = []
    for row in rows:
        if Path(row["path"]).exists() and Path(row["path"]).is_dir():
            existing.append(WorkspaceDto(path=row["path"], name=row["name"], last_opened_at=row["last_opened_at"]))
    return existing


async def cleanup_missing_workspaces() -> None:
    """Startup cleanup routine for workspace entries that no longer exist on disk."""
    db = await get_db()
    rows = await db.execute_fetchall("SELECT path FROM workspaces")
    missing = [row["path"] for row in rows if not (Path(row["path"]).exists() and Path(row["path"]).is_dir())]
    if missing:
        logger.warning("workspace.startup_cleanup removing missing paths=%s", missing)
        await remove_workspaces(missing)


async def get_last_workspace() -> WorkspaceDto | None:
    recent = await list_recent_workspaces()
    return recent[0] if recent else None


async def remove_workspaces(paths: list[str]) -> None:
    if not paths:
        return
    db = await get_db()
    await db.executemany("DELETE FROM workspaces WHERE path = ?", [(path,) for path in paths])
    await db.commit()


def workspace_name(path: str) -> str:
    return Path(path).name
