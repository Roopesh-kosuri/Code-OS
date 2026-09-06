from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Optional

from ....core.paths import normalize_path
from ..agents.agent_factory import AgentFactory
from ..step_tracker import (
    log_step_pending,
    mark_step_running,
    mark_step_completed,
    mark_step_failed,
)
from .handoff import (
    create_diff_handoff,
    create_files_handoff,
    create_review_notes_handoff,
    create_test_output_handoff,
    create_stack_trace_handoff,
    format_handoff_for_prompt,
)
from .roles import get_role_instance, BaseTeamRole
from .team_schemas import (
    HandoffArtifact,
    HandoffType,
    TeamConfig,
    TeamRole,
    TeamSSEEvent,
    TeamTask,
)

logger = logging.getLogger(__name__)


class TeamOrchestrator:
    """Multi-Agent Team Orchestrator with DAG scheduling, concurrency limiting,

    step-level write-ahead durability, and structured artifact handoffs.
    """

    def __init__(
        self,
        team_config: Optional[TeamConfig] = None,
        workspace: Optional[str] = None,
        task_executor: Optional[
            Callable[[TeamTask, list[HandoffArtifact]], Coroutine[Any, Any, dict[str, Any]]]
        ] = None,
    ) -> None:
        self.team_config = team_config or TeamConfig(workspace=workspace or ".")
        self.workspace = self.team_config.workspace
        self.max_concurrency = max(1, self.team_config.max_concurrency)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

        # Snapshot custom roles for job execution (Refinement R1 & R4)
        self.custom_roles: list[dict[str, Any]] = list(getattr(self.team_config, "custom_roles", []))
        self.custom_roles_by_handle: dict[str, dict[str, Any]] = {
            str(cr.get("handle", "")).lstrip("@").lower(): cr
            for cr in self.custom_roles
        }

        # DAG and execution state tracking
        self.completed_task_ids: set[str] = set()
        self.failed_task_ids: set[str] = set()
        self.running_task_ids: set[str] = set()
        self.task_results: dict[str, Any] = {}
        self.task_handoffs: dict[str, HandoffArtifact] = {}
        self.execution_order: list[str] = []

        # Concurrency monitoring
        self.active_concurrency: int = 0
        self.peak_concurrency: int = 0

        # Custom task executor for testing / custom pipelines
        self._custom_task_executor = task_executor
        self.task_executor = task_executor

        # Event stream subscribers
        self._event_subscribers: list[Callable[[TeamSSEEvent], Any]] = []

    def subscribe(self, subscriber: Callable[[TeamSSEEvent], Any]) -> None:
        """Register an event listener for live TeamSSEEvent emissions."""
        self._event_subscribers.append(subscriber)

    def emit_event(self, event_name: str, data: dict[str, Any]) -> None:
        """Emit a structured TeamSSEEvent to all registered subscribers."""
        event = TeamSSEEvent(event=event_name, data=data)
        for sub in self._event_subscribers:
            try:
                sub(event)
            except Exception as exc:
                logger.debug("Event subscriber error: %s", exc)

    async def request_task_approval(
        self,
        task_id: str,
        role: TeamRole | str,
        action_type: str,
        detail: str,
        reason: str,
        command: str = "",
        path: str = "",
        diff_summary: str = "",
    ) -> Any:
        """Tag and dispatch an interactive approval request for edit_file or run_command."""
        from ..harness.approval_coordinator import request_approval
        handle_key = role.value.lower() if isinstance(role, TeamRole) else str(role).lstrip("@").lower()
        custom_role_def = self.custom_roles_by_handle.get(handle_key)
        if custom_role_def:
            role_display_name = custom_role_def.get("name") or handle_key
            role_handle = custom_role_def.get("handle") or handle_key
        else:
            role_display_name = role.value if isinstance(role, TeamRole) else str(role)
            role_handle = role_display_name.lower()

        action_id = f"appr_{task_id}_{int(time.time() * 1000)}"

        metadata = {
            "agent_role": role_display_name,
            "handle": role_handle,
            "task_id": task_id,
            "team_mode": True,
            "reason": reason,
        }

        pending = await request_approval(
            action_id=action_id,
            action_type=action_type,
            detail=detail,
            reason=reason,
            task_id=task_id,
            workspace=self.workspace,
            command=command,
            path=path,
            diff_summary=diff_summary,
            agent_role=role_display_name,
            metadata=metadata,
        )

        self.emit_event("team_approval", {
            "action_id": action_id,
            "action_type": action_type,
            "agent_role": role_display_name,
            "task_id": task_id,
            "detail": detail,
            "reason": reason,
            "team_mode": True,
            "command": command,
            "path": path,
            "metadata": metadata,
        })

        return pending

    async def execute_dag(
        self,
        tasks: list[TeamTask],
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Execute a directed acyclic graph (DAG) of team tasks with bounded parallelism,

        strict dependency resolution, step_tracker write-ahead durability, and handoffs.
        """
        if not tasks:
            return {"status": "completed", "tasks": {}, "duration": 0.0}

        start_time = time.time()
        effective_job_id = job_id or tasks[0].job_id or f"job_{int(start_time)}"

        # Workspace Isolation check (Refinement R4)
        builtin_values = {br.value for br in TeamRole}
        for t in tasks:
            r = t.role
            r_str = r.value if isinstance(r, TeamRole) else str(r)
            r_handle = r_str.lstrip("@").lower()
            if r_handle not in builtin_values and not isinstance(r, TeamRole):
                if r_handle not in self.custom_roles_by_handle:
                    raise ValueError(
                        f"Workspace isolation violation: role '{r_str}' is not defined in workspace '{self.workspace}'"
                    )
                cr = self.custom_roles_by_handle[r_handle]
                cr_ws = cr.get("workspace")
                if cr_ws and normalize_path(cr_ws) != normalize_path(self.workspace):
                    raise ValueError(
                        f"Workspace isolation violation: role '{r_str}' belongs to workspace '{cr_ws}', not '{self.workspace}'"
                    )

        tasks_by_id = {t.task_id: t for t in tasks}
        all_task_ids = set(tasks_by_id.keys())
        running_tasks: dict[str, asyncio.Task] = {}

        self.emit_event("team_status", {
            "job_id": effective_job_id,
            "status": "running",
            "task_count": len(tasks),
            "max_concurrency": self.max_concurrency,
        })

        while len(self.completed_task_ids) + len(self.failed_task_ids) < len(tasks):
            # Check for cascade failures (tasks whose dependencies failed)
            for t in tasks:
                if (
                    t.task_id not in self.completed_task_ids
                    and t.task_id not in self.failed_task_ids
                    and t.task_id not in running_tasks
                ):
                    if any(dep in self.failed_task_ids for dep in t.dependencies):
                        failed_dep = next(dep for dep in t.dependencies if dep in self.failed_task_ids)
                        t.status = "failed"
                        t.error = f"Dependency '{failed_dep}' failed."
                        self.failed_task_ids.add(t.task_id)
                        self.emit_event("team_step_update", {
                            "task_id": t.task_id,
                            "status": "failed",
                            "error": t.error,
                        })

            # Identify all currently runnable tasks
            runnable = [
                t for t in tasks
                if t.task_id not in self.completed_task_ids
                and t.task_id not in self.failed_task_ids
                and t.task_id not in running_tasks
                and all(dep in self.completed_task_ids for dep in t.dependencies)
            ]

            # Dispatch runnable tasks concurrently
            for task in runnable:
                # Gather prior handoffs from completed dependencies
                prior_handoffs = [
                    self.task_handoffs[dep]
                    for dep in task.dependencies
                    if dep in self.task_handoffs
                ]

                coro = self._run_task_with_semaphore(task, prior_handoffs)
                async_task = asyncio.create_task(coro, name=f"team_task_{task.task_id}")
                running_tasks[task.task_id] = async_task

            if not running_tasks:
                # No tasks are running and not all tasks are finished -> Deadlock / circular dependency
                if len(self.completed_task_ids) + len(self.failed_task_ids) < len(tasks):
                    unresolved = all_task_ids - (self.completed_task_ids | self.failed_task_ids)
                    logger.error("DAG deadlock detected. Unresolved tasks: %s", unresolved)
                    for tid in unresolved:
                        dead_task = tasks_by_id[tid]
                        dead_task.status = "failed"
                        dead_task.error = "Unresolvable dependency or cycle detected in DAG."
                        self.failed_task_ids.add(tid)
                break

            # Await the next task completion
            done, _ = await asyncio.wait(running_tasks.values(), return_when=asyncio.FIRST_COMPLETED)
            for dt in done:
                # Find matching task_id
                tid = next(k for k, v in running_tasks.items() if v == dt)
                del running_tasks[tid]

                task = tasks_by_id[tid]
                exc = dt.exception()
                if exc:
                    logger.error("Task %s failed with exception: %s", tid, exc)
                    task.status = "failed"
                    task.error = str(exc)
                    self.failed_task_ids.add(tid)
                    self.emit_event("team_step_update", {
                        "task_id": tid,
                        "status": "failed",
                        "error": str(exc),
                    })

        duration = time.time() - start_time
        final_status = "completed" if not self.failed_task_ids else "failed"
        verif_res: Optional[dict[str, Any]] = None

        # ── Verification Gate Execution ─────────────────────────────────────
        if not self.failed_task_ids and self.team_config.auto_verify:
            from .verifier import VerificationGate

            # Collect modified files from diff handoffs
            modified_files: set[str] = set()
            for h in self.task_handoffs.values():
                if h.type == HandoffType.DIFFS:
                    modified_files.update(h.payload.get("modified_files", []))

            verifier = VerificationGate(
                event_emitter=self.emit_event,
                task_executor=self.task_executor,
                orchestrator=self,
            )
            verif_res = await verifier.verify_job(
                job_id=effective_job_id,
                workspace=self.workspace,
                team_config=self.team_config,
                modified_files=list(modified_files),
            )

            if verif_res.get("verified"):
                final_status = "completed"
                self.emit_event("team_status", {
                    "job_id": effective_job_id,
                    "status": "completed",
                    "completed_tasks": list(self.completed_task_ids),
                    "failed_tasks": list(self.failed_task_ids),
                    "duration": duration,
                    "final_report": verif_res.get("final_report"),
                    "metrics": verif_res.get("metrics"),
                })
            else:
                final_status = "paused_attention"
                self.emit_event("team_status", {
                    "job_id": effective_job_id,
                    "status": "paused_attention",
                    "reason": verif_res.get("reason"),
                    "completed_tasks": list(self.completed_task_ids),
                    "failed_tasks": list(self.failed_task_ids),
                    "duration": duration,
                    "final_report": verif_res.get("final_report"),
                })
                self.emit_event("team_message", {
                    "job_id": effective_job_id,
                    "sender_role": TeamRole.SYSTEM.value,
                    "recipient_role": TeamRole.OPERATOR.value,
                    "message_type": "injection",
                    "content": f"⚠️ Verification failed after max repair rounds: {verif_res.get('reason')}. Operator intervention requested.",
                    "details": verif_res,
                })
        else:
            self.emit_event("team_status", {
                "job_id": effective_job_id,
                "status": final_status,
                "completed_tasks": list(self.completed_task_ids),
                "failed_tasks": list(self.failed_task_ids),
                "duration": duration,
            })

        return {
            "job_id": effective_job_id,
            "status": final_status,
            "completed_count": len(self.completed_task_ids),
            "failed_count": len(self.failed_task_ids),
            "duration": duration,
            "peak_concurrency": self.peak_concurrency,
            "execution_order": self.execution_order,
            "tasks": {t.task_id: t.model_dump() for t in tasks},
            "final_report": verif_res.get("final_report") if verif_res else None,
            "verified": verif_res.get("verified", False) if verif_res else False,
        }

    async def _run_task_with_semaphore(
        self,
        task: TeamTask,
        prior_handoffs: list[HandoffArtifact],
    ) -> None:
        """Run a task bounded by the concurrency semaphore, logging step durability."""
        async with self._semaphore:
            self.active_concurrency += 1
            self.peak_concurrency = max(self.peak_concurrency, self.active_concurrency)
            self.running_task_ids.add(task.task_id)
            task.status = "running"
            task.started_at = time.time()
            role_str = task.role.value if isinstance(task.role, TeamRole) else str(task.role)

            self.emit_event("team_step_update", {
                "task_id": task.task_id,
                "status": "running",
                "role": role_str,
                "active_concurrency": self.active_concurrency,
            })

            # ── 1. Step Tracker Durability: Log Pending & Running ───────
            step_id = f"step_{task.task_id}_1"
            step_logged = False
            try:
                step_id = await log_step_pending(
                    task_id=task.task_id,
                    job_id=task.job_id,
                    step_num=1,
                    step_type=f"team_role_{role_str}",
                    payload={
                        "title": task.title,
                        "role": role_str,
                        "dependencies": task.dependencies,
                    },
                )
                await mark_step_running(step_id)
                step_logged = True
            except Exception as exc:
                logger.warning("Step tracker write-ahead log error: %s", exc)

            # ── 1.5 Smart Model Router: Classify Difficulty & Route Model ──
            if getattr(self.team_config, "smart_router_enabled", False):
                try:
                    from app.features.ai.smart_router.difficulty_classifier import classify_task_difficulty
                    from app.features.ai.smart_router.model_router import route_model

                    files = (task.context or {}).get("files") if isinstance(task.context, dict) else None
                    classification = classify_task_difficulty(task.title, file_list=files)
                    routed = route_model(classification["difficulty"])
                    assigned_model_str = f"{routed['provider']}/{routed['model']}"

                    if task.context is None:
                        task.context = {}
                    task.context["difficulty"] = classification["difficulty"]
                    task.context["difficulty_confidence"] = classification["confidence"]
                    task.context["assigned_model"] = assigned_model_str
                    task.context["tier"] = routed["tier"]
                    task.context["smart_router_config"] = {
                        "provider": routed["provider"],
                        "model": routed["model"],
                        "tier": routed["tier"],
                        "fallback_models": routed.get("fallback_models", []),
                    }

                    self.emit_event("team_metrics", {
                        "task_id": task.task_id,
                        "difficulty": classification["difficulty"],
                        "confidence": classification["confidence"],
                        "assigned_model": assigned_model_str,
                        "tier": routed["tier"],
                    })
                except Exception as ex:
                    logger.warning("Smart model router error: %s", ex)

            try:
                # ── 2. Execute Task Logic ───────────────────────────────
                result = await self._execute_task_dispatch(task, prior_handoffs)

                # ── 3. Step Tracker Durability: Mark Completed ──────────
                if step_logged:
                    await mark_step_completed(step_id, result=result)

                task.status = "completed"
                task.completed_at = time.time()
                task.result = result
                self.completed_task_ids.add(task.task_id)
                self.execution_order.append(task.task_id)
                self.task_results[task.task_id] = result

                # ── 4. Produce Handoff Artifact ────────────────────────
                handoff = self._create_task_handoff(task, result)
                self.task_handoffs[task.task_id] = handoff
                task.handoff = handoff

                self.emit_event("team_step_update", {
                    "task_id": task.task_id,
                    "status": "completed",
                    "role": role_str,
                })

                if handoff:
                    from_role_str = handoff.from_role.value if isinstance(handoff.from_role, TeamRole) else str(handoff.from_role)
                    to_role_str = handoff.to_role.value if isinstance(handoff.to_role, TeamRole) else str(handoff.to_role)
                    self.emit_event("team_handoff", {
                        "task_id": task.task_id,
                        "from_role": from_role_str,
                        "to_role": to_role_str,
                        "type": handoff.type.value if hasattr(handoff.type, "value") else str(handoff.type),
                        "summary": handoff.summary,
                    })

            except Exception as exc:
                # ── 5. Step Tracker Durability: Mark Failed ─────────────
                if step_logged:
                    try:
                        await mark_step_failed(step_id, error=str(exc))
                    except Exception:
                        pass

                task.status = "failed"
                task.completed_at = time.time()
                task.error = str(exc)
                self.failed_task_ids.add(task.task_id)
                self.emit_event("team_step_update", {
                    "task_id": task.task_id,
                    "status": "failed",
                    "error": str(exc),
                })
                raise

            finally:
                self.running_task_ids.discard(task.task_id)
                self.active_concurrency -= 1

    async def _execute_task_dispatch(
        self,
        task: TeamTask,
        prior_handoffs: list[HandoffArtifact],
    ) -> dict[str, Any]:
        """Dispatch task execution to custom executor, AgentFactory, or role handler."""
        # 1. Check for custom executor (e.g. testing or injected mock runner)
        if self._custom_task_executor is not None:
            return await self._custom_task_executor(task, prior_handoffs)

        # 2. Get provider configuration for role from TeamConfig or Smart Router override
        if getattr(self.team_config, "smart_router_enabled", False) and task.context and "smart_router_config" in task.context:
            sr_cfg = task.context["smart_router_config"]
            provider_config = {
                "provider": sr_cfg["provider"],
                "model": sr_cfg["model"],
            }
        else:
            provider_config = self.team_config.get_role_provider_config(
                task.role,
                task_title=task.title,
                task_context=task.context,
            )

        # 3. Format prior handoff context for agent
        handoff_prompt = ""
        if prior_handoffs:
            handoff_blocks = [format_handoff_for_prompt(h) for h in prior_handoffs]
            handoff_prompt = "\n\n".join(handoff_blocks)

        # Retrieve relevant past lessons learned for this task
        try:
            from app.features.ai.memory.memory_service import get_relevant_memories, increment_applied
            memories = await get_relevant_memories(self.workspace, task.title, top_k=5)
            if memories:
                lesson_lines = [f"- {m['lesson']}" for m in memories]
                memory_block = "## LESSONS LEARNED (from past mistakes):\n" + "\n".join(lesson_lines)
                handoff_prompt = f"{handoff_prompt}\n\n{memory_block}" if handoff_prompt else memory_block
                for m in memories:
                    try:
                        await increment_applied(m["id"])
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Orchestrator failed to fetch memories: %s", exc)

        # 4. Role handler instantiation and tool execution
        role_handler = get_role_instance(task.role, custom_roles=self.custom_roles)

        # 5. Dispatch via AgentFactory
        role_str = task.role.value if isinstance(task.role, TeamRole) else str(task.role)
        agent = AgentFactory.create_agent(role_str, provider_config=provider_config)

        # If agent implements execute:
        full_context = task.context.copy()
        if handoff_prompt:
            full_context["handoff_context"] = handoff_prompt

        output = await agent.execute(
            job_id=task.job_id,
            task_id=task.task_id,
            title=task.title,
            context=full_context,
            workspace=self.workspace,
        )

        return {
            "role": role_str,
            "status": getattr(output, "status", "completed"),
            "reasoning": getattr(output, "reasoning", ""),
            "proposals": [p.model_dump() for p in getattr(output, "proposals", [])] if hasattr(output, "proposals") else [],
            "test_results": getattr(output, "test_results", None),
        }

    def _create_task_handoff(self, task: TeamTask, result: dict[str, Any]) -> HandoffArtifact:
        """Package a task's output into a structured HandoffArtifact for dependent tasks."""
        role = task.role
        role_val = (role.value if isinstance(role, TeamRole) else str(role)).lower()

        if role == TeamRole.CODER or role_val == "coder":
            proposals = result.get("proposals", [])
            modified_files = [p.get("path", "") for p in proposals if isinstance(p, dict)]
            return create_diff_handoff(
                from_role=TeamRole.CODER,
                to_role=TeamRole.REVIEWER,
                diffs=proposals,
                modified_files=modified_files,
                summary=f"Coder generated {len(proposals)} proposal(s).",
                task_id=task.task_id,
            )

        elif role == TeamRole.TESTER or role_val == "tester":
            test_res = result.get("test_results") or {}
            passed = test_res.get("passed", True) if isinstance(test_res, dict) else True
            output_str = str(test_res.get("output", result.get("reasoning", "")))
            return create_test_output_handoff(
                from_role=TeamRole.TESTER,
                to_role=TeamRole.REVIEWER,
                test_output=output_str,
                passed=passed,
                summary=f"Tester completed test suite: {'PASSED' if passed else 'FAILED'}",
                task_id=task.task_id,
            )

        elif role == TeamRole.REVIEWER or role_val == "reviewer":
            reasoning = result.get("reasoning", "")
            return create_review_notes_handoff(
                from_role=TeamRole.REVIEWER,
                to_role=TeamRole.ARCHITECT,
                notes=reasoning or "Code review sign-off completed.",
                approved=True,
                summary="Reviewer audit signed off.",
                task_id=task.task_id,
            )

        elif role == TeamRole.DEVOPS or role_val == "devops":
            return create_stack_trace_handoff(
                from_role=TeamRole.DEVOPS,
                to_role=TeamRole.ARCHITECT,
                traces=result.get("reasoning", ""),
                summary="DevOps deployment / verification complete.",
                task_id=task.task_id,
            )

        elif role == TeamRole.ARCHITECT or role_val == "architect":
            files_list = [result.get("reasoning", "")]
            if task.context and "attached_files" in task.context:
                files_list.append(task.context["attached_files"])
            return create_files_handoff(
                from_role=TeamRole.ARCHITECT,
                to_role=TeamRole.CODER,
                files=files_list,
                summary="Architectural specification and task breakdown.",
                task_id=task.task_id,
            )

        else:
            reasoning = result.get("reasoning", "")
            return create_files_handoff(
                from_role=role,
                to_role=TeamRole.REVIEWER,
                files=[reasoning] if reasoning else [],
                summary=f"Custom agent {role_val} completed execution.",
                task_id=task.task_id,
            )
