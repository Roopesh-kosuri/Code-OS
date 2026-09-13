"""Marathon Autopilot — Pydantic models for state, tasks, and budget management."""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class SubTaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class MarathonStatus(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"
    AWAITING_CLARIFICATION = "awaiting_clarification"


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"    # < 50 LOC change
    LOW = "low"            # 50-200 LOC
    MEDIUM = "medium"      # 200-500 LOC
    HIGH = "high"          # 500-1000 LOC
    EPIC = "epic"          # > 1000 LOC


# ── Sub-task ──────────────────────────────────────────────────────────────────

class MarathonSubTask(BaseModel):
    """A single node in the Marathon DAG."""
    id: str = Field(default_factory=lambda: f"mt_{uuid.uuid4().hex[:8]}")
    title: str
    description: str = ""
    dependencies: list[str] = Field(default_factory=list)  # IDs that must complete first
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    target_files: list[str] = Field(default_factory=list)
    target_modules: list[str] = Field(default_factory=list)
    status: SubTaskStatus = SubTaskStatus.TODO
    retry_count: int = 0
    max_retries: int = 3
    git_commit_hash: Optional[str] = None
    error_log: list[str] = Field(default_factory=list)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    @property
    def is_ready(self) -> bool:
        """True if this task has no pending dependencies (caller must check completed IDs)."""
        return self.status == SubTaskStatus.TODO

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None


# ── Budget ────────────────────────────────────────────────────────────────────

class BudgetConfig(BaseModel):
    """User-defined limits for the marathon run."""
    token_budget: int = 1_000_000          # Total tokens allowed
    time_budget_seconds: float = 4 * 3600  # 4 hours default
    cost_budget_usd: float = 5.00          # $5 default


class BudgetUsage(BaseModel):
    """Running totals consumed so far."""
    tokens_used: int = 0
    cost_usd: float = 0.0
    elapsed_seconds: float = 0.0
    started_at: float = Field(default_factory=time.time)

    def update_elapsed(self) -> None:
        self.elapsed_seconds = time.time() - self.started_at

    def token_pct(self, budget: BudgetConfig) -> float:
        if budget.token_budget <= 0:
            return 0.0
        return self.tokens_used / budget.token_budget

    def cost_pct(self, budget: BudgetConfig) -> float:
        if budget.cost_budget_usd <= 0:
            return 0.0
        return self.cost_usd / budget.cost_budget_usd

    def time_pct(self, budget: BudgetConfig) -> float:
        if budget.time_budget_seconds <= 0:
            return 0.0
        return self.elapsed_seconds / budget.time_budget_seconds

    def any_at_90pct(self, budget: BudgetConfig) -> tuple[bool, str]:
        """Returns (should_pause, reason) if any limit hits 90%."""
        self.update_elapsed()
        if self.token_pct(budget) >= 0.90:
            return True, f"token budget ({self.token_pct(budget):.0%} used)"
        if self.cost_pct(budget) >= 0.90:
            return True, f"cost budget ({self.cost_pct(budget):.0%} used)"
        if self.time_pct(budget) >= 0.90:
            return True, f"time budget ({self.time_pct(budget):.0%} used)"
        return False, ""

    def any_at_80pct_tokens(self, budget: BudgetConfig) -> bool:
        """Context-window reset threshold (80% of token budget)."""
        return self.token_pct(budget) >= 0.80


# ── Marathon State ────────────────────────────────────────────────────────────

class MarathonState(BaseModel):
    """The full persisted state of a marathon run."""
    marathon_id: str = Field(default_factory=lambda: f"mrn_{uuid.uuid4().hex[:10]}")
    goal: str
    workspace: str = "."
    status: MarathonStatus = MarathonStatus.PLANNING
    tasks: list[MarathonSubTask] = Field(default_factory=list)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    clarifying_question: Optional[str] = None
    clarifying_answer: Optional[str] = None
    handoff_report: Optional[str] = None
    architectural_decisions: list[str] = Field(default_factory=list)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    # ── DAG helpers ───────────────────────────────────────────────────────────

    @property
    def completed_task_ids(self) -> set[str]:
        return {t.id for t in self.tasks if t.status == SubTaskStatus.COMPLETED}

    @property
    def blocked_task_ids(self) -> set[str]:
        return {t.id for t in self.tasks if t.status == SubTaskStatus.BLOCKED}

    @property
    def ready_tasks(self) -> list[MarathonSubTask]:
        """Tasks whose dependencies are all complete."""
        completed = self.completed_task_ids
        blocked = self.blocked_task_ids
        return [
            t for t in self.tasks
            if t.status == SubTaskStatus.TODO
            and all(dep in completed for dep in t.dependencies)
            and not any(dep in blocked for dep in t.dependencies)
        ]

    @property
    def progress(self) -> tuple[int, int]:
        """Returns (completed, total)."""
        return (
            len([t for t in self.tasks if t.status == SubTaskStatus.COMPLETED]),
            len(self.tasks),
        )

    def touch(self) -> None:
        self.updated_at = time.time()

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_resume_context(self) -> str:
        """Build a system-prompt injection for context-window reset."""
        completed, total = self.progress
        remaining = [t for t in self.tasks if t.status == SubTaskStatus.TODO]
        blocked = [t for t in self.tasks if t.status == SubTaskStatus.BLOCKED]

        lines = [
            f"# Marathon Resume — {self.marathon_id}",
            f"**Goal**: {self.goal}",
            f"**Progress**: {completed}/{total} tasks completed",
            f"**Status**: {self.status}",
            "",
            "## Architectural Decisions Made",
            *[f"- {d}" for d in self.architectural_decisions],
            "",
            "## Blocked Tasks",
            *[f"- [{t.id}] {t.title}: {', '.join(t.error_log[-1:])}" for t in blocked],
            "",
            "## Remaining Tasks (in order)",
            *[f"- [{t.id}] {t.title} (deps: {t.dependencies})" for t in remaining],
            "",
            "Continue the marathon from the next ready task.",
        ]
        return "\n".join(lines)


# ── API Request/Response Models ───────────────────────────────────────────────

class StartMarathonRequest(BaseModel):
    goal: str
    workspace: str = "."
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    clarifying_answer: Optional[str] = None


class MarathonStateResponse(BaseModel):
    """Slimmed-down response for the API (avoids huge payloads)."""
    marathon_id: str
    goal: str
    status: MarathonStatus
    tasks: list[MarathonSubTask]
    budget: BudgetConfig
    usage: BudgetUsage
    progress_completed: int
    progress_total: int
    handoff_report: Optional[str]
    clarifying_question: Optional[str]
    created_at: float
    updated_at: float

    @classmethod
    def from_state(cls, s: MarathonState) -> "MarathonStateResponse":
        completed, total = s.progress
        return cls(
            marathon_id=s.marathon_id,
            goal=s.goal,
            status=s.status,
            tasks=s.tasks,
            budget=s.budget,
            usage=s.usage,
            progress_completed=completed,
            progress_total=total,
            handoff_report=s.handoff_report,
            clarifying_question=s.clarifying_question,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
