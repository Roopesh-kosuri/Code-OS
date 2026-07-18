from backend.app.db.database import get_connection
from backend.app.core.paths import normalize_path
from pathlib import Path
from datetime import datetime, timezone


async def get_workspace_trust(workspace_path: str) -> dict:
    """Get trust status for a workspace."""
    normalized = str(normalize_path(workspace_path))
    db = await get_connection()
    try:
        cursor = await db.execute(
            "SELECT path, trusted, trust_level, trusted_at FROM workspace_trust WHERE path = ?",
            (normalized,)
        )
        row = await cursor.fetchone()
        if row:
            return {
                "path": row["path"],
                "trusted": row["trusted"] == 1,
                "trust_level": row["trust_level"],
                "trusted_at": row["trusted_at"]
            }
        return {"path": normalized, "trusted": False, "trust_level": None, "trusted_at": None}
    finally:
        await db.close()


async def set_workspace_trust(workspace_path: str, trusted: bool, trust_level: str = "full") -> dict:
    """Set trust status for a workspace."""
    normalized = str(normalize_path(workspace_path))
    db = await get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        db_trust_level = trust_level if trusted else None
        db_trusted_at = now if trusted else None
        await db.execute(
            """
            INSERT INTO workspace_trust (path, trusted, trust_level, trusted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET 
                trusted = excluded.trusted,
                trust_level = excluded.trust_level,
                trusted_at = excluded.trusted_at
            """,
            (normalized, 1 if trusted else 0, db_trust_level, db_trusted_at)
        )
        await db.commit()
        return {
            "path": normalized,
            "trusted": trusted,
            "trust_level": db_trust_level,
            "trusted_at": db_trusted_at
        }
    finally:
        await db.close()


async def list_trusted_workspaces() -> list[dict]:
    """List all trusted workspaces."""
    db = await get_connection()
    try:
        rows = await db.execute_fetchall(
            "SELECT path, trusted, trust_level, trusted_at FROM workspace_trust WHERE trusted = 1"
        )
        return [
            {
                "path": row["path"],
                "trusted": row["trusted"] == 1,
                "trust_level": row["trust_level"],
                "trusted_at": row["trusted_at"]
            }
            for row in rows
        ]
    finally:
        await db.close()


async def remove_workspace_trust(workspace_path: str) -> dict:
    """Remove trust from a workspace."""
    normalized = str(normalize_path(workspace_path))
    db = await get_connection()
    try:
        await db.execute(
            "UPDATE workspace_trust SET trusted = 0, trust_level = NULL, trusted_at = NULL WHERE path = ?",
            (normalized,)
        )
        await db.commit()
        return {"path": normalized, "trusted": False, "trust_level": None, "trusted_at": None}
    finally:
        await db.close()


async def clear_all_trust() -> dict:
    """Clear all workspace trust decisions."""
    db = await get_connection()
    try:
        await db.execute("UPDATE workspace_trust SET trusted = 0, trust_level = NULL, trusted_at = NULL")
        await db.commit()
        return {"status": "cleared"}
    finally:
        await db.close()
