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
    from_role: TeamRole
    to_role: TeamRole
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
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def get_role_provider_config(self, role: TeamRole | str) -> dict[str, str]:
        """Get the model and provider configured for a given role."""
        r = role.value if isinstance(role, TeamRole) else str(role).lower()
        if r == "architect":
            return {"provider": self.architect_provider, "model": self.architect_model}
        elif r == "coder":
            return {"provider": self.coder_provider, "model": self.coder_model}
        elif r == "reviewer":
            return {"provider": self.reviewer_provider, "model": self.reviewer_model}
        elif r == "tester":
            return {"provider": self.tester_provider, "model": self.tester_model}
        elif r == "devops":
            return {"provider": self.devops_provider, "model": self.devops_model}
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
    role: TeamRole
    dependencies: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    status: str = "queued"  # "queued", "running", "completed", "failed", "skipped"
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    handoff: Optional[HandoffArtifact] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
