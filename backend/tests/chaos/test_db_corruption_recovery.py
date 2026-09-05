from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task


@pytest.mark.asyncio
async def test_db_corruption_recovery(tmp_path: Path):
    """Simulate database file corruption, verify clean recreate and no crash loop."""
    db_file = tmp_path / "chaos_corrupt.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "corrupt_ws"))

    job_id = "job_corrupt_test"
    await create_job(job_id, str(tmp_path), "test_flow")
    await create_task("task_corrupt_1", job_id, "Corrupt Test", "Coder Agent", dependencies=[])

    await close_db()

    # Corrupt the DB file by overwriting with invalid garbage data
    with open(db_file, "wb") as f:
        f.write(b"CORRUPTED_GARBAGE_DATA_HEADER_INVALID_SQLITE_FORMAT")

    # Re-initialization triggers automatic corruption recovery without crash loop
    await init_db(db_file)

    # Verify database is operational and schema tables exist
    pool2 = await get_pool()
    rows = await pool2.read_query("SELECT name FROM sqlite_master WHERE type='table' AND name='workspaces'")
    assert len(rows) == 1

    await close_db()
