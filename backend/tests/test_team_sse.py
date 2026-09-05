from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
import pytest
import pytest_asyncio
import httpx

from app.core.paths import normalize_path
from app.db.database import get_pool
from app.features.ai.job_service import (
    add_team_message,
    create_job,
    create_task,
    get_agent_metrics,
    get_job,
    get_team_messages,
    record_agent_token_usage,
)
from app.features.ai.step_tracker import (
    get_task_progress_by_role,
    get_last_completed_step_by_role,
    log_step_pending,
    mark_step_running,
    mark_step_completed,
)
from app.features.ai.team.team_routes import broadcast_team_event, get_or_create_active_job
from app.features.workspaces.trust_service import set_workspace_trust


# ── Test 1: Team Messages Persist to DB ───────────────────────────────────────

@pytest.mark.asyncio
async def test_team_messages_persist_to_db(temp_db, tmp_path: Path):
    """Write team messages to SQLite and verify round-trip persistence and order."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))

    job_id = "job_msg_persist_1"
    await create_job(job_id, ws_path, "team_mode")

    # 1. Add messages from different agent roles
    id1 = await add_team_message(
        job_id=job_id,
        sender_role="architect",
        recipient_role="all",
        message_type="decision",
        content="Architecture design finalized with 3 modules.",
        artifact_json=json.dumps({"modules": ["auth", "data", "ui"]}),
        token_usage=350,
        cost_usd=0.005,
    )
    assert id1 is not None and id1 > 0

    id2 = await add_team_message(
        job_id=job_id,
        sender_role="coder",
        recipient_role="reviewer",
        message_type="handoff",
        content="Implementation complete for auth module.",
        artifact_json=json.dumps({"files": ["auth.py"]}),
        token_usage=720,
        cost_usd=0.012,
    )
    assert id2 > id1

    # 2. Retrieve messages
    messages = await get_team_messages(job_id, limit=50)
    assert len(messages) == 2
    assert messages[0]["id"] == id1
    assert messages[0]["sender_role"] == "architect"
    assert messages[0]["message_type"] == "decision"
    assert "Architecture design" in messages[0]["content"]

    assert messages[1]["id"] == id2
    assert messages[1]["sender_role"] == "coder"
    assert messages[1]["recipient_role"] == "reviewer"
    assert messages[1]["token_usage"] == 720


# ── Test 2: SSE Stream Emits Typed Events (All 7 Event Types) ─────────────────

@pytest.mark.asyncio
async def test_sse_stream_emits_typed_events(async_client: httpx.AsyncClient, temp_db, tmp_path: Path):
    """SSE endpoint /api/team/jobs/{id}/events delivers all 7 typed events + snapshot."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))
    job_id = "job_sse_stream_1"
    await create_job(job_id, ws_path, "team_mode")

    active_job = get_or_create_active_job(job_id, workspace=ws_path)

    # Connect to the SSE endpoint
    received_events: list[dict] = []

    async def _listen_stream():
        async with async_client.stream("GET", f"/api/team/jobs/{job_id}/events") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            current_event = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    current_event = line.split("event:", 1)[1].strip()
                elif line.startswith("data:") and current_event:
                    raw_data = line.split("data:", 1)[1].strip()
                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        data = raw_data
                    received_events.append({"event": current_event, "data": data})
                    current_event = None
                    if len(received_events) >= 8:  # 1 snapshot + 7 typed events
                        break

    listener_task = asyncio.create_task(_listen_stream())

    # Wait until listener attaches to active_job.subscribers
    for _ in range(50):
        if len(active_job.subscribers) > 0:
            break
        await asyncio.sleep(0.02)

    # Broadcast all 7 required team event types
    events_to_emit = [
        ("team_status", {"status": "running", "job_id": job_id}),
        ("team_step_update", {"task_id": "t1", "status": "running", "role": "coder"}),
        ("team_message", {"sender_role": "coder", "content": "Writing tests..."}),
        ("team_handoff", {"from_role": "coder", "to_role": "tester", "type": "diffs", "summary": "Diff ready"}),
        ("team_approval", {"action_id": "act_42", "agent_role": "devops", "command": "npm run build"}),
        ("team_repair", {"round": 1, "max_rounds": 3, "reason": "Test failed"}),
        ("team_metrics", {"total_tokens": 1200, "cost_usd": 0.02}),
    ]

    for ev_name, ev_data in events_to_emit:
        broadcast_team_event(job_id, ev_name, ev_data)
        await asyncio.sleep(0.01)

    # Emit close signal so SSE stream finishes cleanly
    broadcast_team_event(job_id, "team_close", {})

    await asyncio.wait_for(listener_task, timeout=4.0)

    event_names = [e["event"] for e in received_events]
    assert "team_snapshot" in event_names
    assert "team_status" in event_names
    assert "team_step_update" in event_names
    assert "team_message" in event_names
    assert "team_handoff" in event_names
    assert "team_approval" in event_names
    assert "team_repair" in event_names
    assert "team_metrics" in event_names


