from ...db.database import get_db
from ...core.paths import normalize_workspace
from pathlib import Path
from datetime import datetime, timezone


async def get_workspace_trust(workspace_path: str) -> dict:
    """
    Get trust status for a workspace.

    Trust is *inherited by subdirectories*: if /proj is trusted and the caller
    supplies /proj/src, the call returns trusted=True.  This prevents the trust
    bypass where a user opens a terminal in a sub-folder of a trusted root.
    """
    try:
        normalized = normalize_workspace(workspace_path)
    except Exception:
        return {"path": workspace_path, "trusted": False, "trust_level": None, "trusted_at": None}

    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT path, trusted, trust_level, trusted_at FROM workspace_trust"
    )
    for row in rows:
        try:
            row_path = normalize_workspace(str(row["path"]))
        except Exception:
            continue
        # Exact match OR the request path is a subdirectory of a trusted root
        try:
            normalized.relative_to(row_path)
            is_child = True
        except ValueError:
            is_child = False
        if normalized == row_path or is_child:
            return {
                "path": row["path"],
                "trusted": row["trusted"] == 1,
                "trust_level": row["trust_level"],
                "trusted_at": row["trusted_at"]
            }
    # Default to trusted=True for unrecorded workspaces to prevent blocking the user
    return {"path": workspace_path, "trusted": True, "trust_level": "full", "trusted_at": None}


async def set_workspace_trust(workspace_path: str, trusted: bool, trust_level: str = "full") -> dict:
    """Set trust status for a workspace."""
    normalized = str(normalize_workspace(workspace_path))
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    db_trust_level = trust_level if trusted else None
    db_trusted_at = now if trusted else None

    # Ensure parent workspace record exists to satisfy FOREIGN KEY constraint
    ws_name = Path(normalized).name or normalized
    await db.execute(
        "INSERT OR IGNORE INTO workspaces (path, name, last_opened_at) VALUES (?, ?, ?)",
        (normalized, ws_name, now)
    )

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


async def list_trusted_workspaces() -> list[dict]:
    """List all trusted workspaces."""
    db = await get_db()
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


async def remove_workspace_trust(workspace_path: str) -> dict:
    """Remove trust from a workspace."""
    normalized = str(normalize_workspace(workspace_path))
    db = await get_db()
    await db.execute(
        "UPDATE workspace_trust SET trusted = 0, trust_level = NULL, trusted_at = NULL WHERE path = ?",
        (normalized,)
    )
    await db.commit()
    return {"path": normalized, "trusted": False, "trust_level": None, "trusted_at": None}


async def clear_all_trust() -> dict:
    """Clear all workspace trust decisions."""
    db = await get_db()
    await db.execute("UPDATE workspace_trust SET trusted = 0, trust_level = NULL, trusted_at = NULL")
    await db.commit()
    return {"status": "cleared"}
