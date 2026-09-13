"""Marathon Autopilot — AI-powered goal decomposition into a validated DAG."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .marathon_schemas import (
    BudgetConfig,
    MarathonState,
    MarathonStatus,
    MarathonSubTask,
    SubTaskStatus,
    TaskComplexity,
)

logger = logging.getLogger(__name__)

# ── Vagueness check ───────────────────────────────────────────────────────────

_TECHNICAL_KEYWORDS = {
    "api", "endpoint", "database", "db", "table", "model", "schema", "service",
    "component", "test", "function", "class", "module", "route", "frontend",
    "backend", "migrate", "refactor", "auth", "deploy", "docker", "ci", "cd",
    "typescript", "python", "react", "fastapi", "postgres", "redis", "file",
    "write", "create", "build", "implement", "add", "update", "fix", "feature",
}

def _is_goal_vague(goal: str) -> bool:
    """Return True if the goal is too vague to decompose without clarification."""
    words = goal.lower().split()
    if len(words) < 8:
        # Very short goal — check if it has any technical specifics
        technical_hits = sum(1 for w in words if any(kw in w for kw in _TECHNICAL_KEYWORDS))
        return technical_hits == 0
    return False


def _generate_clarifying_question(goal: str) -> str:
    return (
        f"Your goal '{goal}' is quite broad. Could you clarify: "
        "What technology stack should be used, what are the main deliverables, "
        "and do you have any constraints (e.g., keep existing tests green, no new dependencies)?"
    )


# ── DAG validation ────────────────────────────────────────────────────────────

def _topological_sort(tasks: list[MarathonSubTask]) -> list[str] | None:
    """Return a valid topological order or None if there's a cycle."""
    id_to_task = {t.id: t for t in tasks}
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}
    for t in tasks:
        for dep in t.dependencies:
            if dep in in_degree:
                in_degree[t.id] = in_degree.get(t.id, 0) + 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for t in tasks:
            if node in t.dependencies:
                in_degree[t.id] -= 1
                if in_degree[t.id] == 0:
                    queue.append(t.id)

    return order if len(order) == len(tasks) else None


# ── DAG extraction from AI output ────────────────────────────────────────────

def _parse_tasks_from_ai_output(raw: str) -> list[dict[str, Any]]:
    """Extract JSON task list from AI response (handles markdown fences)."""
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().strip("`")

    # Try to find a JSON array
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "tasks" in data:
            return data["tasks"]
    except json.JSONDecodeError:
        pass

    # Fallback: try the whole string
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    logger.warning("Could not parse AI task output: %s", raw[:500])
    return []


def _build_tasks_from_dicts(task_dicts: list[dict[str, Any]]) -> list[MarathonSubTask]:
    """Convert raw dicts to MarathonSubTask, assigning stable IDs."""
    id_map: dict[str, str] = {}  # original id → assigned id
    tasks: list[MarathonSubTask] = []

    for raw in task_dicts:
        task = MarathonSubTask(
            title=str(raw.get("title", "Untitled Task"))[:120],
            description=str(raw.get("description", "")),
            target_files=list(raw.get("target_files", [])),
            target_modules=list(raw.get("target_modules", [])),
            complexity=_parse_complexity(raw.get("complexity", "medium")),
        )
        orig_id = str(raw.get("id", task.id))
        id_map[orig_id] = task.id
        tasks.append(task)

    # Remap dependencies to stable assigned IDs
    for i, raw in enumerate(task_dicts):
        raw_deps = raw.get("dependencies", [])
        tasks[i].dependencies = [id_map[d] for d in raw_deps if d in id_map]

    return tasks


def _parse_complexity(val: Any) -> TaskComplexity:
    s = str(val).lower()
    for c in TaskComplexity:
        if c.value in s:
            return c
    return TaskComplexity.MEDIUM


# ── Fallback synthetic plan ───────────────────────────────────────────────────

