from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..schemas import ChatMessage, ModelDto, ProviderHealth


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