# ── Test 3: Snapshot on Reconnect ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snapshot_on_reconnect(async_client: httpx.AsyncClient, temp_db, tmp_path: Path):
    """GET /api/team/jobs/{id}/snapshot returns full state and initial SSE connection receives it."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))
    job_id = "job_snapshot_1"
    await create_job(job_id, ws_path, "team_mode", user_request="Build authentication system")
    await create_task("t_snap_1", job_id, "Plan Architecture", "architect", dependencies=[])

    await add_team_message(
        job_id=job_id,
        sender_role="architect",
        message_type="chat",
        content="Planning auth system structure...",
    )

    # 1. Test REST endpoint GET /api/team/jobs/{id}/snapshot
    res = await async_client.get(f"/api/team/jobs/{job_id}/snapshot")
    assert res.status_code == 200
    snap = res.json()
    assert snap["job_id"] == job_id
    assert snap["job"]["user_request"] == "Build authentication system"
    assert len(snap["messages"]) >= 1
    assert snap["messages"][0]["content"] == "Planning auth system structure..."

    # 2. Test initial snapshot delivered on SSE connect
    first_event = None
    async with async_client.stream("GET", f"/api/team/jobs/{job_id}/events?snapshot_only=true") as response:
        assert response.status_code == 200
        current_event = None
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                current_event = line.split("event:", 1)[1].strip()
            elif line.startswith("data:") and current_event:
                raw = line.split("data:", 1)[1].strip()
                first_event = {"event": current_event, "data": json.loads(raw)}
                break

    assert first_event is not None
    assert first_event["event"] == "team_snapshot"
    assert first_event["data"]["job_id"] == job_id
    assert len(first_event["data"]["messages"]) >= 1


# ── Test 4: Operator Mid-Run Injection ────────────────────────────────────────

@pytest.mark.asyncio
async def test_operator_injection(async_client: httpx.AsyncClient, temp_db, tmp_path: Path):
    """POST /api/team/jobs/{id}/inject records operator message and targets agent role."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))
    job_id = "job_inject_1"
    await create_job(job_id, ws_path, "team_mode")

    # Operator injects instruction targeting 'coder'
    injection_payload = {
        "prompt": "Use argon2 for password hashing instead of bcrypt.",
        "target_role": "coder",
    }
    resp = await async_client.post(f"/api/team/jobs/{job_id}/inject", json=injection_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["target_role"] == "coder"
    assert "argon2" in data["content"]

    # Verify message persisted in team_messages
    messages = await get_team_messages(job_id)
    assert len(messages) == 1
    msg = messages[0]
    assert msg["sender_role"] == "operator"
    assert msg["recipient_role"] == "coder"
    assert msg["message_type"] == "injection"
    assert "argon2" in msg["content"]


# ── Test 5: Per-Agent Token and Cost Metrics ──────────────────────────────────

@pytest.mark.asyncio
async def test_per_agent_metrics(temp_db, tmp_path: Path):
    """Record token usage across roles and verify per-role aggregated metrics & step progress."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))
    job_id = "job_metrics_1"
    await create_job(job_id, ws_path, "team_mode")

    # Record usage for multiple roles
    await record_agent_token_usage(job_id, "t1", "architect", input_tokens=1000, output_tokens=500, cost_usd=0.0075)
    await record_agent_token_usage(job_id, "t2", "coder", input_tokens=3000, output_tokens=1500, cost_usd=0.0315)
    await record_agent_token_usage(job_id, "t2", "coder", input_tokens=1000, output_tokens=500, cost_usd=0.0105)
    await record_agent_token_usage(job_id, "t3", "tester", input_tokens=800, output_tokens=200, cost_usd=0.001)

    metrics = await get_agent_metrics(job_id)

    assert "architect" in metrics
    assert metrics["architect"]["total_tokens"] == 1500
    assert metrics["architect"]["total_cost"] == 0.0075

    assert "coder" in metrics
    assert metrics["coder"]["total_tokens"] == 6000
    assert abs(metrics["coder"]["total_cost"] - 0.042) < 1e-4
    assert metrics["coder"]["message_count"] == 2

    assert "tester" in metrics
    assert metrics["tester"]["total_tokens"] == 1000

    # Also verify role progress helpers in step_tracker.py
    await create_task("t_code", job_id, "Code implementation", "coder", dependencies=[])
    await create_task("t_test", job_id, "Test verification", "tester", dependencies=[])

    s1 = await log_step_pending("t_code", job_id, 1, "team_role_coder", {"cmd": "write"})
    await mark_step_running(s1)
    await mark_step_completed(s1, {"done": True})

    s2 = await log_step_pending("t_test", job_id, 1, "team_role_tester", {"cmd": "pytest"})
    await mark_step_running(s2)

    role_progress = await get_task_progress_by_role(job_id)
    assert "coder" in role_progress
    assert role_progress["coder"]["completed"] == 1
    assert "tester" in role_progress
    assert role_progress["tester"]["running"] == 1

    last_step = await get_last_completed_step_by_role(job_id, "coder")
    assert last_step == 1


# ── Test 6: Job Pause, Resume, and Cancel State Transitions ───────────────────

@pytest.mark.asyncio
async def test_job_pause_resume_cancel(async_client: httpx.AsyncClient, temp_db, tmp_path: Path):
    """Verify pause, resume, and cancel endpoints execute proper state transitions."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))
    await set_workspace_trust(ws_path, trusted=True)

    job_id = "job_life_cycle_1"
    await create_job(job_id, ws_path, "team_mode")

    # 1. Pause
    p_resp = await async_client.post(f"/api/team/jobs/{job_id}/pause")
    assert p_resp.status_code == 200
    assert p_resp.json()["status"] == "paused"
    job = await get_job(job_id)
    assert job["status"] == "paused"

    # 2. Resume
    r_resp = await async_client.post(f"/api/team/jobs/{job_id}/resume")
    assert r_resp.status_code == 200
    assert r_resp.json()["status"] == "running"
    job = await get_job(job_id)
    assert job["status"] == "running"

    # 3. Cancel
    c_resp = await async_client.post(f"/api/team/jobs/{job_id}/cancel")
    assert c_resp.status_code == 200
    assert c_resp.json()["status"] == "cancelled"
    job = await get_job(job_id)
    assert job["status"] == "cancelled"


# ── Test 7: Urgent Operator Injection & Handoffs Retrieval ───────────────────

@pytest.mark.asyncio
async def test_urgent_operator_injection_and_handoffs(async_client: httpx.AsyncClient, temp_db, tmp_path: Path):
    """Verify urgent operator injection triggers acknowledgment and GET /handoffs returns artifacts."""
    pool = await get_pool()
    ws_path = str(normalize_path(str(tmp_path)))
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_path, "ws"))
    job_id = "job_urgent_handoff_1"
    await create_job(job_id, ws_path, "team_mode")

    # 1. Urgent injection
    urgent_payload = {
        "prompt": "Urgent: stop and review security vulnerability in auth",
        "target_role": "reviewer",
        "urgent": True,
    }
    resp = await async_client.post(f"/api/team/jobs/{job_id}/inject", json=urgent_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["urgent"] is True
    assert data["acknowledged"] is True

    # Check messages: operator injection + acknowledgment from reviewer
    messages = await get_team_messages(job_id)
    assert len(messages) == 2
    op_msg = next(m for m in messages if m["sender_role"] == "operator")
    ack_msg = next(m for m in messages if m["sender_role"] == "reviewer")
    assert "Urgent: stop and review" in op_msg["content"]
    assert "Acknowledged by [Reviewer]" in ack_msg["content"]

    # 2. Add a handoff message to DB
    handoff_meta = {
        "type": "diffs",
        "from_role": "coder",
        "to_role": "reviewer",
        "summary": "Transferred secure auth diff",
        "payload": {"files": ["auth.py"]},
    }
    await add_team_message(
        job_id=job_id,
        sender_role="coder",
        recipient_role="reviewer",
        message_type="handoff",
        content="Transferred secure auth diff",
        artifact_json=json.dumps(handoff_meta),
        task_id="t_auth_1",
    )

    # 3. Query GET /api/team/jobs/{job_id}/handoffs
    h_resp = await async_client.get(f"/api/team/jobs/{job_id}/handoffs")
    assert h_resp.status_code == 200
    h_data = h_resp.json()
    assert h_data["job_id"] == job_id
    assert h_data["count"] >= 1
    found = next((h for h in h_data["handoffs"] if h["summary"] == "Transferred secure auth diff"), None)
    assert found is not None
    assert found["from_role"] == "coder"
    assert found["to_role"] == "reviewer"
    assert found["type"] == "diffs"
