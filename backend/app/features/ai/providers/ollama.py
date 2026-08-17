import asyncio
from collections.abc import AsyncIterator
import json
import logging

import httpx

from ....core.config import get_settings
from ..schemas import ChatMessage, ModelDto, ProviderHealth
from .base import AIProvider

logger = logging.getLogger(__name__)


def _format_ollama_error(exc: Exception) -> str:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "[Error: Ollama provider request timed out. Please check your connection and try again.]"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "[Error: Authentication failed with Ollama. Please verify your settings.]"
        if code == 429:
            return "[Error: Rate limit reached for Ollama. Please wait 60 seconds before retrying.]"
        return f"[Error: Ollama provider returned status HTTP {code}.]"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return "[Error: Could not connect to Ollama. Please check if Ollama service is running on 127.0.0.1:11434 or select/configure an API provider in Settings.]"
    logger.exception("Ollama provider error: %s", exc)
    return "[Error: An unexpected error occurred while communicating with Ollama.]"


class OllamaProvider(AIProvider):
    id = "ollama"

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 300.0, max_retries: int = 1) -> None:
        effective_url = base_url.strip() if base_url and base_url.strip() else (get_settings().ollama_base_url or "http://127.0.0.1:11434")
        self.base_url = effective_url.rstrip('/')
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)

    def _urls_to_try(self) -> list[str]:
        urls = [self.base_url]
        if "127.0.0.1" in self.base_url:
            urls.append(self.base_url.replace("127.0.0.1", "localhost"))
        elif "localhost" in self.base_url:
            urls.append(self.base_url.replace("localhost", "127.0.0.1"))
        return urls

    async def health(self) -> ProviderHealth:
        for url in self._urls_to_try():
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.get(f"{url}/api/tags")
                    if res.status_code == 200:
                        self.base_url = url
                        return ProviderHealth(provider=self.id, healthy=True, message="Ollama is reachable")
            except Exception:
                continue
        return ProviderHealth(provider=self.id, healthy=False, message="Ollama is unreachable")

    async def models(self) -> list[ModelDto]:
        for url in self._urls_to_try():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.get(f"{url}/api/tags")
                    if res.status_code == 200:
                        self.base_url = url
                        payload = res.json()
                        result = []
                        for item in payload.get("models", []):
                            model_name = item.get("name") or item.get("model")
                            if model_name:
                                result.append(ModelDto(name=model_name, provider=self.id, details=item))
                        return result
            except Exception as exc:
                logger.debug("Ollama model fetch failed for url %s: %s", url, exc)
                continue
        logger.error("Ollama models retrieval failed for all URLs: %s", self._urls_to_try())
        return []

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        emitted = False
        last_exc = None
        for target_url in self._urls_to_try():
            for attempt in range(self.max_retries + 1):
                try:
                    timeout = httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds))
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        async with client.stream("POST", f"{target_url}/api/chat", json=payload) as response:
                            response.raise_for_status()
                            self.base_url = target_url
                            async for line in response.aiter_lines():
                                try:
                                    data = json.loads(line)
                                except Exception:
                                    continue
                                content = data.get("message", {}).get("content")
                                if content:
                                    emitted = True
                                    yield content
                    return
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                    last_exc = exc
                    if emitted:
                        logger.error("Ollama stream_chat error mid-stream: %s", exc)
                        yield _format_ollama_error(exc)
                        return
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.3)
                    else:
                        break

        if last_exc:
            yield _format_ollama_error(last_exc)
