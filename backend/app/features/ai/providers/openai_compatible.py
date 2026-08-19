import asyncio
from collections.abc import AsyncIterator
import json
import logging
import re

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

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        tools: list[dict] | None = None,
        max_tokens: int | None = 16384,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            if "groq.com" in self.base_url:
                payload["max_tokens"] = min(max_tokens, 2048)
            else:
                payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        emitted = False
        max_attempts = 2
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

                        # ── Non-retryable errors: fail immediately ──
                        if status in self._NON_RETRYABLE_STATUS:
                            error_body = ""
                            try:
                                body_bytes = await response.aread()
                                error_body = body_bytes.decode("utf-8", errors="replace")
                                err_json = json.loads(error_body)
                                err_msg = err_json.get("error", {}).get("message") or err_json.get("message") or error_body
                            except Exception:
                                err_msg = error_body or f"HTTP {status} {response.reason_phrase}"
                            raise RuntimeError(f"{self.id.capitalize()} API Error ({status}): {err_msg}")

                        # ── Rate limit (429): retry with adaptive backoff based on server hints ──
                        if status == 429:
                            error_body = ""
                            try:
                                body_bytes = await response.aread()
                                error_body = body_bytes.decode("utf-8", errors="replace")
                            except Exception:
                                pass

                            if attempt < max_attempts - 1:
                                retry_header = response.headers.get("retry-after")
                                parsed_delay = None

                                if retry_header:
                                    try:
                                        raw_hdr = float(retry_header)
                                        parsed_delay = raw_hdr / 1000.0 if raw_hdr > 100 else raw_hdr
                                    except (ValueError, TypeError):
                                        pass

                                if parsed_delay is None and error_body:
                                    match = re.search(r'try again in\s*([\d.]+)\s*(s|sec|seconds|ms|m)?', error_body, re.IGNORECASE)
                                    if match:
                                        val = float(match.group(1))
                                        unit = (match.group(2) or 's').lower()
                                        if unit == 'ms':
                                            parsed_delay = val / 1000.0
                                        elif unit == 'm':
                                            parsed_delay = val * 60.0
                                        else:
                                            parsed_delay = val

                                if parsed_delay is not None:
                                    backoff = min(20.0, max(2.0, parsed_delay + 0.5) * (1.2 ** attempt))
                                    logger.warning("[RETRY] Rate limited (429 on %s). Server requested wait of %.1fs. Sleeping %.1fs (attempt %d/%d)...", self.id, parsed_delay, backoff, attempt + 1, max_attempts)
                                else:
                                    backoff = min(20.0, (2.0 ** attempt) * 2.0)
                                    logger.warning("[RETRY] Rate limited (429 on %s). Sleeping %.1fs (attempt %d/%d)...", self.id, backoff, attempt + 1, max_attempts)

                                await asyncio.sleep(backoff)
                                continue
                            else:
                                clean_429 = error_body
                                try:
                                    parsed = json.loads(error_body)
                                    if isinstance(parsed, list) and parsed:
                                        parsed = parsed[0]
                                    if isinstance(parsed, dict):
                                        clean_429 = parsed.get("error", {}).get("message") or parsed.get("message") or error_body
                                except Exception:
                                    pass
                                raise RuntimeError(f"Rate limit / quota exceeded (HTTP 429) on '{self.id}'. {clean_429}")

                        # ── Retryable server errors (502/503/504) ──
                        if status in self._RETRYABLE_STATUS:
                            if attempt < max_attempts - 1:
                                backoff = 2.0 * (attempt + 1)
                                logger.warning("[RETRY] Server error (HTTP %d). Backing off %.1fs (attempt %d/%d)", status, backoff, attempt + 1, max_attempts)
                                await asyncio.sleep(backoff)
                                continue
                            else:
                                raise RuntimeError(f"Server error (HTTP {status}) after {max_attempts} attempts on provider '{self.id}'.")

                        # ── Other 4xx/5xx: fail immediately ──
                        if status >= 400:
                            error_body = ""
                            try:
                                body_bytes = await response.aread()
                                error_body = body_bytes.decode("utf-8", errors="replace")
                                err_json = json.loads(error_body)
                                err_msg = err_json.get("error", {}).get("message") or err_json.get("message") or error_body
                            except Exception:
                                err_msg = error_body or f"HTTP {status} {response.reason_phrase}"
                            raise RuntimeError(f"{self.id.capitalize()} API Error ({status}): {err_msg}")

                        # ── Success: stream tokens ──
                        reasoning_buffer: list[str] = []
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

                            if content:
                                emitted = True
                                yield content
                            elif reasoning and not emitted:
                                reasoning_buffer.append(reasoning)

                        # If tool calls were emitted natively, format them into [TOOL_CALL: name] blocks
                        if tool_call_deltas:
                            emitted = True
                            for idx in sorted(tool_call_deltas.keys()):
                                tc = tool_call_deltas[idx]
                                tc_name = tc.get("name", "").strip()
                                tc_args = tc.get("arguments", "").strip()
                                if tc_name:
                                    # If finish_reason was length or arguments are truncated JSON, emit unclosed or truncated marker
                                    if finish_reason == "length":
                                        yield f"\n[TOOL_CALL: {tc_name}]\n{tc_args}\n[TRUNCATED: length]\n"
                                    else:
                                        yield f"\n[TOOL_CALL: {tc_name}]\n{tc_args}\n[/TOOL_CALL]\n"

                        # Fallback for pure reasoning models that put the final output in reasoning deltas
                        if not emitted and reasoning_buffer:
                            fallback_reasoning = "".join(reasoning_buffer).strip()
                            if fallback_reasoning:
                                emitted = True
                                yield fallback_reasoning

                        if finish_reason == "length" and not tool_call_deltas:
                            yield "\n[TRUNCATED: length]\n"

                return
            except (httpx.TimeoutException, httpx.TransportError, TimeoutError) as exc:
                if emitted:
                    logger.error("OpenAICompatible stream_chat network/timeout error after partial response: %s", exc)
                    yield f"\n[TRUNCATED: timeout]\n{_format_openai_error(exc, self.id)}\n"
                    return
                if attempt >= max_attempts - 1:
                    logger.error("OpenAICompatible stream_chat exhausted %d attempts: %s", max_attempts, exc)
                    raise RuntimeError(f"Network timeout / connection error with {self.id}: {exc}") from exc
                backoff = 1.5 * (attempt + 1)
                logger.warning("[RETRY] Network/timeout error: %s. Backing off %.1fs (attempt %d/%d)", type(exc).__name__, backoff, attempt + 1, max_attempts)
                await asyncio.sleep(backoff)
            except RuntimeError:
                raise
            except Exception as exc:
                if emitted:
                    logger.exception("Unexpected error in OpenAICompatible stream_chat: %s", exc)
                    yield f"\n[TRUNCATED: error]\n{_format_openai_error(exc, self.id)}\n"
                    return
                raise exc
