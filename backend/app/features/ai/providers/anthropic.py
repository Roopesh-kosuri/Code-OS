import asyncio
import json
import logging
from typing import AsyncIterator, List

import httpx

from ..schemas import ChatMessage, ModelDto, ProviderHealth
from .base import AIProvider

logger = logging.getLogger(__name__)


def _format_anthropic_error(exc: Exception) -> str:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "[Error: Anthropic provider request timed out. Please check your connection and try again.]"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "[Error: Authentication failed with Anthropic. Please verify your API key in Settings.]"
        if code == 429:
            return "[Error: Rate limit reached for Anthropic. Please wait 60 seconds before retrying.]"
        return f"[Error: Anthropic provider returned status HTTP {code}.]"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return "[Error: Could not connect to Anthropic. Please check your network connection.]"
    logger.exception("Anthropic provider error: %s", exc)
    return "[Error: An unexpected error occurred while communicating with Anthropic.]"


class AnthropicProvider(AIProvider):
    id = "anthropic"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @property
    def headers(self) -> dict[str, str]:
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(healthy=False, provider="anthropic", message="API key missing")
        return ProviderHealth(healthy=True, provider="anthropic", message="Configured")

    async def models(self) -> List[ModelDto]:
        return [
            ModelDto(name="claude-3-5-sonnet-latest", provider="anthropic", details={"label": "Claude 3.5 Sonnet"}),
            ModelDto(name="claude-3-5-haiku-latest", provider="anthropic", details={"label": "Claude 3.5 Haiku"}),
            ModelDto(name="claude-3-opus-latest", provider="anthropic", details={"label": "Claude 3 Opus"}),
        ]

    async def stream_chat(
        self, model: str, messages: List[ChatMessage], temperature: float
    ) -> AsyncIterator[str]:
        # Extract system prompt if provided
        system_prompt = ""
        user_messages = []
        for msg in messages:
            if msg.role == "system":
                system_prompt += f"{msg.content}\n"
            else:
                user_messages.append({"role": msg.role, "content": msg.content})

        if not user_messages:
            user_messages.append({"role": "user", "content": "Hello"})

        payload = {
            "model": model or "claude-3-5-sonnet-latest",
            "messages": user_messages,
            "max_tokens": 4096,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()

        emitted = False
        for attempt in range(self.max_retries + 1):
            try:
                timeout = httpx.Timeout(self.timeout_seconds, connect=min(15.0, self.timeout_seconds))
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", f"{self.base_url}/messages", json=payload, headers=self.headers
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line.removeprefix("data: ").strip()
                            if not data_str:
                                continue
                            try:
                                data = json.loads(data_str)
                            except Exception:
                                continue

                            if data.get("type") == "content_block_delta":
                                text = data.get("delta", {}).get("text")
                                if text:
                                    emitted = True
                                    yield text
                return
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                if emitted or attempt >= self.max_retries:
                    logger.error("Anthropic stream_chat error: %s", exc)
                    yield _format_anthropic_error(exc)
                    return
                await asyncio.sleep(0.5 * (attempt + 1))
            except Exception as exc:
                logger.exception("Unexpected error in Anthropic stream_chat: %s", exc)
                yield _format_anthropic_error(exc)
                return
