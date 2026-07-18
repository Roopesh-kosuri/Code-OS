from pydantic import BaseModel, Field


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
