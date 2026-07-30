import asyncio
from collections.abc import AsyncIterator
import json
import logging

import httpx

from ..schemas import ChatMessage, ModelDto, ProviderHealth
from .base import AIProvider

logger = logging.getLogger(__name__)


def _format_openai_error(exc: Exception, provider_id: str = "AI") -> str:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return f"[Error: {provider_id} provider request timed out. Please check your connection and try again.]"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return f"[Error: Authentication failed with {provider_id}. Please verify your API key in Settings.]"
        if code == 429:
            return f"[Error: Rate limit reached for {provider_id}. Please wait 60 seconds before retrying.]"
        return f"[Error: {provider_id} provider returned status HTTP {code}.]"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return f"[Error: Could not connect to {provider_id}. Please check your network connection.]"
    logger.exception("OpenAI-compatible provider error: %s", exc)
    return f"[Error: An unexpected error occurred while communicating with {provider_id}.]"


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
        emitted = False
        for attempt in range(self.max_retries + 1):
            try:
                timeout = httpx.Timeout(self.timeout_seconds, connect=min(15.0, self.timeout_seconds))
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=self.headers) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line.removeprefix("data: ").strip()
                            try:
                                chunk = json.loads(data)
                            except Exception:
                                continue
                            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                            if content:
                                emitted = True
                                yield content

                return
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                if emitted or attempt >= self.max_retries:
                    logger.error("OpenAICompatible stream_chat error: %s", exc)
                    yield _format_openai_error(exc, self.id)
                    return
                await asyncio.sleep(0.5 * (attempt + 1))
            except Exception as exc:
                logger.exception("Unexpected error in OpenAICompatible stream_chat: %s", exc)
                yield _format_openai_error(exc, self.id)
                return
