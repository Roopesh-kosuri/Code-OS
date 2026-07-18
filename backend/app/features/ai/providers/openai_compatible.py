import asyncio
from collections.abc import AsyncIterator

import httpx

from backend.app.features.ai.providers.base import AIProvider
from backend.app.features.ai.schemas import ChatMessage, ModelDto, ProviderHealth


class OpenAICompatibleProvider(AIProvider):
    id = "openai-compatible"

    def __init__(self, base_url: str, api_key: str | None, timeout_seconds: float = 60.0, max_retries: int = 1) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def health(self) -> ProviderHealth:
        try:
            await self.models()
            return ProviderHealth(provider=self.id, healthy=True, message="Provider is reachable")
        except Exception as exc:
            return ProviderHealth(provider=self.id, healthy=False, message=str(exc))

    async def models(self) -> list[ModelDto]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/models", headers=self.headers)
            response.raise_for_status()
            payload = response.json()
        return [ModelDto(name=item["id"], provider=self.id, details=item) for item in payload.get("data", [])]

    async def stream_chat(self, model: str, messages: list[ChatMessage], temperature: float) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        for attempt in range(self.max_retries + 1):
            emitted = False
            try:
                timeout = httpx.Timeout(self.timeout_seconds, connect=min(15.0, self.timeout_seconds))
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=self.headers) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line.removeprefix("data: ").strip()
                            if data == "[DONE]":
                                break
                            chunk = httpx.Response(200, content=data).json()
                            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                            if content:
                                emitted = True
                                yield content
                return
            except (httpx.TimeoutException, httpx.TransportError):
                if emitted or attempt >= self.max_retries:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
