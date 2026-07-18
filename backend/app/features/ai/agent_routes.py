import uuid
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from backend.app.features.ai.agents.planner import PlannerAgent
from backend.app.features.ai.dag_engine import dag_engine
from backend.app.features.ai.job_service import create_job, create_task, get_job, list_jobs, update_job_status
from backend.app.features.ai.context_service import gather_context

router = APIRouter()

class PlanRequest(BaseModel):
    workspace: str
    user_request: str
    provider_config: dict | None = None

class StartJobRequest(BaseModel):
    workspace: str
    workflow: str
    tasks: list[dict] # The checklist approved by the user
    provider_config: dict | None = None

@router.post("/plan")
async def generate_plan(payload: PlanRequest) -> dict:
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(payload.workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. Agent planning is disabled.")
        
    # 1. Gather active context summary for workspace
    context = await gather_context(payload.workspace)
    context_str = f"Git active branch: {context['git_status'].get('branch') if context['git_status'] else 'None'}\n"
    if context.get("readme"):
        context_str += f"README Summary:\n{context['readme']}\n"
    
    # 2. Run PlannerAgent
    planner = PlannerAgent(provider_config=payload.provider_config)
    tasks = await planner.plan_task(payload.user_request, context_str)
    return {"tasks": tasks}

@router.post("/jobs")
async def start_job(payload: StartJobRequest) -> dict:
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(payload.workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. Agent execution is disabled.")

    job_id = str(uuid.uuid4())
    # 1. Create Job in SQLite
    await create_job(job_id, payload.workspace, payload.workflow)

    # 2. Remap task IDs to fresh UUIDs to avoid UNIQUE constraint collisions when
    #    the planner (or its fallback) returns static/repeated IDs across jobs.
    id_remap: dict[str, str] = {}
    remapped_tasks = []
    for t in payload.tasks:
        new_id = f"{t['id']}_{uuid.uuid4().hex[:8]}"
        id_remap[t["id"]] = new_id
        remapped_tasks.append({**t, "id": new_id})

    # Fix dependency references to use new IDs
    for t in remapped_tasks:
        t["dependencies"] = [id_remap.get(dep, dep) for dep in t.get("dependencies", [])]

    # 3. Create tasks in SQLite
    for t in remapped_tasks:
        await create_task(
            task_id=t["id"],
            job_id=job_id,
            title=t["title"],
            agent_role=t["agent_role"],
            dependencies=t.get("dependencies", []),
            estimated_effort=t.get("estimated_effort", "")
        )

    # 4. Trigger DAG Execution in background

    await dag_engine.start_job(job_id, provider_config=payload.provider_config)
    
    return {"job_id": job_id, "status": "queued"}

@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Calculate progress percentage dynamically
    tasks = job_data.get("tasks", [])
    if not tasks:
        progress = 0
    else:
        completed = sum(1 for t in tasks if t["status"] == "completed")
        progress = int((completed / len(tasks)) * 100)
        
    job_data["progress"] = progress
    return job_data

@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    await dag_engine.cancel_job(job_id)
    return {"status": "cancelled"}

@router.get("/jobs")
async def get_jobs_list(workspace: str = Query(...)) -> list[dict]:
    return await list_jobs(workspace)

@router.post("/jobs/{job_id}/tasks/{task_id}/approve")
async def approve_task_action(job_id: str, task_id: str) -> dict:
    import backend.app.features.ai.agents.permission_state as perm_state
    from backend.app.db.database import get_connection
    import json
    
    if task_id in perm_state.pending_permission_events:
        # Check if there is an associated proposal ID in pending action
        db = await get_connection()
        proposal_id = None
        try:
            cur = await db.execute("SELECT pending_action FROM agent_tasks WHERE id = ?", (task_id,))
            row = await cur.fetchone()
            if row and row["pending_action"]:
                act = json.loads(row["pending_action"])
                if act.get("type") == "file-write":
                    proposal_id = act.get("command")
        finally:
            await db.close()

        if proposal_id:
            from backend.app.features.ai.service import apply_proposal
            try:
                await apply_proposal(proposal_id)
            except Exception as exc:
                # Merge conflict or other write error!
                # Treat as a rejection with error details so the agent can regenerate
                perm_state.pending_permission_decisions[task_id] = "reject"
                perm_state.pending_permission_feedback[task_id] = f"Apply failed: {exc}. Please ground files again and regenerate."
                perm_state.pending_permission_events[task_id].set()
                return {"status": "apply_failed", "error": str(exc)}

        perm_state.pending_permission_decisions[task_id] = "approve"
        perm_state.pending_permission_events[task_id].set()
        return {"status": "approved"}
    raise HTTPException(status_code=400, detail="No pending action for this task")


class TaskRejectRequest(BaseModel):
    feedback: str | None = None

@router.post("/jobs/{job_id}/tasks/{task_id}/reject")
async def reject_task_action(job_id: str, task_id: str, payload: TaskRejectRequest | None = None) -> dict:
    import backend.app.features.ai.agents.permission_state as perm_state
    if task_id in perm_state.pending_permission_events:
        perm_state.pending_permission_decisions[task_id] = "reject"
        if payload and payload.feedback:
            perm_state.pending_permission_feedback[task_id] = payload.feedback
        perm_state.pending_permission_events[task_id].set()
        return {"status": "rejected"}
    raise HTTPException(status_code=400, detail="No pending action for this task")


class TaskRecoverRequest(BaseModel):
    action: str

@router.post("/jobs/{job_id}/tasks/{task_id}/recover")
async def recover_task_action(job_id: str, task_id: str, payload: TaskRecoverRequest) -> dict:
    import backend.app.features.ai.agents.permission_state as perm_state
    if task_id in perm_state.pending_permission_events:
        perm_state.pending_permission_decisions[task_id] = payload.action
        perm_state.pending_permission_events[task_id].set()
        return {"status": "recovered"}
    raise HTTPException(status_code=400, detail="No pending action for this task")

