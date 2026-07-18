from backend.app.db.database import get_connection
from backend.app.core.paths import normalize_path

async def get_all_memory(workspace: str) -> dict[str, str]:
    workspace_path = str(normalize_path(workspace))
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT key, value FROM repo_memory WHERE workspace = ?", (workspace_path,))
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        await db.close()

async def get_memory_key(workspace: str, key: str) -> str | None:
    workspace_path = str(normalize_path(workspace))
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT value FROM repo_memory WHERE workspace = ? AND key = ?", (workspace_path, key))
        row = await cursor.fetchone()
        return row["value"] if row else None
    finally:
        await db.close()

async def save_memory_key(workspace: str, key: str, value: str) -> None:
    workspace_path = str(normalize_path(workspace))
    db = await get_connection()
    try:
        await db.execute(
            """
            INSERT INTO repo_memory(workspace, key, value) VALUES (?, ?, ?)
            ON CONFLICT(workspace, key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (workspace_path, key, value)
        )
        await db.commit()
    finally:
        await db.close()

async def clear_memory(workspace: str) -> None:
    workspace_path = str(normalize_path(workspace))
    db = await get_connection()
    try:
        await db.execute("DELETE FROM repo_memory WHERE workspace = ?", (workspace_path,))
        await db.commit()
    finally:
        await db.close()
