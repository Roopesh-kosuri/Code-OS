import asyncio
import logging
from backend.app.features.ai.job_service import get_job, update_job_status, update_task_status, add_job_log
from backend.app.features.ai.event_bus import event_bus

logger = logging.getLogger(__name__)

class DAGEngine:
    def __init__(self) -> None:
        self._running_jobs: dict[str, asyncio.Task] = {}

    async def start_job(self, job_id: str, provider_config: dict | None = None) -> None:
        task = asyncio.create_task(self._run_job(job_id, provider_config))
        self._running_jobs[job_id] = task

    async def cancel_job(self, job_id: str) -> None:
        if job_id in self._running_jobs:
            self._running_jobs[job_id].cancel()
            del self._running_jobs[job_id]
            await update_job_status(job_id, "cancelled")
            await add_job_log(job_id, "Workflow execution cancelled by user.")

    async def _run_job(self, job_id: str, provider_config: dict | None = None) -> None:
        await update_job_status(job_id, "running")
        await add_job_log(job_id, "Starting workflow execution...")
        
        try:
            while True:
                job_data = await get_job(job_id)
                if not job_data:
                    break
                
                # Check overall status
                if job_data["status"] in ("completed", "failed", "cancelled"):
                    break
                    
                tasks = job_data["tasks"]
                
                # Check if all tasks are completed
                if all(t["status"] == "completed" for t in tasks):
                    await update_job_status(job_id, "completed")
                    await add_job_log(job_id, "Workflow execution completed successfully.")
                    break
                    
                # Check if any task failed (but only if no tasks are still waiting for user input)
                has_waiting = any(t["status"] == "waiting" for t in tasks)
                if not has_waiting and any(t["status"] == "failed" for t in tasks):
                    # Cancel all other queued/running tasks — but never cancel waiting ones
                    for t in tasks:
                        if t["status"] in ("queued", "running"):
                            await update_task_status(t["id"], "cancelled")
                    await update_job_status(job_id, "failed", errors="One or more tasks failed.")
                    await add_job_log(job_id, "Workflow execution failed due to task errors.")
                    break
                
                # Find runnable tasks (queued tasks whose dependencies are all completed)
                completed_task_ids = {t["id"] for t in tasks if t["status"] == "completed"}
                runnable_tasks = []
                for t in tasks:
                    if t["status"] == "queued":
                        deps = t["dependencies"]
                        if all(dep in completed_task_ids for dep in deps):
                            runnable_tasks.append(t)
                
                if not runnable_tasks and not any(t["status"] == "running" for t in tasks):
                    # If there are no runnable tasks and none are currently running, we have a cycle/deadlock
                    await update_job_status(job_id, "failed", errors="Deadlock detected in task dependencies.")
                    await add_job_log(job_id, "Workflow aborted: deadlock in task dependencies.")
                    break
                
                # Launch runnable tasks in parallel
                futures = []
                for t in runnable_tasks:
                    futures.append(self._execute_task(job_id, t, provider_config))
                
                if futures:
                    await asyncio.gather(*futures)
                else:
                    # Wait a bit before checking task status again
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            logger.info("Job %s cancelled", job_id)
        except Exception as exc:
            logger.exception("Job %s crashed", job_id)
            await update_job_status(job_id, "failed", errors=str(exc))
        finally:
            self._running_jobs.pop(job_id, None)

    async def _execute_task(self, job_id: str, task: dict, provider_config: dict | None = None) -> None:
        task_id = task["id"]
        role = task["agent_role"]
        
        await update_task_status(task_id, "running", assigned_agent=role)
        await add_job_log(job_id, f"Agent [{role}] started task '{task['title']}'...")
        await event_bus.publish("task_started", {"job_id": job_id, "task_id": task_id, "role": role})
        
        try:
            from backend.app.features.ai.agents.agent_factory import AgentFactory
            from backend.app.features.ai.context_service import gather_context
            from backend.app.features.ai.service import create_proposal
            from backend.app.features.ai.schemas import EditProposalRequest, FileChange
            from backend.app.features.ai.job_service import add_job_modified_file
            
            job_data = await get_job(job_id)
            workspace = job_data["workspace"] if job_data else ""
            
            # 1. Gather context — pass query so semantic search runs
            context_data = await gather_context(workspace, query=task["title"], provider_config=provider_config)
            context_text = f"Language summary: {context_data.get('languages')}\n"
            context_text += f"Active git branch: {context_data.get('git_status', {}).get('branch')}\n"
            if context_data.get("readme"):
                context_text += f"README Info:\n{context_data.get('readme')}\n"
            # Include top semantic matches so agents know which existing files are relevant
            sem_matches = context_data.get("semantic_matches", [])
            if sem_matches:
                match_lines = "\n".join(
                    f"  {m['relative_path']} (score={m['score']})" for m in sem_matches[:8]
                )
                context_text += f"Semantically relevant files:\n{match_lines}\n"
            
            # 2. Create specialized agent using factory
            agent = AgentFactory.create_agent(role, provider_config=provider_config)
            
            # 3. Execute task with new agent interface
            output = await agent.execute(job_id, task_id, task["title"], context_text, workspace)
            
            if output.status == "failure":
                raise Exception(output.reasoning_summary)
                
            # 4. Save proposals (convert dicts back to FileChange objects)
            if output.proposals and not output.structured_data.get("proposal_created_internally"):
                file_changes = [FileChange(**{k: v for k, v in p.items() if k not in ["plan", "self_review", "test_results"]}) for p in output.proposals]
                first_prop = output.proposals[0]
                payload = EditProposalRequest(
                    workspace=workspace,
                    summary=f"Task: {task['title']} ({role})",
                    changes=file_changes,
                    plan=first_prop.get("plan"),
                    self_review=first_prop.get("self_review"),
                    test_results=first_prop.get("test_results")
                )
                proposal = await create_proposal(payload)
                await add_job_log(job_id, f"Agent [{role}] created edit proposal ID: {proposal.id}")
                for change in file_changes:
                    await add_job_modified_file(job_id, change.path)
            
            await update_task_status(task_id, "completed", reasoning_summary=output.reasoning_summary, structured_data=output.structured_data)
            await add_job_log(job_id, f"Agent [{role}] successfully completed task '{task['title']}'.")
            await event_bus.publish("task_completed", {"job_id": job_id, "task_id": task_id})
            
        except Exception as exc:
            await update_task_status(task_id, "failed", reasoning_summary=str(exc))
            await add_job_log(job_id, f"Agent [{role}] failed task '{task['title']}': {exc}")
            await event_bus.publish("task_failed", {"job_id": job_id, "task_id": task_id, "error": str(exc)})

dag_engine = DAGEngine()
