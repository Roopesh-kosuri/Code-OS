from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from ..schemas import ChatMessage, ModelDto, ProviderHealth


@dataclass(frozen=True)
class ProviderToolCall:
    """A complete, provider-normalized function call.

    `arguments_json` is retained for traceability, while `arguments` is only
    populated after strict JSON-object validation.  Callers must never execute
    a call with `complete=False`.
    """

    id: str
    name: str
    arguments_json: str
    arguments: dict[str, Any] | None = None
    complete: bool = False


@dataclass(frozen=True)
class ProviderStreamEvent:
    """Lossless event boundary between an adapter and the agent harness."""

    type: Literal["text", "reasoning", "tool_calls", "incomplete_tool_call", "retry", "finish"]
    content: str = ""
    tool_calls: tuple[ProviderToolCall, ...] = field(default_factory=tuple)
    finish_reason: str | None = None
    retry_after_seconds: float | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    is_rate_limit: bool = False


class ProviderRequestError(RuntimeError):
    """A classified provider failure that can be presented honestly to users."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 body: str = "", retry_after_seconds: float | None = None,
                 category: str = "unknown") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body[:200]
        self.retry_after_seconds = retry_after_seconds
        self.category = category


class AIProvider(ABC):
    id: str

    @abstractmethod
    async def health(self) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def models(self) -> list[ModelDto]:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def stream_agent(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
        tools: list[dict] | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Compatibility bridge for adapters without native structured calls."""
        # Legacy adapters do not all accept tool/reasoning kwargs.  They remain
        # text-only compatibility paths until they provide a real override.
        async for chunk in self.stream_chat(model, messages, temperature):
            yield ProviderStreamEvent(type="text", content=chunk)
