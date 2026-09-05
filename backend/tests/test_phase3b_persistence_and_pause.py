from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pytest

from app.db.database import init_db, close_db, get_pool, get_db
from app.features.ai.harness.approval_coordinator import (
    request_approval,
    approve_action,
    reject_action,
    load_pending_approvals_from_db,
    get_all_pending_approvals,
    _pending_approvals,
)
from app.features.ai.job_service import (
    create_job,
    create_task,
    pause_job,
    resume_job,
    get_job,
)
from app.features.ai.provider_health import CircuitOpenError, RateLimitError
from app.features.ai.harness.tool_executor import handle_rate_limit_or_circuit_break
from app.features.ai.agents.base import TaskStatus


@pytest.mark.asyncio
async def test_persist_approval_survives_restart(tmp_path: Path):
    db_file = tmp_path / "test_approval_survives.sqlite3"
    await init_db(db_file)
    _pending_approvals.clear()

    # 1. Request approval in session 1
    action_id = "act_test_survive_1"
    await request_approval(
        action_id=action_id,
        action_type="command",
        detail="rm -rf /tmp/cache",
        reason="Cleaning build cache",
        task_id="task_123",
        workspace=str(tmp_path),
        command="rm -rf /tmp/cache"
    )

    # Verify present in memory
    assert action_id in _pending_approvals

    # 2. Simulate backend restart by wiping memory and reloading from DB
    _pending_approvals.clear()
    assert len(_pending_approvals) == 0

    reloaded = await load_pending_approvals_from_db()
    assert len(reloaded) == 1
    assert reloaded[0]["action_id"] == action_id
    assert action_id in _pending_approvals
    assert _pending_approvals[action_id].detail == "rm -rf /tmp/cache"

    await close_db()


@pytest.mark.asyncio
async def test_approve_removes_from_db(tmp_path: Path):
    db_file = tmp_path / "test_approval_delete.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    _pending_approvals.clear()

    action_id = "act_test_del_1"
    await request_approval(
        action_id=action_id,
        action_type="edit",
        detail="Update config.py",
        reason="Updating port",
        workspace=str(tmp_path)
    )

    # Approve action
    approved = await approve_action(action_id)
    assert approved is True

    # Verify removed from memory
    assert action_id not in _pending_approvals

    # Verify removed from SQLite
    rows = await pool.read_query("SELECT action_id FROM pending_approvals WHERE action_id = ?", (action_id,))
    assert len(rows) == 0

    await close_db()


@pytest.mark.asyncio
async def test_expired_approvals_cleaned(tmp_path: Path):
    db_file = tmp_path / "test_approval_expire.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    _pending_approvals.clear()

    # Insert an expired approval (created 2 hours ago, expired 1 hour ago)
    old_action_id = "act_old_expired_1"
    now = time.time()
    await pool.write_execute(
        """
        INSERT INTO pending_approvals (action_id, task_id, workspace, action_type, payload_json, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (old_action_id, "task_old", str(tmp_path), "command", json.dumps({"detail": "old cmd"}), now - 7200, now - 3600)
    )

    # Insert a fresh active approval
    fresh_action_id = "act_fresh_active_1"
    await request_approval(
        action_id=fresh_action_id,
        action_type="command",
        detail="fresh cmd",
        reason="fresh reason",
        workspace=str(tmp_path)
    )

    # Reload from DB (which cleans expired)
    _pending_approvals.clear()
    active_approvals = await load_pending_approvals_from_db()

    # Expired should be purged; only fresh should remain
    action_ids = [a["action_id"] for a in active_approvals]
    assert fresh_action_id in action_ids
    assert old_action_id not in action_ids

    # Verify SQLite row was deleted
    rows = await pool.read_query("SELECT action_id FROM pending_approvals WHERE action_id = ?", (old_action_id,))
    assert len(rows) == 0

    await close_db()


@pytest.mark.asyncio
async def test_429_pauses_task(tmp_path: Path):
    db_file = tmp_path / "test_429_pause.sqlite3"
    await init_db(db_file)

    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))
    job_id = "job_429_test"
    task_id = "task_429_test"
    await create_job(job_id, str(tmp_path), "coder_workflow")
    await create_task(task_id, job_id, "Code Implementation", "Coder Agent", dependencies=[])

    # Simulate 429 RateLimitError
    err = RateLimitError("Groq 429 Too Many Requests: Rate limit exceeded", retry_after=120.0)
    handled = await handle_rate_limit_or_circuit_break(job_id, task_id, err)
    assert handled is True

    # Verify job status is paused and retry_after is recorded
    job_data = await get_job(job_id)
    assert job_data["status"] == "paused"
    assert "429" in job_data["pause_reason"]
    assert job_data["retry_after"] == 120.0

    await close_db()


@pytest.mark.asyncio
async def test_resume_paused_task(tmp_path: Path):
    db_file = tmp_path / "test_resume_task.sqlite3"
    await init_db(db_file)

    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))
    job_id = "job_resume_test"
    task_id = "task_resume_test"
    await create_job(job_id, str(tmp_path), "full_pipeline")
    await create_task(task_id, job_id, "Test Step", "Tester Agent", dependencies=[])

    # Pause job
    await pause_job(job_id, "Paused for testing rate limit", retry_after=60.0)
    job_data_paused = await get_job(job_id)
    assert job_data_paused["status"] == "paused"

    # Resume job
    resumed = await resume_job(job_id)
    assert resumed is True

    job_data_resumed = await get_job(job_id)
    assert job_data_resumed["status"] == "running"
    assert job_data_resumed["pause_reason"] == ""
    assert job_data_resumed["retry_after"] == 0.0

    await close_db()


@pytest.mark.asyncio
async def test_circuit_breaker_pauses_task(tmp_path: Path):
    db_file = tmp_path / "test_circuit_pause.sqlite3"
    await init_db(db_file)

    pool = await get_pool()
    await pool.write_execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (str(tmp_path), "test_ws"))
    job_id = "job_circuit_test"
    task_id = "task_circuit_test"
    await create_job(job_id, str(tmp_path), "audit_workflow")
    await create_task(task_id, job_id, "Security Audit", "Security Agent", dependencies=[])

    # Simulate CircuitOpenError
    circuit_err = CircuitOpenError("openai", cooldown_remaining=300.0)
    handled = await handle_rate_limit_or_circuit_break(job_id, task_id, circuit_err)
    assert handled is True

    job_data = await get_job(job_id)
    assert job_data["status"] == "paused"
    assert "Circuit breaker is OPEN" in job_data["pause_reason"]
    assert job_data["retry_after"] == 300.0

    await close_db()
