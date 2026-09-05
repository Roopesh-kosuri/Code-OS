from typing import Any
import asyncio
from collections.abc import AsyncIterator
import json
import logging
import re

import httpx

from ..schemas import ChatMessage, ModelDto, ProviderHealth, ContextOverflowError
from .base import AIProvider, ProviderRequestError, ProviderStreamEvent, ProviderToolCall

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


REASONING_EFFORT_MODELS = (
    "gpt-oss",
    "o1",
    "o3",
    "o4",
    "deepseek-reasoner",
    "deepseek-r1",
    "qwq",
    "kimi-k2-thinking",
)


def supports_reasoning_effort(provider_id: str, model_name: str) -> bool:
    """Return True only if the provider and model strictly accept OpenAI reasoning_effort."""
    if provider_id in ("nvidia-nim", "nvidia", "gemini", "mistral", "anthropic", "ollama", "local"):
        return False
    m = model_name.lower()
    return any(supported in m for supported in REASONING_EFFORT_MODELS)


class OpenAICompatibleProvider(AIProvider):
    id = "openai-compatible"

    def __init__(self, base_url: str, api_key: str | None, timeout_seconds: float = 180.0, max_retries: int = 1, provider_id: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        if provider_id:
            self.id = provider_id

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "https://github.com/code-os/code-os"
            headers["X-Title"] = "CODE OS"
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

    # HTTP status codes that should never be retried — the request is structurally wrong
    _NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 405, 422})
    # HTTP status codes that indicate transient server issues — safe to retry
    _RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

    async def stream_agent(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        tools: list[dict] | None = None,
        max_tokens: int | None = 16384,
        on_retry: Any = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        if self.id not in ("ollama", "local") and not self.api_key:
            raise ProviderRequestError(
                f"{self.id.capitalize()}: API key not configured. Please add your key in Settings.",
                category="authentication",
            )

        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        if reasoning_effort and supports_reasoning_effort(self.id, model):
            payload["reasoning_effort"] = reasoning_effort
        if max_tokens:
            # Groq on-demand models enforce an 8,000 TPM limit (prompt + max_tokens reservation).
            # Reserving 512 tokens keeps total request ~1800-2000 tokens, allowing multiple
            # sequential agent turns per minute without breaching the 8000 TPM window or tight TPD.
            effective_max_tokens = min(max_tokens, 512) if self.id == "groq" else max_tokens
            payload["max_tokens"] = effective_max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        emitted = False
        max_attempts = 8 if self.id == "groq" else 3
        # Per-chunk idle read timeout (35.0s) so hung/cold-starting endpoints fail-fast to recovery
        idle_read_timeout = 35.0

        for attempt in range(max_attempts):
            try:
                timeout = httpx.Timeout(
                    connect=15.0,
                    read=idle_read_timeout,
                    write=30.0,
                    pool=30.0,
                )
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=self.headers) as response:
                        status = response.status_code

                        # Non-200 responses: read body and log reality (B4)
                        if status != 200:
                            error_body = ""
                            try:
                                body_bytes = await response.aread()
                                error_body = body_bytes.decode("utf-8", errors="replace")
                            except Exception:
                                pass
                            logger.warning("Provider %s HTTP %d: %s", self.id, status, error_body[:300])

                            # ── 1. HTTP 429 or HTTP 413 TPM Rate Limit ──
                            is_rate_limit_resp = status == 429 or (
                                status == 413 and any(k in error_body.lower() for k in ("rate limit", "tpm", "tokens per minute", "try again in"))
                            )
                            if is_rate_limit_resp:
                                if attempt < max_attempts - 1:
                                    retry_header = response.headers.get("retry-after")
                                    header_delay = None
                                    if retry_header:
                                        try:
                                            raw_hdr = float(retry_header)
                                            # RFC 7231: Retry-After is in seconds.
                                            header_delay = raw_hdr / 1000.0 if raw_hdr > 10000 else raw_hdr
                                        except (ValueError, TypeError):
                                            pass

                                    body_delay = None
                                    if error_body:
                                        # 1. Google Gemini / RPC details: "retryDelay": "2.051638194s" or "2s"
                                        m_rpc = re.search(r'["\']?retryDelay["\']?\s*:\s*["\']?([\d.]+)\s*s?["\']?', error_body, re.IGNORECASE)
                                        if m_rpc:
                                            try:
                                                body_delay = float(m_rpc.group(1))
                                            except (ValueError, TypeError):
                                                pass

                                        if body_delay is None:
                                            # 2. Milliseconds: "try again in 500ms" or "retry in 250 ms"
                                            m_ms = re.search(r'(?:try\s+again|retry|wait)\s+(?:in|after)\s*([\d.]+)\s*ms\b', error_body, re.IGNORECASE)
                                            if m_ms:
                                                body_delay = float(m_ms.group(1)) / 1000.0
                                            else:
                                                # 3. Minutes: "try again in 1m 30s" or "retry after 2m"
                                                m_min = re.search(r'(?:try\s+again|retry|wait)\s+(?:in|after)\s*(\d+)\s*m(?!s)(?:in(?:utes?)?)?\s*(?:([\d.]+)\s*s)?', error_body, re.IGNORECASE)
                                                if m_min:
                                                    mins = float(m_min.group(1))
                                                    secs = float(m_min.group(2) or 0)
                                                    body_delay = mins * 60.0 + secs
                                                else:
                                                    # 4. Seconds: "Please retry in 2.051638194s", "try again in 30s", "retry after 5.2s"
                                                    m_sec = re.search(r'(?:try\s+again|retry|wait)\s+(?:in|after)\s*([\d.]+)\s*(?:s|sec|seconds)?\b', error_body, re.IGNORECASE)
                                                    if m_sec:
                                                        body_delay = float(m_sec.group(1))

                                    delays = [d for d in (header_delay, body_delay) if d is not None]
                                    parsed_delay = max(delays) if delays else None

                                    if parsed_delay is not None:
                                        if parsed_delay > 90.0:
                                            # Hard quota / daily limit exceeded (e.g. 7m wait) — fail fast
                                            raise ProviderRequestError(
                                                f"Rate limit / quota exceeded (HTTP {status}) on '{self.id}'. Server requested wait of {int(parsed_delay)}s.",
                                                status_code=status, body=error_body, category="rate_limit",
                                            )
                                        backoff = min(60.0, max(2.0, parsed_delay + 0.5) * (1.1 ** attempt))
                                        logger.warning("[RETRY] Rate limited (%d on %s). Server requested wait of %.1fs. Sleeping %.1fs (attempt %d/%d)...", status, self.id, parsed_delay, backoff, attempt + 1, max_attempts)
                                    else:
                                        backoff = min(20.0, (2.0 ** attempt) * 2.0)
                                        logger.warning("[RETRY] Rate limited (%d on %s). Sleeping %.1fs (attempt %d/%d)...", status, self.id, backoff, attempt + 1, max_attempts)

                                    msg = f"Rate limited — retrying in {int(backoff)}s (attempt {attempt + 1}/{max_attempts})"
                                    if on_retry:
                                        try:
                                            res = on_retry("retry", msg, retry_delay_seconds=int(backoff), attempt=attempt+1, max_attempts=max_attempts)
                                            if asyncio.iscoroutine(res):
                                                await res
                                        except Exception:
                                            pass
                                    yield ProviderStreamEvent(
                                        type="retry", content=msg, retry_after_seconds=backoff,
                                        attempt=attempt + 1, max_attempts=max_attempts, is_rate_limit=True,
                                    )
                                    remaining = backoff
                                    while remaining > 0:
                                        step = min(1.0, remaining)
                                        await asyncio.sleep(step)
                                        remaining -= step
                                        int_rem = int(round(remaining))
                                        if int_rem > 0 and int_rem % 5 == 0 and int_rem != int(backoff):
                                            tick_msg = f"Rate limited — retrying in {int_rem}s (attempt {attempt + 1}/{max_attempts})"
                                            yield ProviderStreamEvent(
                                                type="retry", content=tick_msg, retry_after_seconds=float(int_rem),
                                                attempt=attempt + 1, max_attempts=max_attempts, is_rate_limit=True,
                                            )
                                    continue
                                else:
                                    clean_err = error_body
                                    try:
                                        parsed = json.loads(error_body)
                                        if isinstance(parsed, list) and parsed:
                                            parsed = parsed[0]
                                        if isinstance(parsed, dict):
                                            clean_err = parsed.get("error", {}).get("message") or parsed.get("message") or error_body
                                    except Exception:
                                        pass
                                    if status == 413 or (status != 429 and any(k in clean_err.lower() for k in ("context", "too large", "maximum context"))):
                                        raise ContextOverflowError(f"Token limit / context exceeded (HTTP {status}) on '{self.id}': {clean_err}")
                                    raise ProviderRequestError(
                                        f"Rate limit / quota exceeded (HTTP {status}) on '{self.id}'. {clean_err}",
                                        status_code=status, body=clean_err, category="rate_limit",
                                    )

                            # ── 2. HTTP 5xx Server Errors (500, 502, 503, 504) ──
                            if status in (500, 502, 503, 504):
                                if attempt < max_attempts - 1:
                                    backoff = 2.0 * (attempt + 1)
                                    msg = f"Provider connection issue — retrying in {int(backoff)}s (attempt {attempt + 1}/{max_attempts})"
                                    if on_retry:
                                        try:
                                            res = on_retry("retry", msg, retry_delay_seconds=int(backoff), attempt=attempt+1, max_attempts=max_attempts)
                                            if asyncio.iscoroutine(res):
                                                await res
                                        except Exception:
                                            pass
                                    yield ProviderStreamEvent(
                                        type="retry", content=msg, retry_after_seconds=backoff,
                                        attempt=attempt + 1, max_attempts=max_attempts,
                                    )
                                    remaining = backoff
                                    while remaining > 0:
                                        step = min(1.0, remaining)
                                        await asyncio.sleep(step)
                                        remaining -= step
                                        int_rem = int(round(remaining))
                                        if int_rem > 0 and int_rem % 5 == 0 and int_rem != int(backoff):
                                            tick_msg = f"Provider connection issue — retrying in {int_rem}s (attempt {attempt + 1}/{max_attempts})"
                                            yield ProviderStreamEvent(
                                                type="retry", content=tick_msg, retry_after_seconds=float(int_rem),
                                                attempt=attempt + 1, max_attempts=max_attempts,
                                            )
                                    continue
                                else:
                                    raise ProviderRequestError(
                                        f"Provider connection issue (HTTP {status}) on '{self.id}': {error_body[:200]}",
                                        status_code=status, body=error_body, category="transient",
                                    )

                            # ── 3. HTTP 400 Context Overflow vs Other Bad Request ──
                            if status == 400:
                                err_lower = error_body.lower()
                                if any(k in err_lower for k in ("token", "length", "context")):
                                    raise ContextOverflowError(f"Context too large (HTTP 400): {error_body[:200]}")
                                raise ProviderRequestError(f"{self.id.capitalize()} API Error (HTTP 400): {error_body[:200]}", status_code=400, body=error_body, category="request")

                            # ── 4. HTTP 401 / 403 Authentication Errors ──
                            if status in (401, 403):
                                raise ProviderRequestError(f"{self.id.capitalize()} Authentication Error (HTTP {status}): {error_body[:200]}", status_code=status, body=error_body, category="authentication")

                            # ── 5. HTTP 404 Model Not Found ──
                            if status == 404:
                                raise ProviderRequestError(f"{self.id.capitalize()} Model Not Found (HTTP 404): {error_body[:200]}", status_code=404, body=error_body, category="not_found")

                            # ── 6. HTTP 413 Context / Payload Overflow ──
                            if status == 413:
                                err_lower = error_body.lower()
                                if any(k in err_lower for k in ("token", "length", "context", "tpm", "rate limit", "too large", "requested")):
                                    raise ContextOverflowError(f"Context/payload too large (HTTP 413): {error_body[:200]}")
                                raise ProviderRequestError(f"{self.id.capitalize()} Payload Too Large (HTTP 413): {error_body[:200]}", status_code=413, body=error_body, category="request")

                            # ── 7. Other 4xx Errors (405, 422) ──
                            raise ProviderRequestError(f"{self.id.capitalize()} API Error (HTTP {status}): {error_body[:200]}", status_code=status, body=error_body, category="request")

                        tool_call_deltas: dict[int, dict[str, str]] = {}
                        finish_reason: str | None = None

                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line.removeprefix("data: ").strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                            except Exception:
                                continue
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            content = delta.get("content")
                            reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                            tc_chunks = delta.get("tool_calls")
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]

                            if tc_chunks:
                                for tc in tc_chunks:
                                    idx = tc.get("index", 0)
                                    fn = tc.get("function", {})
                                    name = fn.get("name")
                                    args_piece = fn.get("arguments", "")

                                    if idx not in tool_call_deltas:
                                        tool_call_deltas[idx] = {"name": "", "arguments": ""}
                                    if name:
                                        tool_call_deltas[idx]["name"] += name
                                    if args_piece:
                                        tool_call_deltas[idx]["arguments"] += args_piece

                            if reasoning:
                                yield ProviderStreamEvent(type="reasoning", content=str(reasoning))

                            if content:
                                emitted = True
                                yield ProviderStreamEvent(type="text", content=str(content))

                        # Tool arguments are accumulated by index before a single
                        # structured event is released.  Never synthesize a text
                        # call here: the harness executes only parsed JSON objects.
                        if tool_call_deltas:
                            emitted = True
                            calls: list[ProviderToolCall] = []
                            complete = finish_reason != "length"
                            for idx in sorted(tool_call_deltas):
                                tc = tool_call_deltas[idx]
                                name = tc.get("name", "").strip()
                                raw_args = tc.get("arguments", "").strip()
                                parsed_args: dict[str, Any] | None = None
                                try:
                                    loaded = json.loads(raw_args)
                                    if isinstance(loaded, dict):
                                        parsed_args = loaded
                                    else:
                                        complete = False
                                except json.JSONDecodeError:
                                    complete = False
                                calls.append(ProviderToolCall(
                                    id=str(idx), name=name, arguments_json=raw_args,
                                    arguments=parsed_args, complete=bool(name and parsed_args is not None and complete),
                                ))
                            yield ProviderStreamEvent(
                                type="tool_calls" if complete else "incomplete_tool_call",
                                tool_calls=tuple(calls), finish_reason=finish_reason,
                            )

                        if finish_reason == "length" and not tool_call_deltas:
                            yield ProviderStreamEvent(type="finish", finish_reason="length")
                        elif finish_reason and not tool_call_deltas:
                            yield ProviderStreamEvent(type="finish", finish_reason=finish_reason)

                return
            except (httpx.TimeoutException, httpx.TransportError, TimeoutError) as exc:
                logger.warning("Provider %s connection/timeout error on attempt %d: %s", self.id, attempt + 1, exc)
                if emitted:
                    logger.error("OpenAICompatible stream_chat network/timeout error after partial response: %s", exc)
                    raise ProviderRequestError(
                        f"Provider connection issue on '{self.id}': {exc}", category="transient"
                    ) from exc
                if attempt < max_attempts - 1:
                    backoff = 2.0 * (attempt + 1)
                    msg = f"Provider connection issue — retrying in {int(backoff)}s (attempt {attempt + 1}/{max_attempts})"
                    if on_retry:
                        try:
                            res = on_retry("retry", msg, retry_delay_seconds=int(backoff), attempt=attempt+1, max_attempts=max_attempts)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass
                    yield ProviderStreamEvent(
                        type="retry", content=msg, retry_after_seconds=backoff,
                        attempt=attempt + 1, max_attempts=max_attempts,
                    )
                    await asyncio.sleep(backoff)
                    continue
                else:
                    logger.error("OpenAICompatible stream_chat exhausted %d attempts: %s", max_attempts, exc)
                    raise ProviderRequestError(
                        f"Provider connection issue on '{self.id}': {exc}", category="transient"
                    ) from exc
            except (ProviderRequestError, ContextOverflowError):
                raise
            except Exception as exc:
                if emitted:
                    logger.exception("Unexpected error in OpenAICompatible stream_chat: %s", exc)
                    raise ProviderRequestError(
                        f"Provider request failed on '{self.id}': {exc}", category="unknown"
                    ) from exc
                raise exc

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        tools: list[dict] | None = None,
        max_tokens: int | None = 16384,
        on_retry: Any = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str]:
        """Legacy text stream used by non-agent callers.

        Agent execution must use :meth:`stream_agent`; this adapter remains only
        to avoid changing unrelated chat, completion, and legacy agent paths in
        the same migration.
        """
        try:
            async for event in self.stream_agent(
                model, messages, temperature, tools=tools,
                max_tokens=max_tokens, on_retry=on_retry,
                reasoning_effort=reasoning_effort,
            ):
                if event.type == "text":
                    yield event.content
                elif event.type == "reasoning":
                    yield f"<reasoning>{event.content}</reasoning>"
                elif event.type == "retry":
                    yield f"[STATUS_RETRY: {event.content}]\n"
                elif event.type == "finish" and event.finish_reason == "length":
                    yield "\n[TRUNCATED: length]\n"
                elif event.type in ("tool_calls", "incomplete_tool_call"):
                    for call in event.tool_calls:
                        suffix = "[/TOOL_CALL]" if call.complete else "[TRUNCATED: length]"
                        yield f"\n[TOOL_CALL: {call.name}]\n{call.arguments_json}\n{suffix}\n"
        except ProviderRequestError as exc:
            if exc.category == "transient":
                yield f"\n[TRUNCATED: timeout]\n{_format_openai_error(exc, self.id)}\n"
            else:
                raise
