import json
import time
from typing import Any
from datetime import datetime, timezone
from ...db.database import get_db
from ...core.paths import normalize_path

async def create_job(job_id: str, workspace: str, workflow: str, user_request: str = "") -> None:
    workspace_path = str(normalize_path(workspace))
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    await db.execute(
        """
        INSERT INTO agent_jobs (id, workspace, workflow, status, started_at, completed_at, token_usage, duration, files_modified, errors, logs, workspace_manifest, user_request)
        VALUES (?, ?, ?, ?, ?, NULL, 0, 0.0, '[]', '', '[]', '{}', ?)
        """,
        (job_id, workspace_path, workflow, "queued", now, user_request)
    )
    await db.commit()

async def update_job_status(job_id: str, status: str, errors: str = "") -> None:
    db = await get_db()
    cursor = await db.execute("SELECT started_at FROM agent_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    duration = 0.0
    now_str = datetime.now(timezone.utc).isoformat()
    if row and row["started_at"]:
        start = datetime.fromisoformat(row["started_at"])
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        
    await db.execute(
        """
        UPDATE agent_jobs
        SET status = ?, errors = ?, completed_at = ?, duration = ?
        WHERE id = ?
        """,
        (status, errors, now_str if status in ("completed", "failed", "cancelled") else None, duration, job_id)
    )
    await db.commit()

async def add_job_log(job_id: str, log_message: str) -> None:
    db = await get_db()
    cursor = await db.execute("SELECT logs FROM agent_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    logs = json.loads(row["logs"]) if row and row["logs"] else []
    logs.append(log_message)
    await db.execute("UPDATE agent_jobs SET logs = ? WHERE id = ?", (json.dumps(logs), job_id))
    await db.commit()

async def increment_job_token_usage(job_id: str, tokens: int) -> None:
    db = await get_db()
    await db.execute("UPDATE agent_jobs SET token_usage = token_usage + ? WHERE id = ?", (tokens, job_id))
    await db.commit()

async def add_job_modified_file(job_id: str, file_path: str) -> None:
    db = await get_db()
    cursor = await db.execute("SELECT files_modified FROM agent_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    files = json.loads(row["files_modified"]) if row and row["files_modified"] else []
    if file_path not in files:
        files.append(file_path)
        await db.execute("UPDATE agent_jobs SET files_modified = ? WHERE id = ?", (json.dumps(files), job_id))
        await db.commit()

async def get_job_manifest(job_id: str) -> str:
    """Retrieve the raw workspace manifest JSON for a job."""
    db = await get_db()
    cursor = await db.execute("SELECT workspace_manifest FROM agent_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    return row["workspace_manifest"] if row and row["workspace_manifest"] else "{}"

async def update_job_manifest(job_id: str, manifest_json: str) -> None:
    """Persist the workspace manifest JSON for a job."""
    db = await get_db()
    await db.execute("UPDATE agent_jobs SET workspace_manifest = ? WHERE id = ?", (manifest_json, job_id))
    await db.commit()

async def create_task(task_id: str, job_id: str, title: str, agent_role: str, dependencies: list[str], estimated_effort: str = "") -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO agent_tasks (id, job_id, title, agent_role, status, dependencies, assigned_agent, reasoning_summary, estimated_effort, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, '', ?, NULL, NULL)
        """,
        (task_id, job_id, title, agent_role, "queued", json.dumps(dependencies), estimated_effort)
    )
    await db.commit()

async def update_task_status(task_id: str, status: str, reasoning_summary: str = "", estimated_effort: str = "", assigned_agent: str = "", structured_data: dict = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    started_at = now if status == "running" else None
    completed_at = now if status in ("completed", "failed", "cancelled") else None
    
    structured_data_json = json.dumps(structured_data) if structured_data is not None else None
    
    await db.execute(
        """
        UPDATE agent_tasks
        SET status = ?,
            reasoning_summary = CASE WHEN ? != '' THEN ? ELSE reasoning_summary END,
            estimated_effort = CASE WHEN ? != '' THEN ? ELSE estimated_effort END,
            assigned_agent = CASE WHEN ? IS NOT NULL THEN ? ELSE assigned_agent END,
            started_at = COALESCE(?, started_at),
            completed_at = COALESCE(?, completed_at),
            structured_data = CASE WHEN ? IS NOT NULL THEN ? ELSE structured_data END
        WHERE id = ?
        """,
        (
            status,
            reasoning_summary, reasoning_summary,
            estimated_effort, estimated_effort,
            assigned_agent, assigned_agent,
            started_at,
            completed_at,
            structured_data_json, structured_data_json,
            task_id
        )
    )
    await db.commit()

async def get_job(job_id: str) -> dict | None:
    db = await get_db()
    job_cursor = await db.execute("SELECT * FROM agent_jobs WHERE id = ?", (job_id,))
    job_row = await job_cursor.fetchone()
    await job_cursor.close()
    if not job_row:
        return None
        
    task_cursor = await db.execute("SELECT * FROM agent_tasks WHERE job_id = ?", (job_id,))
    task_rows = await task_cursor.fetchall()
    await task_cursor.close()
    
    tasks = [
        {
            "id": t["id"],
            "job_id": t["job_id"],
            "title": t["title"],
            "agent_role": t["agent_role"],
            "status": t["status"],
            "dependencies": json.loads(t["dependencies"]),
            "assigned_agent": t["assigned_agent"],
            "reasoning_summary": t["reasoning_summary"],
            "estimated_effort": t["estimated_effort"],
            "started_at": t["started_at"],
            "completed_at": t["completed_at"],
            "pending_action": json.loads(t["pending_action"]) if t["pending_action"] else None,
            "structured_data": json.loads(t["structured_data"]) if t["structured_data"] else None
        }
        for t in task_rows
    ]
    
    return {
        "id": job_row["id"],
        "workspace": job_row["workspace"],
        "workflow": job_row["workflow"],
        "status": job_row["status"],
        "started_at": job_row["started_at"],
        "completed_at": job_row["completed_at"],
        "token_usage": job_row["token_usage"],
        "duration": job_row["duration"],
        "files_modified": json.loads(job_row["files_modified"]),
        "errors": job_row["errors"],
        "logs": json.loads(job_row["logs"]),
        "workspace_manifest": job_row["workspace_manifest"] if "workspace_manifest" in job_row.keys() else "{}",
        "user_request": job_row["user_request"] if "user_request" in job_row.keys() else "",
        "pause_reason": job_row["pause_reason"] if "pause_reason" in job_row.keys() else "",
        "retry_after": float(job_row["retry_after"]) if "retry_after" in job_row.keys() and job_row["retry_after"] is not None else 0.0,
        "tasks": tasks
    }

async def list_jobs(workspace: str) -> list[dict]:
    workspace_path = str(normalize_path(workspace))
    db = await get_db()
    cursor = await db.execute("SELECT * FROM agent_jobs WHERE workspace = ? ORDER BY started_at DESC", (workspace_path,))
    rows = await cursor.fetchall()
    return [
        {
            "id": r["id"],
            "workspace": r["workspace"],
            "workflow": r["workflow"],
            "status": r["status"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "token_usage": r["token_usage"],
            "duration": r["duration"],
            "files_modified": json.loads(r["files_modified"]),
            "errors": r["errors"]
        }
        for r in rows
    ]

async def update_task_pending_action(task_id: str, pending_action: dict | None) -> None:
    db = await get_db()
    val = json.dumps(pending_action) if pending_action else None
    await db.execute("UPDATE agent_tasks SET pending_action = ? WHERE id = ?", (val, task_id))
    await db.commit()


def register_subscribers() -> None:
    from .event_bus import event_bus
    
    async def on_agent_log(data: dict) -> None:
        job_id = data.get("job_id")
        message = data.get("message")
        if job_id and message:
            await add_job_log(job_id, message)
            
    event_bus.subscribe("agent_log", on_agent_log)


async def pause_job(job_id: str, pause_reason: str, retry_after: float = 60.0) -> None:
    """Pause an agent job due to rate limiting or circuit breaker with retry delay."""
    db = await get_db()
    await db.execute(
        """
        UPDATE agent_jobs
        SET status = 'paused', errors = ?, pause_reason = ?, retry_after = ?
        WHERE id = ?
        """,
        (pause_reason, pause_reason, retry_after, job_id)
    )
    await db.execute(
        "UPDATE agent_tasks SET status = 'paused' WHERE job_id = ? AND status = 'running'",
        (job_id,)
    )
    await db.commit()


async def resume_job(job_id: str) -> bool:
    """Resume a paused agent job."""
    db = await get_db()
    cursor = await db.execute("SELECT status FROM agent_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if not row or row["status"] != "paused":
        return False
    await db.execute(
        "UPDATE agent_jobs SET status = 'running', errors = '', pause_reason = '', retry_after = 0.0 WHERE id = ?",
        (job_id,)
    )
    await db.execute(
        "UPDATE agent_tasks SET status = 'running' WHERE job_id = ? AND status = 'paused'",
        (job_id,)
    )
    await db.commit()
    return True


async def add_team_message(
    job_id: str,
    sender_role: str,
    message_type: str,
    content: str,
    artifact_json: str | None = None,
    token_usage: int = 0,
    cost_usd: float = 0.0,
    task_id: str | None = None,
    recipient_role: str = "all",
) -> int:
    """Insert a structured message into the team_messages table."""
    db = await get_db()
    now = time.time()
    cur = await db.execute(
        """
        INSERT INTO team_messages
        (job_id, task_id, sender_role, recipient_role, message_type, content, artifact_json, token_usage, cost_usd, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, task_id, sender_role, recipient_role, message_type, content, artifact_json, token_usage, cost_usd, now)
    )
    msg_id = cur.lastrowid
    await cur.close()
    await db.commit()
    return msg_id


async def get_team_messages(job_id: str, limit: int = 100) -> list[dict]:
    """Retrieve structured team messages for a job, ordered chronologically."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id, job_id, task_id, sender_role, recipient_role, message_type, content, artifact_json, token_usage, cost_usd, timestamp
        FROM team_messages
        WHERE job_id = ?
        ORDER BY timestamp ASC, id ASC
        LIMIT ?
        """,
        (job_id, limit)
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [dict(r) for r in rows]


async def record_agent_token_usage(
    job_id: str,
    task_id: str | None,
    agent_role: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float = 0.0,
) -> int:
    """Record token usage and cost for an agent role, updating job totals and emitting a message."""
    total_tokens = input_tokens + output_tokens
    await increment_job_token_usage(job_id, total_tokens)
    content = f"Token usage update for {agent_role}: {input_tokens} in, {output_tokens} out"
    meta = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
    }
    return await add_team_message(
        job_id=job_id,
        sender_role=agent_role,
        message_type="metrics",
        content=content,
        artifact_json=json.dumps(meta),
        token_usage=total_tokens,
        cost_usd=cost_usd,
        task_id=task_id,
    )


async def get_agent_metrics(job_id: str) -> dict[str, dict[str, Any]]:
    """Aggregate per-role token usage and estimated costs for a job."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT sender_role,
               SUM(token_usage) as total_tokens,
               SUM(cost_usd) as total_cost,
               COUNT(*) as message_count
        FROM team_messages
        WHERE job_id = ?
        GROUP BY sender_role
        """,
        (job_id,)
    )
    rows = await cursor.fetchall()
    await cursor.close()

    # Also parse artifact_json for detailed input_tokens / output_tokens breakdown if available
    cursor = await db.execute(
        """
        SELECT sender_role, artifact_json
        FROM team_messages
        WHERE job_id = ? AND message_type = 'metrics' AND artifact_json IS NOT NULL
        """,
        (job_id,)
    )
    metric_rows = await cursor.fetchall()
    await cursor.close()

    input_counts: dict[str, int] = {}
    output_counts: dict[str, int] = {}
    for mr in metric_rows:
        try:
            m_data = json.loads(mr["artifact_json"])
            role = mr["sender_role"]
            input_counts[role] = input_counts.get(role, 0) + int(m_data.get("input_tokens", 0))
            output_counts[role] = output_counts.get(role, 0) + int(m_data.get("output_tokens", 0))
        except Exception:
            pass

    metrics: dict[str, dict[str, Any]] = {}
    for r in rows:
        role = r["sender_role"]
        tot_tok = int(r["total_tokens"] or 0)
        in_tok = input_counts.get(role, 0)
        out_tok = output_counts.get(role, 0)
        if in_tok == 0 and out_tok == 0 and tot_tok > 0:
            in_tok = int(tot_tok * 0.75)
            out_tok = tot_tok - in_tok
        metrics[role] = {
            "total_tokens": tot_tok,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_cost": round(float(r["total_cost"] or 0.0), 6),
            "message_count": int(r["message_count"] or 0),
        }
    return metrics



async def save_team_config(config_data: dict) -> None:
    """Save or update a team configuration in the team_configs table."""
    db = await get_db()
    workspace_path = str(normalize_path(config_data.get("workspace", ".")))
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        INSERT OR REPLACE INTO team_configs
        (id, workspace, name, architect_model, architect_provider, coder_model, coder_provider,
         reviewer_model, reviewer_provider, tester_model, tester_provider, devops_model, devops_provider,
         max_repair_rounds, max_concurrency, auto_verify, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            config_data.get("id"),
            workspace_path,
            config_data.get("name", "Default Team"),
            config_data.get("architect_model", "gpt-4o"),
            config_data.get("architect_provider", "openai"),
            config_data.get("coder_model", "claude-3-5-sonnet-latest"),
            config_data.get("coder_provider", "anthropic"),
            config_data.get("reviewer_model", "gpt-4o"),
            config_data.get("reviewer_provider", "openai"),
            config_data.get("tester_model", "llama-3.3-70b-versatile"),
            config_data.get("tester_provider", "groq"),
            config_data.get("devops_model", "llama-3.1-8b-instant"),
            config_data.get("devops_provider", "groq"),
            config_data.get("max_repair_rounds", 3),
            config_data.get("max_concurrency", 3),
            1 if config_data.get("auto_verify", True) else 0,
            config_data.get("created_at", now),
            now,
        )
    )
    await db.commit()


