import json
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
