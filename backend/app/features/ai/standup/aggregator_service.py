"""
aggregator_service.py — Aggregates agent activity, git history, steps, and costs for standup reports.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.database import get_pool

logger = logging.getLogger(__name__)


def _get_git_commits(workspace_path: Path, since_timestamp: float) -> List[Dict[str, str]]:
    """Query git commits made in the workspace since given timestamp."""
    commits: List[Dict[str, str]] = []
    if not (workspace_path / ".git").exists():
        return commits

    try:
        since_iso = datetime.datetime.fromtimestamp(since_timestamp, tz=datetime.timezone.utc).isoformat()
        cmd = ["git", "log", f"--since={since_iso}", "--pretty=format:%h|%s|%an|%cI"]
        res = subprocess.run(
            cmd,
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 3:
                    commits.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "author": parts[2],
                        "date": parts[3] if len(parts) > 3 else "",
                    })
    except Exception as exc:
        logger.debug("Git log query exception: %s", exc)

    return commits


async def gather_yesterday_activity(workspace: str, date: Optional[str] = None) -> Dict[str, Any]:
    """
    Queries activity from agent_jobs, task_steps, cost_events, and git log.
    Returns: {
        "jobs_completed": [...],
        "files_modified": [...],
        "commits_made": [...],
        "tests_passed": int,
        "total_cost": "$X.XX",
        "total_tokens": int
    }
    """
    ws_path = Path(workspace)

    # Determine time window
    now = time.time()
    if date:
        try:
            # Parse specified date (e.g. YYYY-MM-DD)
            dt = datetime.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
            start_ts = dt.timestamp()
            end_ts = start_ts + 86400.0
        except Exception:
            start_ts = now - 86400.0
            end_ts = now
    else:
        # Last 24 hours
        start_ts = now - 86400.0
        end_ts = now

    start_iso = datetime.datetime.fromtimestamp(start_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_iso = datetime.datetime.fromtimestamp(end_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    jobs_completed: List[Dict[str, Any]] = []
    files_modified_set: set[str] = set()
    tests_passed = 0
    total_cost_usd = 0.0
    total_tokens = 0

    try:
        pool = await get_pool()
    except Exception:
        pool = None

    if pool is not None:
        try:
            # 1. Query agent_jobs with date range filter
            job_rows = await pool.read_query(
                """
                SELECT id, workflow, status, started_at, completed_at, token_usage, duration, files_modified, user_request
                FROM agent_jobs
                WHERE workspace = ? AND status = 'completed'
                  AND (
                    (completed_at IS NOT NULL AND completed_at >= ? AND completed_at <= ?)
                    OR (completed_at IS NULL AND started_at >= ? AND started_at <= ?)
                  )
                ORDER BY completed_at DESC
                LIMIT 50
                """,
                (workspace, start_ts, end_ts, start_ts, end_ts)
            )

            for r in job_rows:
                jobs_completed.append({
                    "id": r["id"],
                    "workflow": r["workflow"],
                    "status": r["status"],
                    "user_request": r["user_request"] or r["workflow"],
                    "duration": r["duration"],
                    "token_usage": r["token_usage"],
                })

                # Extract modified files
                try:
                    raw_files = r["files_modified"]
                    if raw_files:
                        flist = json.loads(raw_files)
                        if isinstance(flist, list):
                            for f in flist:
                                files_modified_set.add(str(f))
                except Exception:
                    pass

            # 2. Query task_steps for test completions and steps
            step_rows = await pool.read_query(
                """
                SELECT id, step_type, status, result_json
                FROM task_steps
                WHERE status = 'completed' AND created_at >= ?
                """,
                (start_ts,)
            )

            for sr in step_rows:
                stype = sr["step_type"].lower()
                r_json = sr["result_json"] or ""
                if "test" in stype or "verify" in stype or "passed" in r_json.lower():
                    tests_passed += 1

            # 3. Query cost_events
            cost_rows = await pool.read_query(
                """
                SELECT COALESCE(SUM(cost_usd), 0.0) as total_usd,
                       COALESCE(SUM(input_tokens + output_tokens), 0) as total_toks
                FROM cost_events
                WHERE workspace = ? AND timestamp >= ?
                """,
                (workspace, start_ts)
            )
            if cost_rows:
                total_cost_usd = float(cost_rows[0]["total_usd"] or 0.0)
                total_tokens = int(cost_rows[0]["total_toks"] or 0)
        except Exception as exc:
            logger.warning("Database activity aggregation warning: %s", exc)

    # 4. Git commits
    commits_made = _get_git_commits(ws_path, start_ts)

    # Format output
    return {
        "jobs_completed": jobs_completed,
        "files_modified": sorted(list(files_modified_set)),
        "commits_made": commits_made,
        "tests_passed": tests_passed,
        "total_cost": f"${total_cost_usd:.2f}",
        "total_tokens": total_tokens,
    }
