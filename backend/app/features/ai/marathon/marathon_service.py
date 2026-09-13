"""Marathon Autopilot — Persistent state file management and boot-time resume detection."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from .marathon_schemas import (
    BudgetConfig,
    BudgetUsage,
    MarathonState,
    MarathonStatus,
)

logger = logging.getLogger(__name__)

# Active marathon executors keyed by marathon_id
_active_executors: dict[str, Any] = {}  # marathon_id -> MarathonExecutor
_active_tasks: dict[str, asyncio.Task] = {}  # marathon_id -> asyncio.Task


def _state_file_path(marathon_id: str, workspace: str) -> Path:
    code_os_dir = Path(workspace) / ".code_os"
    code_os_dir.mkdir(parents=True, exist_ok=True)
    return code_os_dir / f"marathon_state_{marathon_id}.json"


# ── Persistence helpers ───────────────────────────────────────────────────────

def save_state(state: MarathonState) -> None:
    """Synchronously write state to disk."""
    try:
        path = _state_file_path(state.marathon_id, state.workspace)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save marathon state: %s", exc)


def load_state(marathon_id: str, workspace: str) -> Optional[MarathonState]:
    try:
        path = _state_file_path(marathon_id, workspace)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return MarathonState.model_validate(data)
    except Exception as exc:
        logger.error("Failed to load marathon state %s: %s", marathon_id, exc)
        return None


def delete_state_file(marathon_id: str, workspace: str) -> None:
    try:
        _state_file_path(marathon_id, workspace).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Could not delete marathon state file: %s", exc)


# ── Service API ───────────────────────────────────────────────────────────────

async def start_marathon(
    goal: str,
    workspace: str,
    budget: Optional[BudgetConfig] = None,
    provider_config: Optional[dict[str, Any]] = None,
    clarifying_answer: Optional[str] = None,
) -> MarathonState:
    """Create a new marathon, decompose the goal, and start the executor loop."""
    from .marathon_planner import decompose_goal
    from .marathon_executor import MarathonExecutor

    state = MarathonState(
        goal=goal,
        workspace=workspace,
        budget=budget or BudgetConfig(),
        provider_config=provider_config or {},
        clarifying_answer=clarifying_answer,
    )
    save_state(state)

    # Decompose goal into DAG tasks (may return clarifying question)
    state = await decompose_goal(state, provider_config)
    save_state(state)

    if state.status == MarathonStatus.AWAITING_CLARIFICATION:
        return state

    executor = MarathonExecutor(state)
    _active_executors[state.marathon_id] = executor
    task = asyncio.create_task(executor.run(), name=f"marathon-{state.marathon_id}")
    _active_tasks[state.marathon_id] = task
    logger.info("Marathon %s started with %d tasks", state.marathon_id, len(state.tasks))
    return state


async def pause_marathon(marathon_id: str, workspace: str) -> MarathonState:
    executor = _active_executors.get(marathon_id)
    if executor:
        executor.request_pause()

    state = load_state(marathon_id, workspace)
    if state:
        state.status = MarathonStatus.PAUSED
        state.touch()
        _generate_handoff_report(state)
        save_state(state)
        return state
    raise ValueError(f"Marathon {marathon_id} not found")


async def resume_marathon(marathon_id: str, workspace: str) -> MarathonState:
    from .marathon_executor import MarathonExecutor
    import time

    state = load_state(marathon_id, workspace)
    if not state:
        raise ValueError(f"Marathon {marathon_id} state file not found")

    if marathon_id in _active_tasks and not _active_tasks[marathon_id].done():
        raise ValueError(f"Marathon {marathon_id} is already running")

    state.status = MarathonStatus.RUNNING
    state.usage.started_at = time.time()
    state.touch()
    save_state(state)

    executor = MarathonExecutor(state)
    _active_executors[marathon_id] = executor
    task = asyncio.create_task(executor.run(), name=f"marathon-{marathon_id}")
    _active_tasks[marathon_id] = task
    logger.info("Marathon %s resumed", marathon_id)
    return state


async def abort_marathon(marathon_id: str, workspace: str) -> MarathonState:
    task = _active_tasks.get(marathon_id)
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    _active_executors.pop(marathon_id, None)
    _active_tasks.pop(marathon_id, None)

    state = load_state(marathon_id, workspace)
    if state:
        state.status = MarathonStatus.ABORTED
        state.touch()
        save_state(state)
        return state
    raise ValueError(f"Marathon {marathon_id} not found")


def get_marathon_state(marathon_id: str, workspace: str) -> Optional[MarathonState]:
    executor = _active_executors.get(marathon_id)
    if executor:
        return executor.state
    return load_state(marathon_id, workspace)


def list_marathons(workspace: str) -> list[MarathonState]:
    code_os_dir = Path(workspace) / ".code_os"
    if not code_os_dir.exists():
        return []
    states: list[MarathonState] = []
    for f in sorted(code_os_dir.glob("marathon_state_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            states.append(MarathonState.model_validate(data))
        except Exception:
            pass
    return states


def check_for_active_marathon(workspace: str) -> Optional[MarathonState]:
    """Called on backend boot: find a running/paused marathon to offer resume."""
    for s in list_marathons(workspace):
        if s.status in (MarathonStatus.RUNNING, MarathonStatus.PAUSED):
            return s
    return None


def get_active_marathon_count() -> int:
    return len([t for t in _active_tasks.values() if not t.done()])


# ── Handoff Report ────────────────────────────────────────────────────────────

def _generate_handoff_report(state: MarathonState) -> None:
    completed, total = state.progress
    next_tasks = state.ready_tasks[:3]
    next_str = ", ".join(f"[{t.id}] {t.title}" for t in next_tasks) or "None ready"
    blocked = [t for t in state.tasks if t.status.value == "blocked"]

    report_lines = [
        f"# Marathon Paused — {state.marathon_id}",
        f"**Goal**: {state.goal}",
        f"**Progress**: {completed}/{total} tasks completed",
        "",
        "## Budget Status",
        f"- Tokens used: {state.usage.tokens_used:,} / {state.budget.token_budget:,} ({state.usage.token_pct(state.budget):.1%})",
        f"- Cost: ${state.usage.cost_usd:.4f} / ${state.budget.cost_budget_usd:.2f} ({state.usage.cost_pct(state.budget):.1%})",
        f"- Time: {state.usage.elapsed_seconds/3600:.2f}h / {state.budget.time_budget_seconds/3600:.2f}h",
        "",
        "## Next Up",
        f"Run 'Resume Marathon' to continue with: {next_str}",
        "",
        "## Blocked Tasks",
        *[f"- [{t.id}] {t.title}: {t.error_log[-1] if t.error_log else 'unknown error'}" for t in blocked],
    ]
    state.handoff_report = "\n".join(report_lines)
