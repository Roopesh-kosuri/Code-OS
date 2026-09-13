"""Marathon Autopilot — Core autonomous execution loop (asyncio background task)."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from .marathon_schemas import (
    MarathonState,
    MarathonStatus,
    MarathonSubTask,
    SubTaskStatus,
)
from .marathon_service import save_state

logger = logging.getLogger(__name__)

# SSE event emitter (best-effort; import may fail if event bus not ready)
def _emit(event_type: str, data: dict[str, Any]) -> None:
    try:
        from app.features.ai.event_bus import event_bus
        event_bus.emit(event_type, data)
    except Exception:
        pass


class MarathonExecutor:
    """
    Runs the Marathon DAG as a background asyncio task.

    Loop:
      1. Find next ready sub-task (deps all completed)
      2. Dispatch to Coder → Tester → Reviewer pipeline
      3. On pass: git commit, mark completed
      4. On 3 failures: mark blocked, skip to next
      5. Check budget (90% threshold) → pause + handoff report
      6. Check context window (80% tokens) → serialize state
      7. Continue until all tasks done or paused/aborted
    """

    def __init__(self, state: MarathonState) -> None:
        self.state = state
        self._pause_requested = False
        self._abort_requested = False

    def request_pause(self) -> None:
        self._pause_requested = True

    def request_abort(self) -> None:
        self._abort_requested = True

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        logger.info("MarathonExecutor.run: starting marathon %s", self.state.marathon_id)
        self.state.status = MarathonStatus.RUNNING
        self.state.usage.started_at = time.time()
        self._emit_update("marathon_started")

        try:
            while True:
                if self._abort_requested:
                    self.state.status = MarathonStatus.ABORTED
                    break

                if self._pause_requested:
                    self.state.status = MarathonStatus.PAUSED
                    self._emit_update("marathon_paused")
                    break

                # Budget check (90% of any limit)
                should_pause, reason = self.state.usage.any_at_90pct(self.state.budget)
                if should_pause:
                    logger.info("Marathon %s: budget guard triggered (%s)", self.state.marathon_id, reason)
                    self.state.status = MarathonStatus.PAUSED
                    from .marathon_service import _generate_handoff_report
                    _generate_handoff_report(self.state)
                    self._emit_update("marathon_budget_pause", {"reason": reason})
                    break

                # Context window check (80% tokens → serialize and pause)
                if self.state.usage.any_at_80pct_tokens(self.state.budget):
                    logger.info("Marathon %s: context window 80%% — serializing state", self.state.marathon_id)
                    self.state.status = MarathonStatus.PAUSED
                    resume_ctx = self.state.to_resume_context()
                    self._emit_update("marathon_context_reset", {"resume_context": resume_ctx})
                    break

                # Find next ready task
                ready = self.state.ready_tasks
                if not ready:
                    # Check if all done
                    all_done = all(
                        t.status in (SubTaskStatus.COMPLETED, SubTaskStatus.BLOCKED, SubTaskStatus.SKIPPED)
                        for t in self.state.tasks
                    )
                    if all_done:
                        self.state.status = MarathonStatus.COMPLETED
                        self._emit_update("marathon_completed")
                        break
                    # Nothing ready but marathon not done — could be a blocked dependency chain
                    logger.warning("Marathon %s: no ready tasks, checking for deadlock", self.state.marathon_id)
                    self._resolve_deadlock()
                    await asyncio.sleep(2)
                    continue

                # Execute the first ready task
                task = ready[0]
                await self._execute_subtask(task)

                # Persist state after each sub-task
                self.state.touch()
                save_state(self.state)

                # Yield control to event loop
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            self.state.status = MarathonStatus.ABORTED
            logger.info("Marathon %s cancelled", self.state.marathon_id)
        except Exception as exc:
            logger.error("Marathon %s: unexpected error: %s", self.state.marathon_id, exc, exc_info=True)
        finally:
            self.state.touch()
            save_state(self.state)
            self._emit_update("marathon_state_saved")
            logger.info("Marathon %s finished with status: %s", self.state.marathon_id, self.state.status)

    # ── Sub-task execution ────────────────────────────────────────────────────

    async def _execute_subtask(self, task: MarathonSubTask) -> None:
        """Run a single sub-task through the agent pipeline with retry logic."""
        task.status = SubTaskStatus.IN_PROGRESS
        task.started_at = time.time()
        self._emit_update("task_started", {"task_id": task.id, "title": task.title})

        for attempt in range(1, task.max_retries + 1):
            try:
                result = await self._dispatch_to_team(task)
                if result.get("success"):
                    # Commit and mark done
                    commit_hash = await self._git_commit(task)
                    if not commit_hash:
                        error_msg = "Git commit failed; task changes were rolled back."
                        task.error_log.append(f"Attempt {attempt}: {error_msg}")
                        task.retry_count += 1
                        await self._git_rollback(0, task)
                        # The current public task-status schema has no FAILED
                        # value; BLOCKED is the existing terminal failure state.
                        task.status = SubTaskStatus.BLOCKED
                        self._emit_update("task_failed", {
                            "task_id": task.id,
                            "attempt": attempt,
                            "error": error_msg,
                        })
                        logger.error("Marathon task %s failed: git commit did not succeed", task.id)
                        return
                    task.git_commit_hash = commit_hash
                    task.status = SubTaskStatus.COMPLETED
                    task.completed_at = time.time()
                    # Update cumulative usage
                    self.state.usage.tokens_used += result.get("tokens_used", 0)
                    self.state.usage.cost_usd += result.get("cost_usd", 0.0)
                    self.state.usage.update_elapsed()
                    self._emit_update("task_completed", {
                        "task_id": task.id,
                        "commit_hash": commit_hash,
                        "attempt": attempt,
                    })
                    logger.info("Marathon task %s completed (attempt %d)", task.id, attempt)
                    return
                else:
                    error_msg = result.get("error", "Unknown error")
                    task.error_log.append(f"Attempt {attempt}: {error_msg}")
                    task.retry_count += 1
                    logger.warning("Marathon task %s failed (attempt %d): %s", task.id, attempt, error_msg)
                    self._emit_update("task_retry", {"task_id": task.id, "attempt": attempt, "error": error_msg})

                    if attempt < task.max_retries:
                        await self._git_rollback(attempt)
                        await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                task.error_log.append(f"Attempt {attempt} exception: {exc}")
                task.retry_count += 1
                logger.error("Marathon task %s exception (attempt %d): %s", task.id, attempt, exc)

        # All retries exhausted → block
        task.status = SubTaskStatus.BLOCKED
        self._emit_update("task_blocked", {"task_id": task.id, "error_log": task.error_log})
        logger.warning("Marathon task %s blocked after %d attempts", task.id, task.max_retries)

    async def _dispatch_to_team(self, task: MarathonSubTask) -> dict[str, Any]:
        """Dispatch a sub-task to the Coder→Tester→Reviewer pipeline."""
        try:
            from app.features.ai.team.orchestrator import TeamOrchestrator
            from app.features.ai.team.team_schemas import TeamConfig, TeamTask, TeamRole

            config = TeamConfig(workspace=self.state.workspace)
            orchestrator = TeamOrchestrator(team_config=config)

            team_task = TeamTask(
                task_id=task.id,
                job_id=self.state.marathon_id,
                title=task.title,
                role=TeamRole.ARCHITECT,
                context={
                    "description": task.description,
                    "target_files": task.target_files,
                    "target_modules": task.target_modules,
                    "marathon_goal": self.state.goal,
                },
            )

            result = await orchestrator.execute_task(team_task, handoffs=[])
            success = result.get("status") == "completed" and not result.get("error")
            return {
                "success": success,
                "error": result.get("error", ""),
                "tokens_used": result.get("token_usage", 0),
                "cost_usd": result.get("cost_usd", 0.0),
            }
        except Exception as exc:
            logger.warning("dispatch_to_team failed: %s", exc)
            # Fallback: simulate success for isolated runs (e.g., testing)
            return {"success": False, "error": str(exc), "tokens_used": 0, "cost_usd": 0.0}

    # ── Git operations ────────────────────────────────────────────────────────

    def _approved_task_paths(self, task: MarathonSubTask) -> list[str]:
        """Return task targets as workspace-contained, Git-relative paths."""
        workspace = Path(self.state.workspace).resolve()
        approved: list[str] = []
        for target in task.target_files:
            candidate = Path(target)
            full_path = candidate.resolve() if candidate.is_absolute() else (workspace / candidate).resolve()
            try:
                relative = full_path.relative_to(workspace).as_posix()
            except ValueError:
                logger.error("Marathon task %s target escapes workspace: %s", task.id, target)
                return []
            if relative not in approved:
                approved.append(relative)
        return approved

    async def _git_commit(self, task: MarathonSubTask) -> str | None:
        """Stage only this task's approved paths and create a local commit."""
        try:
            commit_msg = f"feat(marathon): {task.title}"
            workspace = self.state.workspace
            approved_paths = self._approved_task_paths(task)
            if not approved_paths:
                logger.error("git commit refused: Marathon task %s has no approved target files", task.id)
                return None

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "add", "--", *approved_paths],
                    cwd=workspace, capture_output=True, text=True, timeout=30,
                ),
            )
            if result.returncode != 0:
                logger.error("git add failed for task %s: %s", task.id, result.stderr)
                return None

            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "commit", "-m", commit_msg, "--allow-empty"],
                    cwd=workspace, capture_output=True, text=True, timeout=30,
                ),
            )
            if result.returncode != 0:
                logger.error("git commit failed for task %s: %s", task.id, result.stderr)
                return None
            hash_result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=workspace, capture_output=True, text=True, timeout=30,
                ),
            )
            if hash_result.returncode != 0:
                logger.error("git rev-parse failed after task %s commit: %s", task.id, hash_result.stderr)
                return None
            return hash_result.stdout.strip() or None
        except Exception as exc:
            logger.error("git_commit failed: %s", exc)
            return None

    async def _git_rollback(self, n_commits: int, task: MarathonSubTask | None = None) -> None:
        """Roll back a failed task's paths, or retain legacy commit-count rollback."""
        try:
            workspace = self.state.workspace
            loop = asyncio.get_event_loop()
            if task is not None:
                approved_paths = self._approved_task_paths(task)
                if not approved_paths:
                    return
                restore = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", *approved_paths],
                        cwd=workspace, capture_output=True, text=True, timeout=30,
                    ),
                )
                if restore.returncode != 0:
                    logger.warning("git restore failed for task %s: %s", task.id, restore.stderr)
                clean = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["git", "clean", "-f", "--", *approved_paths],
                        cwd=workspace, capture_output=True, text=True, timeout=30,
                    ),
                )
                if clean.returncode != 0:
                    logger.warning("git clean failed for task %s: %s", task.id, clean.stderr)
                return
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "reset", "--soft", f"HEAD~{n_commits}"],
                    cwd=workspace, capture_output=True, text=True, timeout=30,
                ),
            )
        except Exception as exc:
            logger.warning("git_rollback failed: %s", exc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_deadlock(self) -> None:
        """If all remaining tasks are blocked by blocked dependencies, skip them."""
        blocked_ids = {t.id for t in self.state.tasks if t.status == SubTaskStatus.BLOCKED}
        for t in self.state.tasks:
            if t.status == SubTaskStatus.TODO:
                if any(dep in blocked_ids for dep in t.dependencies):
                    t.status = SubTaskStatus.SKIPPED
                    logger.warning("Marathon task %s skipped (blocked dependency)", t.id)

    def _emit_update(self, event: str, data: dict[str, Any] | None = None) -> None:
        completed, total = self.state.progress
        payload = {
            "marathon_id": self.state.marathon_id,
            "status": self.state.status.value,
            "progress_completed": completed,
            "progress_total": total,
            "tokens_used": self.state.usage.tokens_used,
            "cost_usd": self.state.usage.cost_usd,
            "elapsed_seconds": self.state.usage.elapsed_seconds,
            "event": event,
            **(data or {}),
        }
        _emit("marathon_update", payload)
