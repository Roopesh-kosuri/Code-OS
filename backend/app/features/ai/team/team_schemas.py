from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class TeamRole(str, Enum):
    """The 5 primary agent roles in Team Mode + operator & system."""
    ARCHITECT = "architect"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    DEVOPS = "devops"
    OPERATOR = "operator"
    SYSTEM = "system"


class HandoffType(str, Enum):
    """Types of inter-agent handoff artifacts."""
    FILES = "files"
    DIFFS = "diffs"
    TEST_OUTPUT = "test_output"
    REVIEW_NOTES = "review_notes"
    STACK_TRACES = "stack_traces"


class HandoffArtifact(BaseModel):
    """Structured artifact passed between agents in the team workflow."""
    type: HandoffType
    from_role: TeamRole | str
    to_role: TeamRole | str
    task_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    created_at: float = Field(default_factory=time.time)


class TeamConfig(BaseModel):
    """Configuration for a multi-agent team job and agent roster."""
    id: str = Field(default_factory=lambda: f"tc_{uuid.uuid4().hex[:8]}")
    workspace: str = "."
    name: str = "Default Team"
    architect_model: str = "gpt-4o"
    architect_provider: str = "openai"
    coder_model: str = "claude-3-5-sonnet-latest"
    coder_provider: str = "anthropic"
    reviewer_model: str = "gpt-4o"
    reviewer_provider: str = "openai"
    tester_model: str = "llama-3.3-70b-versatile"
    tester_provider: str = "groq"
    devops_model: str = "llama-3.1-8b-instant"
    devops_provider: str = "groq"
    max_repair_rounds: int = 3
    max_concurrency: int = 3
    auto_verify: bool = True
    auto_model_selection: bool = False
    smart_router_enabled: bool = False
    custom_roles: list[dict[str, Any]] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def get_role_provider_config(
        self,
        role: TeamRole | str,
        task_title: str = "",
        task_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, str]:
        """Get the model and provider configured for a given role, with difficulty-based auto routing."""
        if getattr(self, "smart_router_enabled", False):
            try:
                from app.features.ai.smart_router.difficulty_classifier import classify_task_difficulty
                from app.features.ai.smart_router.model_router import route_model

                files = (task_context or {}).get("files") if isinstance(task_context, dict) else None
                cls_result = classify_task_difficulty(task_title, file_list=files)
                routed = route_model(cls_result["difficulty"])
                return {"provider": routed["provider"], "model": routed["model"]}
            except Exception:
                pass

        r = role.value if isinstance(role, TeamRole) else str(role).lstrip("@").lower()
        cfg = {"provider": "openai", "model": "gpt-4o"}
        if r == "architect":
            cfg = {"provider": self.architect_provider, "model": self.architect_model}
        elif r == "coder":
            cfg = {"provider": self.coder_provider, "model": self.coder_model}
        elif r == "reviewer":
            cfg = {"provider": self.reviewer_provider, "model": self.reviewer_model}
        elif r == "tester":
            cfg = {"provider": self.tester_provider, "model": self.tester_model}
        elif r == "devops":
            cfg = {"provider": self.devops_provider, "model": self.devops_model}
        else:
            # Check custom_roles snapshot in team_config
            for cr in getattr(self, "custom_roles", []):
                cr_handle = str(cr.get("handle", "")).lstrip("@").lower()
                if cr_handle == r:
                    cfg = {
                        "provider": cr.get("provider", "openai"),
                        "model": cr.get("model", "gpt-4o"),
                    }
                    break

        if cfg["model"] == "auto" or cfg["provider"] == "auto" or self.auto_model_selection:
            return resolve_auto_model(r, task_title=task_title, task_context=task_context)

        return cfg


