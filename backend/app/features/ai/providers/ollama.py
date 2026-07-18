import asyncio
from collections.abc import AsyncIterator

import httpx

from backend.app.core.config import get_settings
from backend.app.features.ai.providers.base import AIProvider
from backend.app.features.ai.schemas import ChatMessage, ModelDto, ProviderHealth
import logging

logger = logging.getLogger(__name__)


class OllamaProvider(AIProvider):
    id = "ollama"

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 300.0, max_retries: int = 1) -> None:
        self.base_url = (base_url or get_settings().ollama_base_url).rstrip('/')
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)

    async def health(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return ProviderHealth(provider=self.id, healthy=True, message="Ollama is reachable")
        except Exception as exc:
            return ProviderHealth(provider=self.id, healthy=False, message=str(exc))

    async def models(self) -> list[ModelDto]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
            return [
                ModelDto(name=item["name"], provider=self.id, details=item)
                for item in payload.get("models", [])
            ]
        except Exception as exc:
            # Return empty list and log error; UI will display a toast
            logger.error(f"Ollama models retrieval failed: {exc}")
            return []


    async def stream_chat(self, model: str, messages: list[ChatMessage], temperature: float) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        for attempt in range(self.max_retries + 1):
            emitted = False
            try:
                timeout = httpx.Timeout(self.timeout_seconds, connect=min(15.0, self.timeout_seconds))
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            data = httpx.Response(200, content=line).json()
                            content = data.get("message", {}).get("content")
                            if content:
                                emitted = True
                                yield content
                return
            except (httpx.TimeoutException, httpx.TransportError):
                if emitted or attempt >= self.max_retries:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
