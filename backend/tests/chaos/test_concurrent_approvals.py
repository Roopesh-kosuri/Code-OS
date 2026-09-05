from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.harness.approval_coordinator import (
    request_approval,
    load_pending_approvals_from_db,
    get_all_pending_approvals,
    _pending_approvals,
)


@pytest.mark.asyncio
async def test_concurrent_approvals(tmp_path: Path):
    """Request 10 approvals concurrently, crash backend, reboot,
    and verify all 10 approvals resurface without duplicates."""
    db_file = tmp_path / "chaos_concurrent_approvals.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "approval_ws"))
    _pending_approvals.clear()

    # Request 10 approvals concurrently
    async def create_approval(i: int):
        return await request_approval(
            action_id=f"act_conc_{i}",
            action_type="command",
            detail=f"rm -rf /cache/{i}",
            reason=f"Clear cache {i}",
            task_id=f"task_appr_{i}",
            workspace=str(tmp_path),
            command=f"rm -rf /cache/{i}",
        )

    approvals = await asyncio.gather(*[create_approval(i) for i in range(10)])
    assert len(approvals) == 10
    assert len(_pending_approvals) == 10

    # --- SIMULATE CRASH & REBOOT ---
    _pending_approvals.clear()
    await close_db()
    await init_db(db_file)

    reloaded = await load_pending_approvals_from_db()
    assert len(reloaded) == 10

    # Verify all 10 unique IDs are present with no duplicates
    reloaded_ids = [a["action_id"] for a in reloaded]
    assert len(set(reloaded_ids)) == 10
    for i in range(10):
        assert f"act_conc_{i}" in reloaded_ids

    # Query via API function
    all_active = await get_all_pending_approvals(str(tmp_path))
    assert len(all_active) == 10

    await close_db()
