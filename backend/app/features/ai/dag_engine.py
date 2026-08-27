import asyncio
import logging
from pathlib import Path
from .job_service import get_job, update_job_status, update_task_status, add_job_log
from .event_bus import event_bus

logger = logging.getLogger(__name__)

class DAGEngine:
    def __init__(self) -> None:
        self._running_jobs: dict[str, asyncio.Task] = {}
        self._job_events: dict[str, asyncio.Event] = {}

    def _notify_job_update(self, job_id: str) -> None:
        """Wake up the DAG engine event loop immediately upon task state change."""
        if job_id in self._job_events:
            self._job_events[job_id].set()

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
        self._job_events[job_id] = asyncio.Event()
        
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
                    # Spec coverage final check before completing job
                    try:
                        from .spec_coverage import extract_requirements, check_coverage, format_coverage_report
                        from .workspace_manifest import WorkspaceManifest
                        from .job_service import get_job_manifest
                        manifest_raw = await get_job_manifest(job_id)
                        manifest = WorkspaceManifest.from_json(manifest_raw)
                        user_req = job_data.get("user_request") or job_data.get("workflow") or ""
                        if user_req:
                            reqs = extract_requirements(user_req)
                            cov = check_coverage(reqs, manifest.get_entries(), tasks)
                            cov_report = format_coverage_report(cov)
                            await add_job_log(job_id, cov_report)
                            if cov.get("coverage_ratio", 1.0) < 0.6 and cov.get("uncovered"):
                                await add_job_log(job_id, f"WARNING: Spec coverage is low ({cov.get('coverage_ratio', 0):.0%}). Some requested features may not be addressed.")
                    except Exception as cov_exc:
                        logger.debug("Spec coverage check skipped: %s", cov_exc)
                    
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
                    has_waiting = any(t["status"] == "waiting" for t in tasks)
                    if has_waiting:
                        # A task is waiting for user permission or clarification — keep polling silently
                        evt = self._job_events.get(job_id)
                        if evt:
                            evt.clear()
                            try:
                                await asyncio.wait_for(evt.wait(), timeout=2.0)
                            except asyncio.TimeoutError:
                                pass
                        else:
                            await asyncio.sleep(2.0)
                        continue
                    # If there are no runnable tasks and none are currently running or waiting, we have a cycle/deadlock
                    await update_job_status(job_id, "failed", errors="Deadlock detected in task dependencies.")
                    await add_job_log(job_id, "Workflow aborted: deadlock in task dependencies.")
                    break

                
                # Launch runnable tasks in parallel
                futures = []
                for t in runnable_tasks:
                    futures.append(self._execute_task(job_id, t, provider_config))
                
                if futures:
                    await asyncio.gather(*futures)
                    # Brief smoothing delay to avoid bursting API token limits
                    await asyncio.sleep(1.0)
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
            self._job_events.pop(job_id, None)

    async def _execute_task(self, job_id: str, task: dict, provider_config: dict | None = None) -> None:
        task_id = task["id"]
        role = task["agent_role"]
        
        await update_task_status(task_id, "running", assigned_agent=role)
        await add_job_log(job_id, f"Agent [{role}] started task '{task['title']}'...")
        await event_bus.publish("task_started", {"job_id": job_id, "task_id": task_id, "role": role})
        
        try:
            from pathlib import Path
            from .agents.agent_factory import AgentFactory
            from .context_service import gather_context
            from .service import create_proposal
            from .schemas import EditProposalRequest, FileChange
            from .job_service import add_job_modified_file, get_job_manifest, update_job_manifest
            from .workspace_manifest import WorkspaceManifest, build_prior_steps_context, extract_exports
            from .output_validator import validate_proposals, format_stub_findings
            
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
            
            # 2. Add Cross-DAG Prior Steps Context via WorkspaceManifest
            manifest_raw = await get_job_manifest(job_id)
            manifest = WorkspaceManifest.from_json(manifest_raw)
            completed_tasks = [t for t in (job_data.get("tasks") or []) if t.get("status") == "completed"]
            dep_ids = task.get("dependencies") or []
            prior_context = build_prior_steps_context(manifest, completed_tasks, dep_ids, workspace)
            context_text += f"\n\n{prior_context}\n"
            
            # 3. Create specialized agent using factory
            agent = AgentFactory.create_agent(role, provider_config=provider_config)
            
            # 4. Execute task with agent interface
            output = await agent.execute(job_id, task_id, task["title"], context_text, workspace)
            
            if output.status == "failure":
                raise Exception(output.reasoning_summary)
            
            # 5. Quality Guardrail: Scan proposals for stub implementations
            if output.proposals:
                stub_findings = validate_proposals(output.proposals)
                if stub_findings:
                    stub_msg = format_stub_findings(stub_findings)
                    logger.warning("Task '%s' generated potential stub warnings: %s", task['title'], stub_msg)
                    await add_job_log(job_id, f"Agent [{role}] note: {stub_msg}")
                
            # 6. Apply proposals to workspace disk directly and verify on-disk existence
            if output.proposals:
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
                from .service import create_proposal, apply_proposal
                proposal = await create_proposal(payload)
                await add_job_log(job_id, f"Agent [{role}] created edit proposal ID: {proposal.id}")
                
                # Apply changes directly to workspace disk
                await apply_proposal(proposal.id)
                await add_job_log(job_id, f"Agent [{role}] applied {len(file_changes)} file(s) to workspace disk.")

                # HARD GUARDRAIL: Verify every file physically exists on disk and is non-empty
                for change in file_changes:
                    full_disk_path = Path(workspace) / change.path
                    if not full_disk_path.exists():
                        raise Exception(f"File write verification failed: Expected file '{change.path}' was not created on disk at {full_disk_path}")
                    if full_disk_path.stat().st_size == 0 and len(change.updated.strip()) > 0:
                        raise Exception(f"File write verification failed: File '{change.path}' on disk is 0 bytes but expected non-empty content.")
                    await add_job_modified_file(job_id, change.path)

                # Notify file tree and watcher to refresh explorer
                await event_bus.publish("files_changed", {"workspace": workspace, "paths": [c.path for c in file_changes]})
            
            # 7. Update WorkspaceManifest and check for duplicates
            if output.proposals:
                for p in output.proposals:
                    p_path = p.get("path") if isinstance(p, dict) else getattr(p, "path", "")
                    p_code = p.get("updated") if isinstance(p, dict) else getattr(p, "updated", "")
                    p_orig = p.get("original") if isinstance(p, dict) else getattr(p, "original", "")
                    is_new = not bool(p_orig and p_orig.strip())
                    if p_path:
                        new_exports = extract_exports(p_code) if p_code else []
                        dups = manifest.check_duplicates(p_path, task["title"], new_exports)
                        if dups:
                            for d in dups:
                                await add_job_log(job_id, f"WARNING: Potential duplicate file detected! '{p_path}' may overlap with existing '{d['existing_path']}' created by '{d['existing_task']}'.")
                        manifest.add_file(
                            path=p_path,
                            purpose=task["title"],
                            task_id=task_id,
                            task_title=task["title"],
                            agent_role=role,
                            code_content=p_code,
                            is_new_file=is_new,
                        )
                await update_job_manifest(job_id, manifest.to_json())
            
            await update_task_status(task_id, "completed", reasoning_summary=output.reasoning_summary, structured_data=output.structured_data)
            await add_job_log(job_id, f"Agent [{role}] successfully completed task '{task['title']}'.")
            self._notify_job_update(job_id)
            await event_bus.publish("task_completed", {"job_id": job_id, "task_id": task_id})
            
        except Exception as exc:
            import traceback
            tb_str = traceback.format_exc()
            logger.error("Agent [%s] task '%s' failed with traceback:\n%s", role, task['title'], tb_str)
            await add_job_log(job_id, f"Agent [{role}] encountered error on '{task['title']}': {exc}")
            
            # Prompt user with Graceful Degradation fallback options
            from .agents import permission_state as perm_state
            from .job_service import update_task_pending_action
            
            event = asyncio.Event()
            perm_state.pending_permission_events[task_id] = event
            
            action_payload = {
                "type": "task_failure",
                "details": f"Agent [{role}] encountered an internal issue on task '{task['title']}': {exc}",
                "error": str(exc)
            }
            await update_task_pending_action(task_id, action_payload)
            await update_task_status(task_id, "waiting", reasoning_summary=str(exc))
            
            await event.wait()
            
            perm_state.pending_permission_events.pop(task_id, None)
            decision = perm_state.pending_permission_decisions.pop(task_id, "cancel")
            await update_task_pending_action(task_id, None)
            
            if decision == "retry":
                await add_job_log(job_id, f"User selected 'Try Again'. Re-queuing task '{task['title']}'...")
                await update_task_status(task_id, "queued")
            elif decision == "reduced_pipeline":
                await add_job_log(job_id, f"User selected 'Continue with Reduced Pipeline'. Skipping Review & Documentation tasks...")
                await update_task_status(task_id, "completed", reasoning_summary=f"Completed with reduced pipeline (Skipped: {exc})")
                
                # Skip Review Agent and Documentation Agent tasks in this job
                job_data = await get_job(job_id)
                if job_data:
                    for t in job_data.get("tasks", []):
                        if t["agent_role"] in ("Review Agent", "Documentation Agent") and t["status"] in ("queued", "waiting"):
                            await update_task_status(t["id"], "completed", reasoning_summary="Skipped by user choice (Reduced Pipeline)")
                            await add_job_log(job_id, f"Task '{t['title']}' ({t['agent_role']}) skipped by user choice.")
                self._notify_job_update(job_id)
                await event_bus.publish("task_completed", {"job_id": job_id, "task_id": task_id})
            else:
                await update_task_status(task_id, "failed", reasoning_summary=str(exc))
                await add_job_log(job_id, f"Workflow cancelled by user after task failure: {exc}")
                await event_bus.publish("task_failed", {"job_id": job_id, "task_id": task_id, "error": str(exc)})

dag_engine = DAGEngine()