def _build_fallback_plan(goal: str) -> list[MarathonSubTask]:
    """Create a minimal 3-task plan when AI decomposition fails."""
    t1 = MarathonSubTask(title="Analyse and understand the existing codebase", description=f"Read and understand relevant code for: {goal}", complexity=TaskComplexity.LOW)
    t2 = MarathonSubTask(title="Implement core changes", description=f"Implement the main logic for: {goal}", complexity=TaskComplexity.HIGH, dependencies=[t1.id])
    t3 = MarathonSubTask(title="Write tests and verify", description="Write tests and verify everything passes", complexity=TaskComplexity.MEDIUM, dependencies=[t2.id])
    return [t1, t2, t3]


# ── System prompt ─────────────────────────────────────────────────────────────

_DECOMPOSE_SYSTEM = """You are a senior software architect acting as a Marathon Planner.
Your job: decompose a large software goal into a precise DAG (Directed Acyclic Graph) of 5-30 sub-tasks.

Output ONLY a valid JSON array. No prose. Each task must have:
{
  "id": "unique_short_string",
  "title": "Short imperative title (max 80 chars)",
  "description": "What exactly to do (2-5 sentences)",
  "dependencies": ["id_of_task_that_must_finish_first", ...],
  "complexity": "trivial|low|medium|high|epic",
  "target_files": ["path/to/file.py", ...],
  "target_modules": ["module.name", ...]
}

Rules:
1. Tasks must be atomic (one clear deliverable each).
2. Dependencies must form a valid DAG (no cycles).
3. First tasks should have empty dependencies.
4. Group related changes so they can be tested together.
5. Include a final "integration test" task that depends on all others.
"""


# ── Main decomposition function ───────────────────────────────────────────────

async def decompose_goal(
    state: MarathonState,
    provider_config: dict[str, Any] | None = None,
) -> MarathonState:
    """
    Decompose the marathon goal into sub-tasks and store them in state.
    Sets state.clarifying_question if goal is too vague.
    """
    goal = state.goal

    # Check if goal is vague
    if _is_goal_vague(goal) and not state.clarifying_answer:
        state.clarifying_question = _generate_clarifying_question(goal)
        state.status = MarathonStatus.AWAITING_CLARIFICATION
        state.touch()
        return state

    # Build an enriched goal if we have a clarifying answer
    enriched_goal = goal
    if state.clarifying_answer:
        enriched_goal = f"{goal}\n\nAdditional context: {state.clarifying_answer}"

    # Call AI to decompose
    raw_tasks = await _call_ai_planner(enriched_goal, state.workspace, provider_config or state.provider_config)

    if raw_tasks:
        tasks = _build_tasks_from_dicts(raw_tasks)
    else:
        logger.warning("AI planner returned no tasks, using fallback plan")
        tasks = _build_fallback_plan(goal)

    # Validate DAG
    order = _topological_sort(tasks)
    if order is None:
        logger.error("Cycle detected in marathon DAG; using fallback plan")
        tasks = _build_fallback_plan(goal)

    state.tasks = tasks
    state.status = MarathonStatus.RUNNING
    state.clarifying_question = None
    state.touch()
    logger.info("Marathon %s: decomposed goal into %d tasks", state.marathon_id, len(tasks))
    return state


async def _call_ai_planner(
    goal: str,
    workspace: str,
    provider_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Call the AI provider to generate the DAG JSON."""
    try:
        from app.features.ai.providers.base import build_provider
        provider_name = provider_config.get("provider", "openai")
        model = provider_config.get("model", "gpt-4o")
        provider = build_provider(provider_name, model=model)

        messages = [
            {"role": "system", "content": _DECOMPOSE_SYSTEM},
            {"role": "user", "content": f"Workspace: {workspace}\n\nGoal: {goal}\n\nGenerate the task DAG JSON array:"},
        ]

        response_text = ""
        async for chunk in provider.stream_chat(messages=messages, max_tokens=4096):
            if isinstance(chunk, dict):
                response_text += chunk.get("content", "")
            elif isinstance(chunk, str):
                response_text += chunk

        return _parse_tasks_from_ai_output(response_text)

    except Exception as exc:
        logger.warning("AI planner call failed: %s", exc)
        return []
