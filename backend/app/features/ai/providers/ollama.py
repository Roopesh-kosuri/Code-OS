import asyncio
from collections.abc import AsyncIterator
import json
import logging

import httpx

from ....core.config import get_settings
from ..schemas import ChatMessage, ModelDto, ProviderHealth
from .base import AIProvider, ProviderRequestError, ProviderStreamEvent, ProviderToolCall

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

    async def stream_agent(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
        tools: list[dict] | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
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
                                    yield ProviderStreamEvent(type="text", content=content)
                                raw_calls = data.get("message", {}).get("tool_calls") or []
                                if raw_calls:
                                    calls: list[ProviderToolCall] = []
                                    for index, raw_call in enumerate(raw_calls):
                                        fn = raw_call.get("function", {})
                                        args = fn.get("arguments", {})
                                        if isinstance(args, str):
                                            try:
                                                args = json.loads(args)
                                            except json.JSONDecodeError:
                                                args = None
                                        calls.append(ProviderToolCall(
                                            id=str(raw_call.get("id", index)), name=str(fn.get("name", "")),
                                            arguments_json=json.dumps(args) if isinstance(args, dict) else str(args or ""),
                                            arguments=args if isinstance(args, dict) else None,
                                            complete=bool(fn.get("name") and isinstance(args, dict)),
                                        ))
                                    yield ProviderStreamEvent(
                                        type="tool_calls" if all(call.complete for call in calls) else "incomplete_tool_call",
                                        tool_calls=tuple(calls), finish_reason="tool_calls",
                                    )
                    return
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                    last_exc = exc
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                    body = ""
                    if isinstance(exc, httpx.HTTPStatusError):
                        try:
                            if hasattr(exc.response, "aread"):
                                await exc.response.aread()
                            body = exc.response.text
                        except Exception:
                            body = ""
                    category = "rate_limit" if status == 429 else ("authentication" if status in (401, 403) else ("not_found" if status == 404 else "transient"))
                    if emitted:
                        logger.error("Ollama stream_chat error mid-stream: %s", exc)
                        raise ProviderRequestError(_format_ollama_error(exc), status_code=status, body=body, category=category) from exc
                    if attempt < self.max_retries:
                        backoff = 0.5 * (attempt + 1)
                        is_rate_limit = status == 429
                        msg = f"Rate limited — retrying in {int(backoff)}s (attempt {attempt + 1}/{self.max_retries + 1})" if is_rate_limit else f"Provider connection issue — retrying in {int(backoff)}s (attempt {attempt + 1}/{self.max_retries + 1})"
                        yield ProviderStreamEvent(
                            type="retry",
                            content=msg,
                            retry_after_seconds=backoff,
                            attempt=attempt + 1,
                            max_attempts=self.max_retries + 1,
                            is_rate_limit=is_rate_limit,
                        )
                        await asyncio.sleep(backoff)
                    else:
                        break

        if last_exc:
            status = last_exc.response.status_code if isinstance(last_exc, httpx.HTTPStatusError) else None
            body = ""
            if isinstance(last_exc, httpx.HTTPStatusError):
                try:
                    if hasattr(last_exc.response, "aread"):
                        await last_exc.response.aread()
                    body = last_exc.response.text
                except Exception:
                    body = ""
            category = "rate_limit" if status == 429 else ("authentication" if status in (401, 403) else ("not_found" if status == 404 else "transient"))
            raise ProviderRequestError(_format_ollama_error(last_exc), status_code=status, body=body, category=category) from last_exc

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Legacy text stream retained for non-agent callers."""
        async for event in self.stream_agent(model, messages, temperature, tools=tools):
            if event.type == "text":
                yield event.content
