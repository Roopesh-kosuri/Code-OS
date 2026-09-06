from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..job_service import (
    add_team_message,
    create_job,
    create_task,
    get_agent_metrics,
    get_job,
    get_team_config,
    get_team_messages,
    pause_job,
    record_agent_token_usage,
    resume_job,
    save_final_report,
    save_team_config,
    update_job_status,
    update_task_status,
    get_final_report,
    format_report_as_markdown,
    get_custom_roles,
    save_custom_role,
    delete_custom_role,
    save_job_custom_roles_snapshot,
    get_job_custom_roles_snapshot,
)
from ...workspaces.trust_service import get_workspace_trust
from .handoff import format_handoff_for_prompt
from .orchestrator import TeamOrchestrator
from .team_schemas import (
    HandoffArtifact,
    HandoffType,
    TeamConfig,
    TeamMessage,
    TeamRole,
    TeamSSEEvent,
    TeamTask,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SubmitTeamJobRequest(BaseModel):
    workspace: str
    user_request: str
    team_config: Optional[TeamConfig] = None
    tasks: Optional[list[dict[str, Any]]] = None
    file_ids: list[str] = Field(default_factory=list)


class InjectPromptRequest(BaseModel):
    prompt: str
    target_role: str = "all"
    urgent: bool = False


class ActiveJobState:
    """In-memory state and event broadcaster for an active team job."""

    def __init__(
        self,
        job_id: str,
        workspace: str = "",
        orchestrator: Optional[TeamOrchestrator] = None,
    ) -> None:
        self.job_id = job_id
        self.workspace = workspace
        self.orchestrator = orchestrator
        self.subscribers: set[asyncio.Queue] = set()
        self.status: str = "queued"
        self.is_paused: bool = False
        self.pause_event = asyncio.Event()
        self.pause_event.set()
        self.async_task: Optional[asyncio.Task] = None
        self.injected_prompts: list[dict[str, str]] = []

    def broadcast(self, event: str, data: dict[str, Any]) -> None:
        """Push an SSE event to all connected subscriber queues."""
        msg = {"event": event, "data": data}
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except Exception:
                pass


_active_jobs: dict[str, ActiveJobState] = {}


def get_or_create_active_job(job_id: str, workspace: str = "", orchestrator: Optional[TeamOrchestrator] = None) -> ActiveJobState:
    """Retrieve or create an in-memory ActiveJobState."""
    if job_id not in _active_jobs:
        _active_jobs[job_id] = ActiveJobState(job_id, workspace=workspace, orchestrator=orchestrator)
    elif orchestrator is not None and _active_jobs[job_id].orchestrator is None:
        _active_jobs[job_id].orchestrator = orchestrator
    return _active_jobs[job_id]


def broadcast_team_event(job_id: str, event_name: str, data: dict[str, Any]) -> None:
    """Public helper to broadcast an event to active SSE listeners for a job."""
    state = get_or_create_active_job(job_id)
    state.broadcast(event_name, data)


async def get_job_snapshot_data(job_id: str) -> dict[str, Any]:
    """Assemble a complete snapshot of the current state of a team job."""
    job = await get_job(job_id)
    messages = await get_team_messages(job_id, limit=200)
    metrics = await get_agent_metrics(job_id)
    ws = job.get("workspace", "") if job else ""
    config = await get_team_config(ws) if ws else None

    active = _active_jobs.get(job_id)
    status = active.status if active else (job.get("status", "unknown") if job else "unknown")

    return {
        "job_id": job_id,
        "status": status,
        "job": job,
        "messages": messages,
        "metrics": metrics,
        "team_config": config,
        "tasks": job.get("tasks", []) if job else [],
    }


# ── Route Endpoints ──────────────────────────────────────────────────────────

@router.post("/jobs")
async def submit_team_job(payload: SubmitTeamJobRequest) -> dict[str, Any]:
    """Submit a multi-agent team workflow with workspace trust check and DAG orchestration."""
    trust = await get_workspace_trust(payload.workspace)
    if not trust.get("trusted", False):
        raise HTTPException(
            status_code=403,
            detail="Workspace is in Restricted Mode. Team execution is disabled.",
        )

    job_id = f"team_{uuid.uuid4().hex[:12]}"
    config = payload.team_config or TeamConfig(workspace=payload.workspace)
    config.workspace = payload.workspace

    # Snapshot workspace custom roles into job configuration (Refinement R1)
    custom_roles = await get_custom_roles(payload.workspace)
    config.custom_roles = custom_roles
    await save_team_config(config.model_dump())

    # Fetch attached files for Architect DAG planning
    attached_context_str = ""
    if payload.file_ids:
        from ..file_ingestion.service import get_uploaded_file
        file_blocks = []
        for fid in payload.file_ids:
            fdata = get_uploaded_file(fid, payload.workspace)
            if fdata and fdata.get("content"):
                file_blocks.append(f"[{fdata.get('filename', 'file')}]:\n{fdata.get('content', '')}")
        if file_blocks:
            attached_context_str = "Attached files:\n\n" + "\n\n".join(file_blocks)

    effective_user_request = f"{attached_context_str}\n\n{payload.user_request}" if attached_context_str else payload.user_request

    await create_job(job_id, payload.workspace, "team_mode", user_request=effective_user_request)
    await save_job_custom_roles_snapshot(job_id, custom_roles)

    # Build TeamTask DAG
    tasks: list[TeamTask] = []
    if payload.tasks:
        for idx, t in enumerate(payload.tasks):
            tid = t.get("id") or t.get("task_id") or f"{job_id}_t{idx+1}"
            role_str = t.get("role") or t.get("agent_role") or "coder"
            clean_role = role_str.lstrip("@").lower()
            try:
                role = TeamRole(clean_role)
            except ValueError:
                role = clean_role

            task_ctx = dict(t.get("context", {}))
            if attached_context_str and idx == 0:
                task_ctx["attached_files"] = attached_context_str
                task_ctx["file_ids"] = payload.file_ids

            task = TeamTask(
                task_id=tid,
                job_id=job_id,
                title=t.get("title", f"Task {idx+1}"),
                role=role,
                dependencies=t.get("dependencies", []),
                context=task_ctx,
            )
            tasks.append(task)
            role_val = task.role.value if isinstance(task.role, TeamRole) else str(task.role)
            await create_task(task.task_id, job_id, task.title, role_val, dependencies=task.dependencies)
    else:
        # Default Team Pipeline: Architect -> Coder -> Tester -> Reviewer
        arch_ctx: dict[str, Any] = {}
        if attached_context_str:
            arch_ctx["attached_files"] = attached_context_str
            arch_ctx["file_ids"] = payload.file_ids

        t1 = TeamTask(task_id=f"{job_id}_arch", job_id=job_id, title="Decompose Specification", role=TeamRole.ARCHITECT, dependencies=[], context=arch_ctx)
        t2 = TeamTask(task_id=f"{job_id}_code", job_id=job_id, title="Implement Solution", role=TeamRole.CODER, dependencies=[t1.task_id])
        t3 = TeamTask(task_id=f"{job_id}_test", job_id=job_id, title="Run Test Suite & Verify", role=TeamRole.TESTER, dependencies=[t2.task_id])
        t4 = TeamTask(task_id=f"{job_id}_rev", job_id=job_id, title="Code Review Audit", role=TeamRole.REVIEWER, dependencies=[t3.task_id])
        tasks = [t1, t2, t3, t4]
        for t in tasks:
            await create_task(t.task_id, job_id, t.title, t.role.value, dependencies=t.dependencies)

    orchestrator = TeamOrchestrator(team_config=config, workspace=payload.workspace)
    active_job = get_or_create_active_job(job_id, workspace=payload.workspace, orchestrator=orchestrator)
    active_job.status = "running"

    # Forward orchestrator events to active SSE broadcaster & database
    def _on_orchestrator_event(evt: TeamSSEEvent) -> None:
        active_job.broadcast(evt.event, evt.data)

        # Durably record messages and state transitions to SQLite
        try:
            loop = asyncio.get_running_loop()
            if evt.event == "team_status":
                st = evt.data.get("status", "")
                if st:
                    active_job.status = st
                    db_st = "paused" if st == "paused_attention" else st
                    loop.create_task(update_job_status(job_id, db_st))
                if evt.data.get("final_report"):
                    loop.create_task(save_final_report(job_id, evt.data["final_report"]))
            elif evt.event == "team_step_update":
                tid = evt.data.get("task_id")
                st = evt.data.get("status")
                err = evt.data.get("error", "")
                if tid and st:
                    loop.create_task(update_task_status(tid, st, errors=err))
            elif evt.event == "team_message":
                loop.create_task(add_team_message(
                    job_id=job_id,
                    sender_role=evt.data.get("sender_role", "system"),
                    recipient_role=evt.data.get("recipient_role", "all"),
                    message_type=evt.data.get("message_type", "chat"),
                    content=evt.data.get("content", ""),
                    artifact_json=json.dumps(evt.data.get("artifact")) if evt.data.get("artifact") else None,
                ))
            elif evt.event == "team_handoff":
                loop.create_task(add_team_message(
                    job_id=job_id,
                    sender_role=evt.data.get("from_role", "system"),
                    recipient_role=evt.data.get("to_role", "all"),
                    message_type="handoff",
                    content=evt.data.get("summary", "Artifact transfer"),
                    artifact_json=json.dumps(evt.data),
                ))
        except RuntimeError:
            pass

    orchestrator.subscribe(_on_orchestrator_event)

    # Execute DAG in background
    async def _run_bg() -> None:
        try:
            await update_job_status(job_id, "running")
            await orchestrator.execute_dag(tasks, job_id=job_id)
        except Exception as exc:
            logger.error("Team job %s failed: %s", job_id, exc)
            active_job.status = "failed"
            await update_job_status(job_id, "failed", errors=str(exc))

    active_job.async_task = asyncio.create_task(_run_bg())

    return {
        "job_id": job_id,
        "status": "queued",
        "task_count": len(tasks),
        "workspace": payload.workspace,
    }


@router.get("/jobs/{job_id}/events")
async def stream_team_events(job_id: str, snapshot_only: bool = False) -> StreamingResponse:
    """Stream live Server-Sent Events (SSE) for a team job with reconnect snapshot support."""
    active_job = get_or_create_active_job(job_id)

    async def event_generator():
        q: asyncio.Queue = asyncio.Queue()
        active_job.subscribers.add(q)
        try:
            # 1. Deliver initial snapshot on connect
            snapshot = await get_job_snapshot_data(job_id)
            yield f"event: team_snapshot\ndata: {json.dumps(snapshot)}\n\n"

            if snapshot_only:
                return

            # 2. Yield events as they are broadcast
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    evt_name = msg.get("event", "team_event")
                    payload = msg.get("data", {})
                    yield f"event: {evt_name}\ndata: {json.dumps(payload)}\n\n"
                    if evt_name in ("team_close", "close"):
                        break
                    if evt_name == "team_status" and payload.get("status") in ("completed", "failed", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            active_job.subscribers.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}/snapshot")
async def get_team_job_snapshot(job_id: str) -> dict[str, Any]:
    """Get the initial state snapshot for a team job (used on load/reconnect)."""
    snapshot = await get_job_snapshot_data(job_id)
    if not snapshot.get("job"):
        # If job not found in DB or memory
        raise HTTPException(status_code=404, detail=f"Team job '{job_id}' not found.")
    return snapshot


@router.post("/jobs/{job_id}/inject")
async def inject_operator_prompt(job_id: str, payload: InjectPromptRequest) -> dict[str, Any]:
    """Operator mid-run prompt injection targeting a specific agent or the entire team."""
    active_job = get_or_create_active_job(job_id)

    # Urgent injection: pause the active job
    if payload.urgent and active_job.status in ("running", "queued"):
        try:
            await pause_job(job_id, "Paused for urgent operator injection")
        except Exception:
            pass
        active_job.status = "paused"
        active_job.is_paused = True
        active_job.pause_event.clear()
        active_job.broadcast("team_status", {
            "job_id": job_id,
            "status": "paused",
            "message": "Paused for urgent operator injection",
        })

    msg_id = await add_team_message(
        job_id=job_id,
        sender_role="operator",
        recipient_role=payload.target_role,
        message_type="injection",
        content=payload.prompt,
        artifact_json=json.dumps({"urgent": payload.urgent, "target_role": payload.target_role}) if payload.urgent else None,
    )

    active_job.injected_prompts.append({
        "role": payload.target_role,
        "prompt": payload.prompt,
        "urgent": payload.urgent,
        "timestamp": time.time(),
    })

    # Broadcast team_message SSE event
    active_job.broadcast("team_message", {
        "message_id": msg_id,
        "job_id": job_id,
        "sender_role": "operator",
        "recipient_role": payload.target_role,
        "message_type": "injection",
        "content": payload.prompt,
        "details": {"urgent": payload.urgent, "target_role": payload.target_role},
        "timestamp": time.time(),
    })

    if payload.urgent:
        # Emit acknowledgment event from target role
        target_title = payload.target_role.capitalize() if payload.target_role != "all" else "Team"
        ack_sender = payload.target_role if payload.target_role != "all" else "system"
        ack_content = f"Acknowledged by [{target_title}]: {payload.prompt}"
        ack_id = await add_team_message(
            job_id=job_id,
            sender_role=ack_sender,
            recipient_role="operator",
            message_type="chat",
            content=ack_content,
            artifact_json=json.dumps({"acknowledged": True, "details": {"target_role": payload.target_role}}),
        )
        active_job.broadcast("team_message", {
            "message_id": ack_id,
            "job_id": job_id,
            "sender_role": ack_sender,
            "recipient_role": "operator",
            "message_type": "chat",
            "content": ack_content,
            "acknowledged": True,
            "details": {"target_role": payload.target_role},
            "timestamp": time.time(),
        })

        # Resume after operator prompt is acknowledged
        try:
            await resume_job(job_id)
        except Exception:
            pass
        active_job.status = "running"
        active_job.is_paused = False
        active_job.pause_event.set()
        active_job.broadcast("team_status", {
            "job_id": job_id,
            "status": "running",
            "message": "Resumed after urgent operator prompt acknowledged",
        })

    return {
        "success": True,
        "job_id": job_id,
        "message_id": msg_id,
        "target_role": payload.target_role,
        "content": payload.prompt,
        "urgent": payload.urgent,
        "acknowledged": bool(payload.urgent),
    }


@router.get("/jobs/{job_id}/handoffs")
async def get_team_job_handoffs(job_id: str) -> dict[str, Any]:
    """Retrieve all handoff artifacts for the job with metadata."""
    active_job = _active_jobs.get(job_id)
    handoffs: list[dict[str, Any]] = []

    # 1. From active in-memory orchestrator
    if active_job and active_job.orchestrator:
        for tid, h in active_job.orchestrator.task_handoffs.items():
            if hasattr(h, "model_dump"):
                h_dict = h.model_dump()
            elif isinstance(h, dict):
                h_dict = h.copy()
            else:
                continue
            h_dict["task_id"] = tid
            handoffs.append(h_dict)

    # 2. Persisted handoff messages from database
    db_messages = await get_team_messages(job_id, limit=200)
    seen_tasks = {h.get("task_id") for h in handoffs if h.get("task_id")}
    for m in db_messages:
        if m.get("message_type") == "handoff":
            art_json = m.get("artifact_json")
            art_data = {}
            if art_json:
                try:
                    art_data = json.loads(art_json)
                except Exception:
                    art_data = {}
            tid = m.get("task_id") or art_data.get("task_id")
            if not tid or tid not in seen_tasks:
                handoffs.append({
                    "id": m.get("id"),
                    "task_id": tid,
                    "from_role": m.get("sender_role") or art_data.get("from_role"),
                    "to_role": m.get("recipient_role") or art_data.get("to_role"),
                    "type": art_data.get("type", "files"),
                    "summary": m.get("content") or art_data.get("summary", ""),
                    "payload": art_data.get("payload", art_data),
                    "timestamp": m.get("timestamp"),
                })
                if tid:
                    seen_tasks.add(tid)

    return {
        "job_id": job_id,
        "handoffs": handoffs,
        "count": len(handoffs),
    }


@router.post("/jobs/{job_id}/pause")
async def pause_team_job(job_id: str) -> dict[str, Any]:
    """Pause an active team job."""
    await pause_job(job_id, "Paused by operator")
    active_job = get_or_create_active_job(job_id)
    active_job.status = "paused"
    active_job.is_paused = True
    active_job.pause_event.clear()

    active_job.broadcast("team_status", {
        "job_id": job_id,
        "status": "paused",
        "message": "Team job paused by operator.",
    })

    return {"success": True, "job_id": job_id, "status": "paused"}


@router.post("/jobs/{job_id}/resume")
async def resume_team_job(job_id: str) -> dict[str, Any]:
    """Resume a paused team job."""
    res = await resume_job(job_id)
    active_job = get_or_create_active_job(job_id)
    active_job.status = "running"
    active_job.is_paused = False
    active_job.pause_event.set()

    active_job.broadcast("team_status", {
        "job_id": job_id,
        "status": "running",
        "message": "Team job resumed by operator.",
    })

    return {"success": True, "job_id": job_id, "status": "running"}


@router.post("/jobs/{job_id}/cancel")
async def cancel_team_job(job_id: str) -> dict[str, Any]:
    """Cancel an active team job."""
    await update_job_status(job_id, "cancelled", errors="Cancelled by operator")
    active_job = get_or_create_active_job(job_id)
    active_job.status = "cancelled"
    if active_job.async_task and not active_job.async_task.done():
        active_job.async_task.cancel()

    active_job.broadcast("team_status", {
        "job_id": job_id,
        "status": "cancelled",
        "message": "Team job cancelled by operator.",
    })

    return {"success": True, "job_id": job_id, "status": "cancelled"}


@router.post("/jobs/{job_id}/report")
async def save_job_report_endpoint(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Save or update the final verification report for a team job."""
    report = payload.get("final_report") or payload
    await save_final_report(job_id, report)
    return {"success": True, "job_id": job_id, "final_report": report}


@router.get("/jobs/{job_id}/report")
async def get_job_report_endpoint(job_id: str) -> dict[str, Any]:
    """Get the saved final verification report for a team job."""
    report = await get_final_report(job_id)
    if not report:
        raise HTTPException(status_code=404, detail="No final report found for this job")
    return {"job_id": job_id, "final_report": report}


@router.get("/jobs/{job_id}/report/export")
async def export_job_report_markdown(job_id: str) -> PlainTextResponse:
    """Export the final verification report as a Markdown document."""
    report = await get_final_report(job_id)
    if not report:
        raise HTTPException(status_code=404, detail="No final report found for this job")
    md_content = format_report_as_markdown(job_id, report)
    return PlainTextResponse(content=md_content, media_type="text/markdown")


# ── Custom Roles Endpoints (Phase B7) ────────────────────────────────────────

class CustomRoleRequest(BaseModel):
    id: Optional[str] = None
    workspace: str = "."
    name: str
    handle: str
    description: str = ""
    color: str = "#6366f1"
    icon: str = "bot"
    allowed_tools: list[str] = Field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None


@router.get("/roles")
async def get_custom_roles_endpoint(workspace: Optional[str] = Query(None)) -> dict[str, Any]:
    """Retrieve custom agent roles, optionally filtered by workspace."""
    roles = await get_custom_roles(workspace)
    return {"roles": roles, "count": len(roles)}


@router.post("/roles")
async def save_custom_role_endpoint(payload: CustomRoleRequest) -> dict[str, Any]:
    """Create or update a custom agent role with safety tool sanitization."""
    if not payload.name.strip() or not payload.handle.strip():
        raise HTTPException(status_code=400, detail="Name and handle are required.")
    clean_handle = payload.handle.strip().lstrip("@").lower()
    builtin_values = {br.value for br in TeamRole}
    if clean_handle in builtin_values:
        raise HTTPException(status_code=400, detail=f"Handle '@{clean_handle}' conflicts with a built-in role.")
    role_data = payload.model_dump()
    role_data["handle"] = clean_handle
    try:
        saved = await save_custom_role(role_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"role": saved, "success": True}


@router.delete("/roles/{role_id}")
async def delete_custom_role_endpoint(role_id: str, workspace: Optional[str] = Query(None)) -> dict[str, Any]:
    """Delete a custom agent role."""
    deleted = await delete_custom_role(role_id, workspace=workspace)
    if not deleted:
        raise HTTPException(status_code=404, detail="Role not found or could not be deleted.")
    return {"success": True, "role_id": role_id}


@router.get("/jobs/{job_id}/roles/snapshot")
async def get_job_custom_roles_snapshot_endpoint(job_id: str) -> dict[str, Any]:
    """Get the custom roles snapshot frozen at job start."""
    snapshot = await get_job_custom_roles_snapshot(job_id)
    return {"job_id": job_id, "custom_roles": snapshot}

