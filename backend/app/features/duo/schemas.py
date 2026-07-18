"""Pydantic schemas for the Duo Generator/Critic loop feature."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Configuration for one side of the duo (generator or critic)."""
    provider: str = "ollama"          # "ollama" | "openai-compatible"
    model: str
    base_url: str | None = None       # overrides default; None → use stored setting
    temperature: float = 0.2
    # Canonical key ID for api_keys table — decouples wire-protocol name from
    # the per-provider key (e.g. preset "groq" → api_key_provider "groq")
    api_key_provider: str | None = None


class DuoSessionRequest(BaseModel):
    workspace: str
    task_description: str
    generator: ModelConfig
    critic: ModelConfig
    max_rounds: int = Field(default=5, ge=1, le=20)


# ── Critic structured output ──────────────────────────────────────────────────

class CriticIssue(BaseModel):
    description: str
    severity: str                     # "high" | "medium" | "low"
    suggested_fix: str | None = None


class CriticVerdict(BaseModel):
    approved: bool
    issues: list[CriticIssue] = []
    reasoning: str = ""


# ── DTO objects returned by API ───────────────────────────────────────────────

class DuoRoundDto(BaseModel):
    round_number: int
    generator_output: str             # full raw LLM text (may contain proposal markers)
    proposal_id: str | None           # edit_proposals.id if extracted, else None
    critic_verdict: CriticVerdict | None  # None while critic is still running
    created_at: str


class DuoSessionDto(BaseModel):
    id: str
    workspace: str
    task_description: str
    # status values: "running" | "approved" | "unresolved" | "cancelled" | "error" | "waiting_for_recovery"
    status: str
    current_round: int
    max_rounds: int
    rounds: list[DuoRoundDto]
    final_proposal_id: str | None     # the proposal the user should review in DiffViewer
    generator: ModelConfig
    critic: ModelConfig
    created_at: str
    pending_action: dict | None = None
