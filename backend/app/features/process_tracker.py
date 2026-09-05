from __future__ import annotations

import logging
import time
from typing import Optional
import psutil

from ..db.database import get_pool

logger = logging.getLogger(__name__)


async def track_spawned_process(pid: int, process_type: str, workspace: str) -> None:
    """Record a spawned process in the database."""
    try:
        pool = await get_pool()
        await pool.write_execute(
            "INSERT OR REPLACE INTO spawned_processes (pid, process_type, workspace, spawned_at) VALUES (?, ?, ?, ?)",
            (pid, process_type, workspace, time.time()),
        )
        logger.debug("process_tracker: tracked PID %d (%s) in %s", pid, process_type, workspace)
    except Exception as exc:
        logger.warning("process_tracker: failed to track PID %d: %s", pid, exc)


async def untrack_process(pid: int) -> None:
    """Remove a process from tracking (called on clean shutdown)."""
    try:
        pool = await get_pool()
        await pool.write_execute("DELETE FROM spawned_processes WHERE pid = ?", (pid,))
        logger.debug("process_tracker: untracked PID %d", pid)
    except Exception as exc:
        logger.warning("process_tracker: failed to untrack PID %d: %s", pid, exc)


async def reap_orphaned_processes() -> int:
    """On startup, check tracked PIDs and kill orphans from dead sessions."""
    try:
        pool = await get_pool()
        rows = await pool.read_query("SELECT pid, process_type FROM spawned_processes")
    except Exception as exc:
        logger.warning("process_tracker: failed to read spawned_processes for reaping: %s", exc)
        return 0

    reaped = 0
    for row in rows:
        pid = row["pid"]
        process_type = row["process_type"]
        try:
            # Check if process still exists
            proc = psutil.Process(pid)
            if proc.is_running():
                logger.warning("Reaping orphaned %s process PID %d", process_type, pid)
                # Kill children first, then parent process
                for child in proc.children(recursive=True):
                    try:
                        child.terminate()
                    except Exception:
                        pass
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
                reaped += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process already dead or not accessible - clean up DB entry
            pass
        except Exception as exc:
            logger.error("Failed to reap PID %d: %s", pid, exc)

        # Remove from tracking table
        await untrack_process(pid)

    if reaped > 0:
        logger.info("Reaped %d orphaned processes", reaped)
    return reaped
