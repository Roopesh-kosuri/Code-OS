import asyncio
import json
import logging
from typing import AsyncIterator, List

import httpx

from ..schemas import ChatMessage, ContextOverflowError, ModelDto, ProviderHealth
from .base import AIProvider, ProviderRequestError, ProviderStreamEvent, ProviderToolCall

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

    async def stream_agent(
        self, model: str, messages: List[ChatMessage], temperature: float,
        tools: list[dict] | None = None, reasoning_effort: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
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
            "max_tokens": 8192,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()
        if tools:
            payload["tools"] = [
                {
                    "name": tool.get("function", {}).get("name", ""),
                    "description": tool.get("function", {}).get("description", ""),
                    "input_schema": tool.get("function", {}).get("parameters", {"type": "object", "properties": {}}),
                }
                for tool in tools
                if tool.get("function", {}).get("name")
            ]

        emitted = False
        for attempt in range(self.max_retries + 1):
            try:
                timeout = httpx.Timeout(self.timeout_seconds, connect=min(15.0, self.timeout_seconds))
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", f"{self.base_url}/messages", json=payload, headers=self.headers
                    ) as response:
                        response.raise_for_status()
                        tool_deltas: dict[int, dict[str, str]] = {}
                        finish_reason: str | None = None
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

                            if data.get("type") == "content_block_start":
                                block = data.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    idx = int(data.get("index", 0))
                                    initial = block.get("input", "")
                                    tool_deltas[idx] = {
                                        "id": str(block.get("id", idx)),
                                        "name": str(block.get("name", "")),
                                        "arguments": json.dumps(initial) if isinstance(initial, dict) else str(initial or ""),
                                    }
                            elif data.get("type") == "content_block_delta":
                                delta = data.get("delta", {})
                                if delta.get("type") == "input_json_delta":
                                    idx = int(data.get("index", 0))
                                    tool_deltas.setdefault(idx, {"id": str(idx), "name": "", "arguments": ""})
                                    tool_deltas[idx]["arguments"] += str(delta.get("partial_json", ""))
                                text = data.get("delta", {}).get("text")
                                if text:
                                    emitted = True
                                    yield ProviderStreamEvent(type="text", content=text)
                            elif data.get("type") == "message_delta":
                                finish_reason = data.get("delta", {}).get("stop_reason")
                        if tool_deltas:
                            calls: list[ProviderToolCall] = []
                            complete = finish_reason != "max_tokens"
                            for idx in sorted(tool_deltas):
                                raw = tool_deltas[idx]["arguments"]
                                parsed: dict | None = None
                                try:
                                    candidate = json.loads(raw)
                                    if isinstance(candidate, dict):
                                        parsed = candidate
                                    else:
                                        complete = False
                                except json.JSONDecodeError:
                                    complete = False
                                calls.append(ProviderToolCall(
                                    id=tool_deltas[idx]["id"], name=tool_deltas[idx]["name"],
                                    arguments_json=raw, arguments=parsed,
                                    complete=bool(parsed is not None and tool_deltas[idx]["name"] and complete),
                                ))
                            yield ProviderStreamEvent(
                                type="tool_calls" if complete else "incomplete_tool_call",
                                tool_calls=tuple(calls), finish_reason=finish_reason,
                            )
                return
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                body = ""
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        if hasattr(exc.response, "aread"):
                            await exc.response.aread()
                        body = exc.response.text
                    except Exception:
                        body = ""

                # Context overflow check
                if status == 400 and any(k in body.lower() for k in ("prompt is too long", "max_tokens", "context length", "context_length")):
                    raise ContextOverflowError(f"Anthropic context window exceeded: {body}") from exc

                if status in (401, 403):
                    raise ProviderRequestError(_format_anthropic_error(exc), status_code=status, body=body, category="authentication") from exc

                if status == 404:
                    raise ProviderRequestError(_format_anthropic_error(exc), status_code=status, body=body, category="not_found") from exc

                is_rate_limit = status == 429
                is_transient = (status is not None and status >= 500) or isinstance(exc, (httpx.TimeoutException, httpx.TransportError))

                if not emitted and attempt < self.max_retries and (is_rate_limit or is_transient):
                    backoff = 0.5 * (attempt + 1)
                    if is_rate_limit:
                        retry_after_hdr = exc.response.headers.get("retry-after") if hasattr(exc, "response") and exc.response else None
                        if retry_after_hdr:
                            try:
                                backoff = max(1.0, float(retry_after_hdr))
                            except ValueError:
                                pass
                        msg = f"Rate limited — retrying in {int(backoff)}s (attempt {attempt + 1}/{self.max_retries + 1})"
                    else:
                        msg = f"Provider connection issue — retrying in {int(backoff)}s (attempt {attempt + 1}/{self.max_retries + 1})"

                    yield ProviderStreamEvent(
                        type="retry",
                        content=msg,
                        retry_after_seconds=backoff,
                        attempt=attempt + 1,
                        max_attempts=self.max_retries + 1,
                        is_rate_limit=is_rate_limit,
                    )
                    await asyncio.sleep(backoff)
                    continue

                category = "rate_limit" if is_rate_limit else ("transient" if is_transient else "unknown")
                logger.error("Anthropic stream_chat error: %s", exc)
                raise ProviderRequestError(_format_anthropic_error(exc), status_code=status, body=body, category=category) from exc
            except Exception as exc:
                if isinstance(exc, (ProviderRequestError, ContextOverflowError)):
                    raise
                logger.exception("Unexpected error in Anthropic stream_chat: %s", exc)
                raise ProviderRequestError(_format_anthropic_error(exc), category="unknown") from exc

    async def stream_chat(
        self, model: str, messages: List[ChatMessage], temperature: float
    ) -> AsyncIterator[str]:
        """Legacy text stream retained for non-agent callers."""
        async for event in self.stream_agent(model, messages, temperature):
            if event.type == "text":
                yield event.content
