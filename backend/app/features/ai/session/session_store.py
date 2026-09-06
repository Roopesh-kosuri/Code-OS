"""
session_store.py — Session Replay, Timeline Reconstruction, Time Travel & Forking.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.database import get_db, get_pool
from app.features.ai.cost.cost_aggregator import compute_cost
from app.features.ai.workspace_manifest import WorkspaceManifest

logger = logging.getLogger(__name__)


async def get_session_list(workspace: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """
    Fetch a list of past agent sessions/jobs with duration, status, step counts, and costs.
    """
    db = await get_db()
    query = """
        SELECT id, workspace, workflow, status, started_at, completed_at,
               duration, token_usage, files_modified, logs, user_request,
               workspace_manifest, final_report
        FROM agent_jobs
    """
    params: list[Any] = []
    if workspace:
        query += " WHERE workspace = ?"
        params.append(workspace)

    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, tuple(params))
    rows = await cursor.fetchall()
    await cursor.close()

    sessions: list[dict[str, Any]] = []
    for r in rows:
        job_id = r["id"]

        # 1. Total cost calculation
        cost_usd = 0.0
        try:
            c_cur = await db.execute(
                "SELECT SUM(cost_usd) as total FROM cost_events WHERE job_id = ?", (job_id,)
            )
            c_row = await c_cur.fetchone()
            await c_cur.close()
            if c_row and c_row["total"] is not None:
                cost_usd = float(c_row["total"])
            else:
                # Check team_messages
                tm_cur = await db.execute(
                    "SELECT SUM(cost_usd) as total FROM team_messages WHERE job_id = ?", (job_id,)
                )
                tm_row = await tm_cur.fetchone()
                await tm_cur.close()
                if tm_row and tm_row["total"] is not None:
                    cost_usd = float(tm_row["total"])
                else:
                    # Fallback estimate from token_usage
                    tok = r["token_usage"] or 0
                    if tok > 0:
                        cost_usd = compute_cost("groq", "llama-3.3-70b", tok // 2, tok // 2)
        except Exception as exc:
            logger.debug("Error resolving cost for job %s: %s", job_id, exc)

        # 2. Step count calculation
        step_count = 0
        try:
            s_cur = await db.execute(
                "SELECT COUNT(*) as cnt FROM task_steps WHERE job_id = ?", (job_id,)
            )
            s_row = await s_cur.fetchone()
            await s_cur.close()
            step_count = int(s_row["cnt"]) if s_row else 0

            if step_count == 0:
                # Check team_messages
                tm_s_cur = await db.execute(
                    "SELECT COUNT(*) as cnt FROM team_messages WHERE job_id = ?", (job_id,)
                )
                tm_s_row = await tm_s_cur.fetchone()
                await tm_s_cur.close()
                step_count = int(tm_s_row["cnt"]) if tm_s_row else 0

            if step_count == 0:
                # Check agent_tasks
                at_cur = await db.execute(
                    "SELECT COUNT(*) as cnt FROM agent_tasks WHERE job_id = ?", (job_id,)
                )
                at_row = await at_cur.fetchone()
                await at_cur.close()
                step_count = int(at_row["cnt"]) if at_row else 0
        except Exception as exc:
            logger.debug("Error resolving steps for job %s: %s", job_id, exc)

        title = (
            r["user_request"]
            or r["workflow"]
            or f"Session {job_id[:8]}"
        )

        sessions.append({
            "job_id": job_id,
            "workspace": r["workspace"],
            "title": title,
            "created_at": r["started_at"],
            "completed_at": r["completed_at"],
            "duration": round(float(r["duration"] or 0.0), 2),
            "status": r["status"] or "unknown",
            "cost_usd": round(cost_usd, 4),
            "step_count": step_count,
            "token_usage": r["token_usage"] or 0,
        })

    return sessions


async def get_session_timeline(job_id: str) -> list[dict[str, Any]]:
    """
    Collate chronological step-by-step timeline of agent execution:
    thought/reasoning, tool calls, file edits, test runs, outputs, and costs.
    """
    db = await get_db()
    timeline: list[dict[str, Any]] = []

    # 1. Fetch task_steps
    try:
        ts_cur = await db.execute(
            """
            SELECT ts.id, ts.task_id, ts.job_id, ts.step_num, ts.step_type, ts.status,
                   ts.payload_hash, ts.result_json, ts.created_at, ts.updated_at,
                   at.title as task_title, at.assigned_agent as task_role
            FROM task_steps ts
            LEFT JOIN agent_tasks at ON ts.task_id = at.id
            WHERE ts.job_id = ?
            ORDER BY ts.step_num ASC, ts.created_at ASC
            """,
            (job_id,),
        )
        step_rows = await ts_cur.fetchall()
        await ts_cur.close()

        for s in step_rows:
            res_data: dict[str, Any] = {}
            if s["result_json"]:
                try:
                    res_data = json.loads(s["result_json"]) if isinstance(s["result_json"], str) else s["result_json"]
                except Exception:
                    res_data = {"raw": s["result_json"]}

            # Determine agent role
            role = s["task_role"] or "agent"
            if s["step_type"].startswith("team_role_"):
                role = s["step_type"].replace("team_role_", "")

            # Extract tool and actions
            tool_name = res_data.get("tool") or res_data.get("tool_name") or ""
            action_type = "tool_call"
            if "proposals" in res_data or "file_changes" in res_data or "patch" in res_data:
                action_type = "file_edit"
            elif "pytest" in str(res_data) or "test" in str(s["step_type"]):
                action_type = "test_run"
            elif s["step_type"] in ("thinking", "reasoning"):
                action_type = "thinking"

            # File changes extraction
            file_changes = res_data.get("proposals") or res_data.get("file_changes") or []
            if isinstance(file_changes, dict):
                file_changes = [file_changes]

            # Thinking / reasoning extraction
            thinking = (
                res_data.get("thinking")
                or res_data.get("reasoning")
                or res_data.get("reasoning_summary")
                or res_data.get("plan")
                or ""
            )

            timeline.append({
                "step_id": s["id"],
                "task_id": s["task_id"],
                "step_num": s["step_num"],
                "timestamp": s["created_at"],
                "agent_role": role,
                "action_type": action_type,
                "tool_name": tool_name or s["step_type"],
                "status": s["status"],
                "input": res_data.get("input") or res_data.get("args") or {},
                "output": res_data.get("output") or res_data.get("result") or res_data,
                "file_changes": file_changes,
                "thinking": thinking,
                "cost_usd": res_data.get("cost_usd", 0.0),
            })
    except Exception as exc:
        logger.debug("Error reading task_steps for job %s: %s", job_id, exc)

    # 2. If task_steps were empty, fallback to team_messages
    if not timeline:
        try:
            tm_cur = await db.execute(
                "SELECT * FROM team_messages WHERE job_id = ? ORDER BY timestamp ASC",
                (job_id,),
            )
            msg_rows = await tm_cur.fetchall()
            await tm_cur.close()

            for idx, m in enumerate(msg_rows, 1):
                msg_type = m["message_type"]
                role = m["sender_role"] or "agent"
                content = m["content"] or ""

                action_type = "message"
                tool_name = "chat"
                if msg_type == "handoff":
                    action_type = "handoff"
                    tool_name = "handoff_artifact"
                elif msg_type == "metrics":
                    action_type = "metrics"
                    tool_name = "token_recorder"

                timeline.append({
                    "step_id": f"msg_{m['id']}",
                    "task_id": f"task_msg_{m['id']}",
                    "step_num": idx,
                    "timestamp": m["timestamp"],
                    "agent_role": role,
                    "action_type": action_type,
                    "tool_name": tool_name,
                    "status": "completed",
                    "input": {"content": content},
                    "output": {"token_usage": m["token_usage"], "cost_usd": m["cost_usd"]},
                    "file_changes": [],
                    "thinking": content if msg_type != "metrics" else "",
                    "cost_usd": float(m["cost_usd"] or 0.0),
                })
        except Exception as exc:
            logger.debug("Error reading team_messages for job %s: %s", job_id, exc)

    # 3. If still empty, synthesize from agent_jobs logs
    if not timeline:
        try:
            job_cur = await db.execute(
                "SELECT logs, user_request, workflow, files_modified, started_at FROM agent_jobs WHERE id = ?",
                (job_id,),
            )
            j_row = await job_cur.fetchone()
            await job_cur.close()
            if j_row:
                raw_logs = json.loads(j_row["logs"]) if j_row["logs"] else []
                t_base = time.time()
                try:
                    if j_row["started_at"]:
                        t_base = datetime.fromisoformat(j_row["started_at"]).timestamp()
                except Exception:
                    pass

                for idx, log_entry in enumerate(raw_logs, 1):
                    timeline.append({
                        "step_id": f"log_{job_id}_{idx}",
                        "task_id": f"task_{job_id}",
                        "step_num": idx,
                        "timestamp": t_base + (idx * 0.5),
                        "agent_role": "coder",
                        "action_type": "log",
                        "tool_name": "agent_log",
                        "status": "completed",
                        "input": {},
                        "output": {"message": log_entry},
                        "file_changes": [],
                        "thinking": log_entry,
                        "cost_usd": 0.0,
                    })
        except Exception as exc:
            logger.debug("Error parsing logs for job %s: %s", job_id, exc)

    return timeline


async def get_session_snapshot(job_id: str, step_id: str) -> dict[str, Any]:
    """
    Reconstruct the full snapshot state at a specific step:
    messages up to step, staged file changes, workspace manifest, agent state.
    """
    db = await get_db()
    timeline = await get_session_timeline(job_id)

    target_step: Optional[dict[str, Any]] = None
    target_idx = -1
    for i, s in enumerate(timeline):
        if str(s["step_id"]) == str(step_id) or str(s.get("step_num")) == str(step_id):
            target_step = s
            target_idx = i
            break

    if not target_step and timeline:
        target_step = timeline[-1]
        target_idx = len(timeline) - 1

    # Fetch job metadata
    job_cur = await db.execute("SELECT * FROM agent_jobs WHERE id = ?", (job_id,))
    job_row = await job_cur.fetchone()
    await job_cur.close()

    # Accumulate prior steps
    prior_steps = timeline[: target_idx + 1] if target_idx >= 0 else []

    # Reconstruct staged file changes up to this step
    staged_changes: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for s in reversed(prior_steps):
        for fc in s.get("file_changes", []):
            p = fc.get("path") if isinstance(fc, dict) else getattr(fc, "path", "")
            if p and p not in seen_paths:
                seen_paths.add(p)
                staged_changes.append(fc if isinstance(fc, dict) else fc.__dict__)

    # Workspace manifest snapshot
    manifest_raw = job_row["workspace_manifest"] if job_row and job_row["workspace_manifest"] else "{}"
    manifest = WorkspaceManifest.from_json(manifest_raw)

    return {
        "job_id": job_id,
        "step_id": target_step.get("step_id") if target_step else step_id,
        "step_num": target_step.get("step_num", 1) if target_step else 1,
        "agent_role": target_step.get("agent_role", "agent") if target_step else "agent",
        "timestamp": target_step.get("timestamp", time.time()) if target_step else time.time(),
        "status": target_step.get("status", "completed") if target_step else "completed",
        "messages": [
            {
                "role": s.get("agent_role", "assistant"),
                "content": s.get("thinking") or str(s.get("output")),
                "timestamp": s.get("timestamp"),
                "step_id": s.get("step_id"),
            }
            for s in prior_steps
            if s.get("thinking")
        ],
        "staged_changes": staged_changes,
        "workspace_manifest": manifest.get_entries(),
        "agent_state": {
            "active_role": target_step.get("agent_role", "coder") if target_step else "coder",
            "completed_steps": target_idx + 1,
            "total_steps": len(timeline),
            "workflow": job_row["workflow"] if job_row else "",
            "workspace": job_row["workspace"] if job_row else "",
        },
    }


async def fork_session(original_job_id: str, step_id: str, new_prompt: str) -> dict[str, Any]:
    """
    Fork an existing session at step_id, cloning state and manifest, and preparing
    the forked timeline with new prompt instructions.
    """
    db = await get_db()
    pool = await get_pool()

    # 1. Get snapshot at step_id
    snapshot = await get_session_snapshot(original_job_id, step_id)

    # 2. Get original job
    job_cur = await db.execute("SELECT * FROM agent_jobs WHERE id = ?", (original_job_id,))
    orig_job = await job_cur.fetchone()
    await job_cur.close()

    if not orig_job:
        raise ValueError(f"Original job '{original_job_id}' not found")

    forked_job_id = f"job_fork_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = time.time()

    manifest_json = json.dumps(snapshot["workspace_manifest"])
    fork_logs = [
        f"Session forked from '{original_job_id}' at step '{step_id}' (Step {snapshot.get('step_num', 1)})",
        f"Fork instruction: {new_prompt}",
    ]

    # 3. Insert new forked job into agent_jobs
    await pool.write_execute(
        """
        INSERT INTO agent_jobs (
            id, workspace, workflow, status, started_at, completed_at,
            token_usage, duration, files_modified, errors, logs,
            workspace_manifest, user_request
        )
        VALUES (?, ?, ?, 'running', ?, NULL, 0, 0.0, ?, '', ?, ?, ?)
        """,
        (
            forked_job_id,
            orig_job["workspace"],
            f"Fork: {orig_job['workflow'] or original_job_id}",
            now_iso,
            json.dumps([c.get("path") for c in snapshot.get("staged_changes", []) if c.get("path")]),
            json.dumps(fork_logs),
            manifest_json,
            new_prompt,
        ),
    )

    # 4. Clone prior steps up to step_id into task_steps for durability & timeline continuity
    # Ensure parent task exists in agent_tasks for foreign key constraint
    await pool.write_execute(
        """
        INSERT OR IGNORE INTO agent_tasks (id, job_id, title, agent_role, status)
        VALUES (?, ?, ?, 'coder', 'completed')
        """,
        (f"task_{forked_job_id}", forked_job_id, f"Forked Context: {orig_job['workflow'] or 'job'}"),
    )

    timeline = await get_session_timeline(original_job_id)
    target_idx = -1
    for i, s in enumerate(timeline):
        if str(s["step_id"]) == str(step_id) or str(s.get("step_num")) == str(step_id):
            target_idx = i
            break
    if target_idx < 0:
        target_idx = len(timeline) - 1

    cloned_steps = timeline[: target_idx + 1]
    for cs in cloned_steps:
        new_step_id = f"step_{forked_job_id}_{cs.get('step_num', 1)}"
        res_payload = {
            "tool": cs.get("tool_name"),
            "thinking": cs.get("thinking"),
            "output": cs.get("output"),
            "proposals": cs.get("file_changes"),
            "forked_from": cs.get("step_id"),
        }
        try:
            await pool.write_execute(
                """
                INSERT OR REPLACE INTO task_steps (
                    id, task_id, job_id, step_num, step_type, status,
                    payload_hash, result_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'completed', 'forked_hash', ?, ?, ?)
                """,
                (
                    new_step_id,
                    f"task_{forked_job_id}",
                    forked_job_id,
                    cs.get("step_num", 1),
                    f"team_role_{cs.get('agent_role', 'coder')}",
                    json.dumps(res_payload),
                    cs.get("timestamp", now_ts),
                    now_ts,
                ),
            )
        except Exception as exc:
            logger.debug("Could not insert cloned step for forked job: %s", exc)

    # 5. Insert new step for the forked prompt
    next_step_num = len(cloned_steps) + 1
    new_step_id = f"step_{forked_job_id}_{next_step_num}"
    await pool.write_execute(
        """
        INSERT OR REPLACE INTO task_steps (
            id, task_id, job_id, step_num, step_type, status,
            payload_hash, result_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'fork_instruction', 'completed', 'prompt_hash', ?, ?, ?)
        """,
        (
            new_step_id,
            f"task_{forked_job_id}",
            forked_job_id,
            next_step_num,
            json.dumps({"instruction": new_prompt, "status": "started"}),
            now_ts,
            now_ts,
        ),
    )

    return {
        "job_id": forked_job_id,
        "original_job_id": original_job_id,
        "step_id": step_id,
        "title": new_prompt,
        "workspace": orig_job["workspace"],
        "status": "running",
        "created_at": now_iso,
        "step_count": next_step_num,
        "message": f"Successfully forked session at step {step_id} into job '{forked_job_id}'",
    }


def export_session_transcript(job_id: str, timeline: list[dict[str, Any]], job_meta: dict[str, Any], format: str = "markdown") -> str:
    """
    Export session transcript to markdown or structured JSON.
    """
    if format.lower() == "json":
        data = {
            "job_id": job_id,
            "metadata": job_meta,
            "total_steps": len(timeline),
            "timeline": timeline,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(data, indent=2, default=str)

    # Markdown format
    title = job_meta.get("user_request") or job_meta.get("workflow") or f"Session {job_id}"
    status = str(job_meta.get("status", "completed")).upper()
    created = job_meta.get("started_at", "N/A")
    duration = round(float(job_meta.get("duration") or 0.0), 2)
    tok = job_meta.get("token_usage", 0)

    total_cost = sum(float(s.get("cost_usd", 0.0)) for s in timeline)
    if total_cost == 0.0 and tok > 0:
        total_cost = compute_cost("groq", "llama-3.3-70b", tok // 2, tok // 2)

    md = [
        f"# Session Replay: {title}",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
        f"| **Job ID** | `{job_id}` |",
        f"| **Status** | `{status}` |",
        f"| **Created At** | {created} |",
        f"| **Duration** | {duration}s |",
        f"| **Total Tokens** | {tok:,} |",
        f"| **Total Cost** | ${total_cost:.4f} |",
        f"| **Step Count** | {len(timeline)} |",
        "",
        "## User Directive",
        f"> {title}",
        "",
        "## Chronological Timeline",
        "| # | Role | Action | Tool | Status | Summary |",
        "|---|---|---|---|---|---|",
    ]

    for s in timeline:
        num = s.get("step_num", 1)
        role = str(s.get("agent_role", "agent")).upper()
        action = s.get("action_type", "tool_call")
        tool = s.get("tool_name", "-")
        stat = s.get("status", "completed")
        summary = str(s.get("thinking") or s.get("output") or "-")[:70].replace("\n", " ")
        md.append(f"| {num} | `{role}` | {action} | `{tool}` | {stat} | {summary} |")

    md.append("")
    md.append("## Step Details & Artifacts")
    for s in timeline:
        num = s.get("step_num", 1)
        role = s.get("agent_role", "agent")
        tool = s.get("tool_name", "")
        md.append(f"### Step {num}: [{role.upper()}] {tool}")
        if s.get("thinking"):
            md.append(f"**Thinking / Reasoning:**\n> {s['thinking']}\n")
        if s.get("input"):
            md.append("**Input Parameters:**")
            md.append("```json")
            md.append(json.dumps(s["input"], indent=2, default=str))
            md.append("```")
        if s.get("output"):
            md.append("**Output Result:**")
            md.append("```json")
            md.append(json.dumps(s["output"], indent=2, default=str))
            md.append("```")
        if s.get("file_changes"):
            md.append("**Modified Files:**")
            for fc in s["file_changes"]:
                path = fc.get("path") if isinstance(fc, dict) else getattr(fc, "path", "file")
                md.append(f"- `{path}`")
        md.append("---")

    return "\n".join(md)


async def export_session(job_id: str, format: str = "markdown") -> str:
    """Convenience helper to fetch timeline and metadata and export transcript."""
    db = await get_db()
    timeline = await get_session_timeline(job_id)
    cur = await db.execute("SELECT * FROM agent_jobs WHERE id = ?", (job_id,))
    row = await cur.fetchone()
    await cur.close()
    job_meta = dict(row) if row else {"id": job_id}
    return export_session_transcript(job_id, timeline, job_meta, format=format)
