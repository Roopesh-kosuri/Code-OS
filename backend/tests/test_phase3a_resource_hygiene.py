from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
import psutil
import pytest

from app.db.database import init_db, close_db, get_pool, checkpoint_wal
from app.features.process_tracker import (
    track_spawned_process,
    untrack_process,
    reap_orphaned_processes,
)
from app.features.ai.harness.tool_executor import _read_file_cached, _file_read_cache


@pytest.mark.asyncio
async def test_track_untrack_process(tmp_path: Path):
    db_file = tmp_path / "test_tracker.sqlite3"
    await init_db(db_file)
    pool = await get_pool()

    # Track a test process
    test_pid = 999991
    await track_spawned_process(test_pid, "test_runner", str(tmp_path))

    rows = await pool.read_query("SELECT pid, process_type, workspace FROM spawned_processes WHERE pid = ?", (test_pid,))
    assert len(rows) == 1
    assert rows[0]["pid"] == test_pid
    assert rows[0]["process_type"] == "test_runner"

    # Untrack the process
    await untrack_process(test_pid)
    rows_after = await pool.read_query("SELECT pid FROM spawned_processes WHERE pid = ?", (test_pid,))
    assert len(rows_after) == 0

    await close_db()


@pytest.mark.asyncio
async def test_reap_orphaned_process(tmp_path: Path):
    db_file = tmp_path / "test_reap.sqlite3"
    await init_db(db_file)
    pool = await get_pool()

    # Spawn real background sleeping subprocess
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pid = proc.pid

    try:
        # Track in DB as orphaned process from previous crashed session
        await track_spawned_process(pid, "orphaned_worker", str(tmp_path))

        # Ensure it is currently alive
        assert psutil.pid_exists(pid)
        p = psutil.Process(pid)
        assert p.is_running()

        # Run orphan reaping
        reaped_count = await reap_orphaned_processes()
        assert reaped_count >= 1

        # Verify process is terminated
        await asyncio.sleep(0.5)
        is_running = False
        try:
            p_check = psutil.Process(pid)
            is_running = p_check.is_running() and p_check.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            is_running = False
        assert not is_running

        # Verify DB entry removed
        rows = await pool.read_query("SELECT pid FROM spawned_processes WHERE pid = ?", (pid,))
        assert len(rows) == 0
    finally:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass
        await close_db()


@pytest.mark.asyncio
async def test_reap_dead_process_cleanup(tmp_path: Path):
    db_file = tmp_path / "test_dead_reap.sqlite3"
    await init_db(db_file)
    pool = await get_pool()

    # Insert a non-existent PID
    fake_pid = 999998
    await track_spawned_process(fake_pid, "dead_runner", str(tmp_path))

    # Reaping should safely ignore non-existent process and untrack it
    reaped = await reap_orphaned_processes()
    assert reaped == 0

    rows = await pool.read_query("SELECT pid FROM spawned_processes WHERE pid = ?", (fake_pid,))
    assert len(rows) == 0

    await close_db()


@pytest.mark.asyncio
async def test_wal_checkpoint(tmp_path: Path):
    db_file = tmp_path / "test_wal.sqlite3"
    await init_db(db_file)
    pool = await get_pool()

    # Perform multiple writes to populate WAL
    for i in range(100):
        await pool.write_execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (f"key_{i}", f"value_{i}" * 100),
        )

    # Trigger WAL checkpoint
    await checkpoint_wal()

    # Read back to ensure data integrity
    rows = await pool.read_query("SELECT count(*) as cnt FROM settings WHERE key LIKE 'key_%'")
    assert rows[0]["cnt"] == 100

    await close_db()


def test_unbounded_list_audit(tmp_path: Path):
    _file_read_cache.clear()

    # Create dummy files and verify cache bounding at 1000 items
    test_file = tmp_path / "test_cache.py"
    test_file.write_text("print('hello')", encoding="utf-8")

    # Populate cache up to 1005 items
    for i in range(1005):
        f = tmp_path / f"file_{i}.txt"
        f.write_text(f"content {i}", encoding="utf-8")
        _read_file_cached(f)

    # Verify cache did not exceed 1000 items
    assert len(_file_read_cache) == 1000
    assert len(_file_read_cache) <= 1000
