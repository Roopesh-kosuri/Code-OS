from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel, Field


class ContextOverflowError(RuntimeError):
    """Raised when an AI provider indicates context window or token limit was exceeded."""
    pass


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    provider: str = "ollama"
    model: str
    messages: list[ChatMessage]
    base_url: str | None = None
    temperature: float = 0.2
    attached_paths: list[str] = []
    workspace: str | None = None
    # Canonical key ID for api_keys table lookup.
    # Decouples the wire-protocol name ("openai-compatible") from per-provider
    # key storage (e.g. "groq", "anthropic", "nvidia-nim").
    # When None, falls back to the value of `provider` for backwards compat.
    api_key_provider: str | None = None


class ModelDto(BaseModel):
    name: str
    provider: str
    details: dict[str, object] = {}


class ProviderHealth(BaseModel):
    provider: str
    healthy: bool
    message: str


class FileChange(BaseModel):
    path: str
    original: str
    updated: str


class EditProposalRequest(BaseModel):
    workspace: str
    summary: str
    changes: list[FileChange] = Field(default_factory=list)
    plan: dict | None = None
    self_review: dict | None = None
    test_results: dict | None = None


class EditProposalDto(BaseModel):
    id: str
    workspace: str
    status: str
    summary: str
    changes: list[FileChange]
    diff: str
    plan: dict | None = None
    self_review: dict | None = None
    test_results: dict | None = None


class ContextRequest(BaseModel):
    workspace: str
    active_path: str | None = None
    selection: str | None = None
    open_tabs: list[str] = Field(default_factory=list)
    query: str | None = None


# ── Chat Threading schemas ────────────────────────────────────────────────────

class ChatThreadDto(BaseModel):
    id: str
    workspace: str
    title: str
    created_at: str
    updated_at: str


class ThreadCreateRequest(BaseModel):
    id: str
    workspace: str
    title: str


class ThreadRenameRequest(BaseModel):
    title: str


class ChatMessageExtendedDto(BaseModel):
    role: str
    content: str
    model: str | None = None
    attached_paths: list[str] = []
    created_at: str | None = None


class MessageSyncRequest(BaseModel):
    messages: list[ChatMessageExtendedDto]


class PendingApprovalDto(BaseModel):
    action_id: str
    task_id: str
    workspace: str
    action_type: str
    detail: str
    reason: str
    command: Optional[str] = None
    created_at: float
    expires_at: float


class ResumeResponse(BaseModel):
    status: str
    task_id: Optional[str] = None
    job_id: Optional[str] = None


class InterruptedTask(BaseModel):
    id: str
    job_id: Optional[str] = None
    title: str
    agent_role: str
    status: str
    workspace: Optional[str] = None


class SubsystemHealth(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    active: Optional[int] = None
    total: Optional[int] = None
    files_indexed: Optional[int] = None
    error: Optional[str] = None


class HealthMetrics(BaseModel):
    active_tasks: int
    pending_approvals: int
    memory_mb: float
    open_connections: int


class HealthCheckResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    subsystems: dict[str, SubsystemHealth]
    metrics: HealthMetrics


class ReadinessStatus(BaseModel):
    status: str
    services: dict[str, str]
