"""
Unit tests for Session Replay, Timeline Scrubber, Forking & Transcript Export.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.db.database import get_db, init_db, close_db
from app.features.ai.session.session_store import (
    get_session_list,
    get_session_timeline,
    get_session_snapshot,
    fork_session,
    export_session,
    export_session_transcript,
)


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path: Path):
    db_file = tmp_path / "test_session_replay.db"
    await init_db(db_file)
    yield
    await close_db()


@pytest.mark.asyncio
async def test_get_session_list_returns_recent_jobs():
    """Verify session listing retrieves jobs with duration, step counts, and costs."""
    db = await get_db()
    ws = "/test/workspace/sessions"
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "WS"))

    now_iso = datetime.now(timezone.utc).isoformat()
    # Insert 2 jobs
    await db.execute(
        """
        INSERT INTO agent_jobs (
            id, workspace, workflow, status, started_at, completed_at,
            token_usage, duration, files_modified, errors, logs,
            workspace_manifest, user_request
        ) VALUES (
            'job-101', ?, 'calculator-build', 'completed', ?, ?,
            12000, 42.5, '["calc.py"]', '', '["started", "done"]', '{}', 'Build 4-lang calculator'
        )
        """,
        (ws, now_iso, now_iso),
    )

    await db.execute(
        """
        INSERT INTO agent_jobs (
            id, workspace, workflow, status, started_at, completed_at,
            token_usage, duration, files_modified, errors, logs,
            workspace_manifest, user_request
        ) VALUES (
            'job-102', ?, 'web-scraper', 'running', ?, NULL,
            5000, 15.2, '[]', '', '["crawling"]', '{}', 'Scrape pricing data'
        )
        """,
        (ws, now_iso),
    )

    # Insert cost events
    await db.execute(
        """
        INSERT INTO cost_events (id, workspace, job_id, provider, model, input_tokens, output_tokens, cost_usd, timestamp)
        VALUES ('ce-1', ?, 'job-101', 'groq', 'llama-3.3-70b', 6000, 6000, 0.0082, ?)
        """,
        (ws, time.time()),
    )

    # Insert agent_task first for FK
    await db.execute(
        """
        INSERT INTO agent_tasks (id, job_id, title, agent_role, status)
        VALUES ('t-1', 'job-101', 'Init plan', 'architect', 'completed')
        """
    )

    # Insert task_steps
    await db.execute(
        """
        INSERT INTO task_steps (id, task_id, job_id, step_num, step_type, status, payload_hash, result_json, created_at, updated_at)
        VALUES ('step-1', 't-1', 'job-101', 1, 'team_role_architect', 'completed', 'h1', '{"plan": "init"}', ?, ?)
        """,
        (time.time(), time.time()),
    )
    await db.commit()

    sessions = await get_session_list(workspace=ws, limit=10)
    assert len(sessions) == 2

    j101 = next(s for s in sessions if s["job_id"] == "job-101")
    assert j101["title"] == "Build 4-lang calculator"
    assert j101["status"] == "completed"
    assert j101["duration"] == 42.5
    assert j101["step_count"] >= 1
    assert j101["cost_usd"] > 0.0


@pytest.mark.asyncio
async def test_get_session_timeline_includes_all_steps():
    """Verify timeline collation returns chronological steps with tool calls, files, and thoughts."""
    db = await get_db()
    ws = "/test/timeline"
    job_id = "job-timeline-1"
    now = time.time()

    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "WS"))
    await db.execute(
        """
        INSERT INTO agent_jobs (id, workspace, workflow, status, started_at, token_usage, duration, logs)
        VALUES (?, ?, 'full-pipeline', 'completed', ?, 15000, 60.0, '[]')
        """,
        (job_id, ws, datetime.now(timezone.utc).isoformat()),
    )

    # Insert agent_tasks for FK
    await db.execute("INSERT INTO agent_tasks (id, job_id, title, agent_role, status) VALUES ('t-plan', ?, 'Plan', 'architect', 'completed')", (job_id,))
    await db.execute("INSERT INTO agent_tasks (id, job_id, title, agent_role, status) VALUES ('t-code', ?, 'Code', 'coder', 'completed')", (job_id,))
    await db.execute("INSERT INTO agent_tasks (id, job_id, title, agent_role, status) VALUES ('t-test', ?, 'Test', 'tester', 'completed')", (job_id,))

    # Step 1: Architect planning
    step1_result = {
        "tool": "create_plan",
        "reasoning": "Designing component modular architecture",
        "output": {"modules": ["engine", "gui", "cli"]},
    }
    await db.execute(
        """
        INSERT INTO task_steps (id, task_id, job_id, step_num, step_type, status, payload_hash, result_json, created_at, updated_at)
        VALUES ('step-t1', 't-plan', ?, 1, 'team_role_architect', 'completed', 'h1', ?, ?, ?)
        """,
        (job_id, json.dumps(step1_result), now, now),
    )

    # Step 2: Coder file writes
    step2_result = {
        "tool": "write_to_file",
        "thinking": "Writing calculator engine logic",
        "proposals": [{"path": "calc.py", "original": "", "updated": "def add(a, b): return a + b"}],
        "output": {"success": True, "bytes": 35},
    }
    await db.execute(
        """
        INSERT INTO task_steps (id, task_id, job_id, step_num, step_type, status, payload_hash, result_json, created_at, updated_at)
        VALUES ('step-t2', 't-code', ?, 2, 'team_role_coder', 'completed', 'h2', ?, ?, ?)
        """,
        (job_id, json.dumps(step2_result), now + 1, now + 1),
    )

    # Step 3: Tester verification
    step3_result = {
        "tool": "run_command",
        "thinking": "Verifying calculation tests pass",
        "output": {"stdout": "1 passed in 0.02s", "exit_code": 0},
    }
    await db.execute(
        """
        INSERT INTO task_steps (id, task_id, job_id, step_num, step_type, status, payload_hash, result_json, created_at, updated_at)
        VALUES ('step-t3', 't-test', ?, 3, 'team_role_tester', 'completed', 'h3', ?, ?, ?)
        """,
        (job_id, json.dumps(step3_result), now + 2, now + 2),
    )
    await db.commit()

    timeline = await get_session_timeline(job_id)
    assert len(timeline) == 3

    assert timeline[0]["agent_role"] == "architect"
    assert timeline[0]["thinking"] == "Designing component modular architecture"

    assert timeline[1]["agent_role"] == "coder"
    assert timeline[1]["action_type"] == "file_edit"
    assert len(timeline[1]["file_changes"]) == 1
    assert timeline[1]["file_changes"][0]["path"] == "calc.py"

    assert timeline[2]["agent_role"] == "tester"
    assert timeline[2]["action_type"] == "test_run"


@pytest.mark.asyncio
async def test_get_session_snapshot_at_specific_step():
    """Verify snapshot reconstructs exact state, prior messages, and manifest at step 2."""
    db = await get_db()
    ws = "/test/snapshot"
    job_id = "job-snap-1"
    now = time.time()

    manifest_data = {
        "calc.py": {
            "path": "calc.py",
            "purpose": "Math core",
            "created_by_task_id": "t-1",
            "agent_role": "coder",
        }
    }

    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "WS"))
    await db.execute(
        """
        INSERT INTO agent_jobs (id, workspace, workflow, status, started_at, workspace_manifest, user_request)
        VALUES (?, ?, 'calc-flow', 'completed', ?, ?, 'Build calculator')
        """,
        (job_id, ws, datetime.now(timezone.utc).isoformat(), json.dumps(manifest_data)),
    )

    # Insert tasks and 3 steps
    for i in range(1, 4):
        await db.execute(
            "INSERT INTO agent_tasks (id, job_id, title, agent_role, status) VALUES (?, ?, ?, 'coder', 'completed')",
            (f"t-{i}", job_id, f"Task {i}"),
        )
        res = {
            "tool": f"tool_{i}",
            "thinking": f"Reasoning for step {i}",
            "file_changes": [{"path": f"file_{i}.py", "updated": f"# v{i}"}],
        }
        await db.execute(
            """
            INSERT INTO task_steps (id, task_id, job_id, step_num, step_type, status, payload_hash, result_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'tool_call', 'completed', 'h', ?, ?, ?)
            """,
            (f"step-{i}", f"t-{i}", job_id, i, json.dumps(res), now + i, now + i),
        )
    await db.commit()

    # Query snapshot specifically at step 2
    snap = await get_session_snapshot(job_id, step_id="step-2")
    assert snap["job_id"] == job_id
    assert snap["step_num"] == 2
    assert len(snap["messages"]) == 2  # messages from step 1 and step 2
    assert any(c["path"] == "file_2.py" for c in snap["staged_changes"])
    assert not any(c["path"] == "file_3.py" for c in snap["staged_changes"])
    assert "calc.py" in snap["workspace_manifest"]


@pytest.mark.asyncio
async def test_fork_session_clones_state_and_executes():
    """Verify forking clones preceding history into a new job with new directive prompt."""
    db = await get_db()
    ws = "/test/fork"
    orig_id = "job-orig-1"
    now = time.time()

    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "WS"))
    await db.execute(
        """
        INSERT INTO agent_jobs (id, workspace, workflow, status, started_at, user_request, workspace_manifest)
        VALUES (?, ?, 'orig-workflow', 'completed', ?, 'Initial prompt', '{"core.py": {}}')
        """,
        (orig_id, ws, datetime.now(timezone.utc).isoformat()),
    )

    # Add tasks and 2 completed steps
    for i in range(1, 3):
        await db.execute(
            "INSERT INTO agent_tasks (id, job_id, title, agent_role, status) VALUES (?, ?, ?, 'coder', 'completed')",
            (f"t-{i}", orig_id, f"Task {i}"),
        )
        res = {"tool": f"step_tool_{i}", "thinking": f"Idea {i}", "output": f"ok {i}"}
        await db.execute(
            """
            INSERT INTO task_steps (id, task_id, job_id, step_num, step_type, status, payload_hash, result_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'team_role_coder', 'completed', 'h', ?, ?, ?)
            """,
            (f"orig-s{i}", f"t-{i}", orig_id, i, json.dumps(res), now + i, now + i),
        )
    await db.commit()

    # Fork from step 1 with a new instruction
    fork_result = await fork_session(
        original_job_id=orig_id,
        step_id="orig-s1",
        new_prompt="Refactor using Rust instead of Python",
    )

    assert fork_result["job_id"].startswith("job_fork_")
    assert fork_result["original_job_id"] == orig_id
    assert fork_result["step_id"] == "orig-s1"
    assert fork_result["status"] == "running"

    # Verify new job in agent_jobs
    cur = await db.execute("SELECT * FROM agent_jobs WHERE id = ?", (fork_result["job_id"],))
    new_job = await cur.fetchone()
    await cur.close()
    assert new_job is not None
    assert new_job["user_request"] == "Refactor using Rust instead of Python"

    # Verify cloned steps exist for the new job
    s_cur = await db.execute("SELECT * FROM task_steps WHERE job_id = ? ORDER BY step_num ASC", (fork_result["job_id"],))
    cloned_steps = await s_cur.fetchall()
    await s_cur.close()
    assert len(cloned_steps) == 2  # step 1 (cloned) + step 2 (fork instruction)
    assert cloned_steps[0]["step_num"] == 1
    assert cloned_steps[1]["step_type"] == "fork_instruction"


@pytest.mark.asyncio
async def test_export_session_as_markdown():
    """Verify exporting session to Markdown produces structured report."""
    timeline = [
        {
            "step_num": 1,
            "agent_role": "architect",
            "action_type": "planning",
            "tool_name": "generate_spec",
            "status": "completed",
            "thinking": "Outlining microservices",
            "input": {"spec": "v1"},
            "output": {"result": "Architecture approved"},
            "file_changes": [{"path": "arch.md"}],
            "cost_usd": 0.005,
        },
        {
            "step_num": 2,
            "agent_role": "tester",
            "action_type": "test_run",
            "tool_name": "pytest",
            "status": "completed",
            "thinking": "Checking test coverage",
            "input": {"cmd": "pytest"},
            "output": {"passed": 12},
            "file_changes": [],
            "cost_usd": 0.003,
        },
    ]
    job_meta = {
        "id": "job-export-md",
        "user_request": "Build full auth system",
        "status": "completed",
        "started_at": "2026-09-06T12:00:00Z",
        "duration": 55.4,
        "token_usage": 8500,
    }

    md = export_session_transcript("job-export-md", timeline, job_meta, format="markdown")
    assert "# Session Replay: Build full auth system" in md
    assert "| **Job ID** | `job-export-md` |" in md
    assert "| 1 | `ARCHITECT` | planning | `generate_spec` | completed |" in md
    assert "### Step 1: [ARCHITECT] generate_spec" in md
    assert "Outlining microservices" in md
    assert "### Step 2: [TESTER] pytest" in md


@pytest.mark.asyncio
async def test_export_session_as_json():
    """Verify exporting session to JSON produces valid parseable dictionary."""
    timeline = [
        {
            "step_num": 1,
            "agent_role": "coder",
            "action_type": "file_edit",
            "tool_name": "write_to_file",
            "status": "completed",
            "output": {"success": True},
        }
    ]
    job_meta = {
        "id": "job-export-json",
        "user_request": "Deploy API",
        "status": "completed",
    }

    json_str = export_session_transcript("job-export-json", timeline, job_meta, format="json")
    data = json.loads(json_str)
    assert data["job_id"] == "job-export-json"
    assert data["total_steps"] == 1
    assert data["timeline"][0]["agent_role"] == "coder"
    assert "exported_at" in data