def resolve_auto_model(
    role: str,
    task_title: str = "",
    task_context: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    """Dynamically route a task to the optimal model based on role and task difficulty."""
    role_lower = role.lower()
    text_corpus = f"{task_title} {str(task_context or '')}".lower()

    # Keywords indicating high complexity / architectural difficulty
    high_difficulty = (
        "architect", "architecture", "security", "invariant", "refactor",
        "redesign", "algorithm", "concurrency", "distributed", "auth",
        "crypto", "parser", "ast", "compiler", "deadlock", "schema"
    )

    # Keywords indicating low complexity / fast execution
    low_difficulty = (
        "lint", "format", "typo", "deps", "dependency", "clean",
        "rename", "docs", "comment", "readme", "config", "bump"
    )

    is_high = any(k in text_corpus for k in high_difficulty)
    is_low = any(k in text_corpus for k in low_difficulty) and not is_high

    if role_lower in ("architect",):
        return {"provider": "openai", "model": "gpt-4o"}
    elif role_lower in ("reviewer",):
        return {"provider": "openai", "model": "gpt-4o"}
    elif role_lower in ("coder",):
        if is_low:
            return {"provider": "openai", "model": "gpt-4o-mini"}
        return {"provider": "anthropic", "model": "claude-3-5-sonnet-latest"}
    elif role_lower in ("tester",):
        if is_high:
            return {"provider": "openai", "model": "gpt-4o"}
        return {"provider": "groq", "model": "llama-3.3-70b-versatile"}
    elif role_lower in ("devops",):
        return {"provider": "groq", "model": "llama-3.1-8b-instant"}

    return {"provider": "openai", "model": "gpt-4o"}



class TeamMessage(BaseModel):
    """A message in the multi-agent team communication feed."""
    id: Optional[int] = None
    job_id: str
    task_id: Optional[str] = None
    sender_role: TeamRole | str
    recipient_role: TeamRole | str = "all"
    message_type: str = "chat"  # 'chat' | 'handoff' | 'decision' | 'review_verdict' | 'test_report' | 'injection'
    content: str
    artifact: Optional[HandoffArtifact] = None
    artifact_json: Optional[str] = None
    token_usage: int = 0
    cost_usd: float = 0.0
    acknowledged: bool = False
    details: Optional[dict[str, Any]] = None
    timestamp: float = Field(default_factory=time.time)


class TeamSSEEvent(BaseModel):
    """Server-Sent Event dispatched to the frontend team stream."""
    event: str  # 'team_status', 'team_step_update', 'team_message', 'team_handoff', 'team_approval', 'team_repair', 'team_metrics'
    data: dict[str, Any] = Field(default_factory=dict)


class TeamTask(BaseModel):
    """A node in the multi-agent DAG task graph."""
    task_id: str
    job_id: str
    title: str
    role: TeamRole | str
    dependencies: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "queued"  # "queued", "running", "completed", "failed", "skipped"
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    handoff: Optional[HandoffArtifact] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input_per_million": 2.50, "output_per_million": 10.00},
    "gpt-4o-mini": {"input_per_million": 0.15, "output_per_million": 0.60},
    "claude-3-5-sonnet-latest": {"input_per_million": 3.00, "output_per_million": 15.00},
    "claude-3-5-sonnet": {"input_per_million": 3.00, "output_per_million": 15.00},
    "llama-3.3-70b-versatile": {"input_per_million": 0.59, "output_per_million": 0.79},
    "llama-3.1-8b-instant": {"input_per_million": 0.05, "output_per_million": 0.08},
}


def calculate_token_cost(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
    """Calculate USD cost for input/output tokens according to model pricing."""
    m = model.lower()
    pricing = None
    for k, p in MODEL_PRICING.items():
        if k in m or m in k:
            pricing = p
            break
    if not pricing:
        pricing = {"input_per_million": 2.50, "output_per_million": 10.00}

    in_cost = (input_tokens / 1_000_000.0) * pricing["input_per_million"]
    out_cost = (output_tokens / 1_000_000.0) * pricing["output_per_million"]
    return round(in_cost + out_cost, 6)