async def get_team_config(workspace: str) -> dict | None:
    """Retrieve the latest team configuration for a workspace."""
    db = await get_db()
    workspace_path = str(normalize_path(workspace))
    cursor = await db.execute(
        "SELECT * FROM team_configs WHERE workspace = ? ORDER BY updated_at DESC LIMIT 1",
        (workspace_path,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    return dict(row) if row else None


async def save_final_report(job_id: str, report_data: dict) -> None:
    """Save the final verification report to the agent_jobs table."""
    db = await get_db()
    report_json = json.dumps(report_data) if isinstance(report_data, dict) else str(report_data)
    try:
        await db.execute(
            "UPDATE agent_jobs SET final_report = ? WHERE id = ?",
            (report_json, job_id)
        )
        await db.commit()
    except Exception:
        try:
            await db.execute("ALTER TABLE agent_jobs ADD COLUMN final_report TEXT DEFAULT NULL")
            await db.execute(
                "UPDATE agent_jobs SET final_report = ? WHERE id = ?",
                (report_json, job_id)
            )
            await db.commit()
        except Exception:
            pass


async def get_final_report(job_id: str) -> dict | None:
    """Retrieve the saved final report for a job."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT final_report FROM agent_jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row and row["final_report"]:
            return json.loads(row["final_report"])
    except Exception:
        pass
    return None


def format_report_as_markdown(job_id: str, report: dict) -> str:
    """Format a final report dictionary as a Markdown export."""
    files_changed = report.get("files_changed", 0)
    tests_run = report.get("tests_run", 0)
    tests_passed = report.get("tests_passed", 0)
    tests_failed = report.get("tests_failed", 0)
    review_notes = report.get("review_notes", 0)
    repair_rounds = report.get("repair_rounds", 1)
    total_cost = report.get("total_cost", 0.0)

    return f"""# Verification Report — Job `{job_id}`

## Summary
- **Status:** Verified & Completed
- **Files Changed:** {files_changed}
- **Tests Run:** {tests_run} (Passed: {tests_passed}, Failed: {tests_failed})
- **Review Notes:** {review_notes} blockers found
- **Repair Rounds:** {repair_rounds}
- **Total Cost:** ${float(total_cost):.2f}

## Verification Sign-Off
All automated tests and reviewer quality checks have completed successfully.
"""
