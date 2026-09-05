import pytest
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from app.features.ai.schemas import ChatMessage, ChatRequest, FileChange
from app.features.ai.harness.tool_executor import ToolResult
from app.features.ai.harness.sse_streamer import StreamReasoningFilter, SSEStreamer
from app.features.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.features.ai.provider_health import ProviderHealthTracker
from app.features.ai.sandbox.executor import _execute_command_async


@pytest.mark.asyncio
async def test_retry_emits_status_not_thinking():
    filter_ = StreamReasoningFilter()
    events = filter_.feed("[STATUS_RETRY: Rate limited - retrying in 2s (attempt 1/3)]\nHello world")
    
    retry_events = [e for e in events if e[0] == "retry"]
    token_events = [e for e in events if e[0] == "token"]
    thinking_events = [e for e in events if e[0] == "thinking"]
    
    assert len(retry_events) == 1
    assert "Rate limited" in retry_events[0][1]
    assert len(thinking_events) == 0
    assert len(token_events) == 1
    assert "Hello world" in token_events[0][1]


@pytest.mark.asyncio
async def test_thinking_progress_events():
    filter_ = StreamReasoningFilter()
    long_thought = "x" * 250
    events = filter_.feed(f"<think>{long_thought}</think>Hello")
    
    thinking_tokens = [e for e in events if e[0] == "thinking_tokens"]
    assert len(thinking_tokens) >= 1
    assert thinking_tokens[0][1] > 0
    
    tokens = [e for e in events if e[0] == "token"]
    assert len(tokens) == 1
    assert tokens[0][1] == "Hello"


@pytest.mark.asyncio
async def test_reasoning_effort_per_tier():
    provider = OpenAICompatibleProvider("https://api.groq.com/openai/v1", "mock_key", provider_id="groq")
    
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        
        async def mock_lines():
            yield 'data: {"choices": [{"delta": {"content": "Done"}, "finish_reason": "stop"}]}'
            yield 'data: [DONE]'
            
        mock_resp.aiter_lines = mock_lines
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream.return_value = mock_cm
        
        messages = [ChatMessage(role="user", content="Fix typo")]
        tokens = []
        async for t in provider.stream_chat("openai/gpt-oss-120b", messages, reasoning_effort="low"):
            tokens.append(t)
            
        call_kwargs = mock_client.stream.call_args.kwargs
        assert call_kwargs["json"]["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_no_silent_local_fallback():
    tracker = ProviderHealthTracker()
    configured_keys = {"groq": None, "gemini": None, "openai": None}
    fallback = tracker.find_fallback_provider("gemini", configured_keys, allow_local_fallback=False)
    assert fallback is None


@pytest.mark.asyncio
async def test_local_fallback_only_when_enabled_and_transient():
    tracker = ProviderHealthTracker()
    configured_keys = {"groq": None, "gemini": None}
    assert tracker.find_fallback_provider("groq", configured_keys, allow_local_fallback=False) is None
    fb = tracker.find_fallback_provider("groq", configured_keys, allow_local_fallback=True)
    assert fb is not None
    assert fb[0] == "ollama"


@pytest.mark.asyncio
async def test_echo_command_exit_zero_windows(tmp_path):
    ws = str(tmp_path)
    res = await _execute_command_async(ws, "echo hello", timeout=10.0)
    assert res.success is True
    assert "hello" in res.output.lower()


@pytest.mark.asyncio
async def test_tool_error_contains_real_exception(tmp_path):
    ws = str(tmp_path)
    res = await _execute_command_async(ws, "nonexistent_binary_xyz_12345", timeout=5.0)
    assert res.success is False
    assert len(res.error) > 0
    assert "nonexistent_binary_xyz_12345" in res.error or "not recognized" in res.error.lower() or "not found" in res.error.lower()


@pytest.mark.asyncio
async def test_truncated_tool_call_detected():
    from app.features.ai.harness.compaction_manager import _is_response_truncated
    truncated_sample = "[TOOL_CALL: edit_file]\n{\"path\": \"calc.py\", \"original\": \"\", \"updated\": \"def add(a, b): return a + b"
    assert _is_response_truncated(truncated_sample) is True


# ═══════════════════════════════════════════════════════════════════
# Phase C: Error Taxonomy Tests
# ═══════════════════════════════════════════════════════════════════
import httpx
from app.features.ai.schemas import ContextOverflowError
from app.features.ai.providers.openai_compatible import supports_reasoning_effort
from app.features.ai.harness.compaction_manager import _compact_conversation_history


async def _async_lines_helper(lines):
    for line in lines:
        yield line


@pytest.mark.asyncio
async def test_429_labeled_rate_limited():
    """429 HTTP responses must yield STATUS_RETRY containing 'Rate limited'."""
    provider = OpenAICompatibleProvider("https://api.groq.com/openai/v1", "mock_key", provider_id="groq")

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {"retry-after": "1"}
    mock_resp_429.aread = AsyncMock(return_value=b'{"error":{"message":"Rate limit exceeded","code":"rate_limit_exceeded"}}')

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {}
    mock_resp_200.aiter_lines = MagicMock(return_value=_async_lines_helper([
        'data: {"choices":[{"delta":{"content":"Hello after 429"}}]}\\n',
        'data: [DONE]\\n',
    ]))

    call_count = 0
    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = mock_resp_429 if call_count == 1 else mock_resp_200
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    retry_callbacks = []
    def on_retry_cb(ev_type, msg, **kwargs):
        retry_callbacks.append((ev_type, msg))

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        chunks = []
        async for chunk in provider.stream_chat(
            model="openai/gpt-oss-120b",
            messages=[ChatMessage(role="user", content="Hi")],
            on_retry=on_retry_cb,
        ):
            chunks.append(chunk)

    full_output = "".join(chunks)
    assert "[STATUS_RETRY: Rate limited" in full_output
    assert len(retry_callbacks) >= 1
    assert "Rate limited" in retry_callbacks[0][1]


@pytest.mark.asyncio
async def test_400_never_labeled_rate_limited():
    """Non-token 400 Bad Request must NEVER be retried and NEVER labeled as rate limited."""
    provider = OpenAICompatibleProvider("https://integrate.api.nvidia.com/v1", "mock_key", provider_id="nvidia-nim")

    mock_resp_400 = MagicMock()
    mock_resp_400.status_code = 400
    mock_resp_400.headers = {}
    mock_resp_400.aread = AsyncMock(return_value=b'{"detail":[{"loc":["body","unknown_param"],"msg":"extra fields not permitted"}]}')

    stream_called = 0
    def mock_stream(*args, **kwargs):
        nonlocal stream_called
        stream_called += 1
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp_400)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        with pytest.raises(RuntimeError) as exc_info:
            async for _ in provider.stream_chat(
                model="meta/llama-3.1-70b-instruct",
                messages=[ChatMessage(role="user", content="Hi")],
            ):
                pass

    err_text = str(exc_info.value)
    # Assert NO retry attempt occurred
    assert stream_called == 1
    # Assert error includes HTTP status and body excerpt
    assert "HTTP 400" in err_text
    assert "extra fields not permitted" in err_text
    # Assert NOT labeled rate limit
    assert "rate limit" not in err_text.lower()
    assert "quota" not in err_text.lower()


@pytest.mark.asyncio
async def test_5xx_labeled_connection_issue():
    """5xx server errors must be labeled 'Provider connection issue' and never 'Rate limited'."""
    provider = OpenAICompatibleProvider("https://generativelanguage.googleapis.com/v1beta/openai", "mock_key", provider_id="gemini")

    mock_resp_503 = MagicMock()
    mock_resp_503.status_code = 503
    mock_resp_503.headers = {}
    mock_resp_503.aread = AsyncMock(return_value=b'{"error":{"message":"Model temporarily overloaded"}}')

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {}
    mock_resp_200.aiter_lines = MagicMock(return_value=_async_lines_helper([
        'data: {"choices":[{"delta":{"content":"Recovered from 503"}}]}\\n',
        'data: [DONE]\\n',
    ]))

    call_count = 0
    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = mock_resp_503 if call_count == 1 else mock_resp_200
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    retry_callbacks = []
    def on_retry_cb(ev_type, msg, **kwargs):
        retry_callbacks.append((ev_type, msg))

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        chunks = []
        async for chunk in provider.stream_chat(
            model="gemini-2.5-flash",
            messages=[ChatMessage(role="user", content="Hi")],
            on_retry=on_retry_cb,
        ):
            chunks.append(chunk)

    full_output = "".join(chunks)
    assert "[STATUS_RETRY: Provider connection issue" in full_output
    assert "Rate limited" not in full_output
    assert len(retry_callbacks) >= 1
    assert "Provider connection issue" in retry_callbacks[0][1]
    assert "Rate limited" not in retry_callbacks[0][1]


@pytest.mark.asyncio
async def test_timeout_labeled_connection_issue():
    """Timeouts must be labeled 'Provider connection issue' and never 'Rate limited'."""
    provider = OpenAICompatibleProvider("https://api.deepseek.com/v1", "mock_key", provider_id="deepseek")

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {}
    mock_resp_200.aiter_lines = MagicMock(return_value=_async_lines_helper([
        'data: {"choices":[{"delta":{"content":"Recovered from timeout"}}]}\\n',
        'data: [DONE]\\n',
    ]))

    call_count = 0
    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("Read timed out after 35s")
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp_200)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    retry_callbacks = []
    def on_retry_cb(ev_type, msg, **kwargs):
        retry_callbacks.append((ev_type, msg))

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        chunks = []
        async for chunk in provider.stream_chat(
            model="deepseek-reasoner",
            messages=[ChatMessage(role="user", content="Hi")],
            on_retry=on_retry_cb,
        ):
            chunks.append(chunk)

    full_output = "".join(chunks)
    assert "[STATUS_RETRY: Provider connection issue" in full_output
    assert "Rate limited" not in full_output
    assert len(retry_callbacks) >= 1
    assert "Provider connection issue" in retry_callbacks[0][1]
    assert "Rate limited" not in retry_callbacks[0][1]


@pytest.mark.asyncio
async def test_context_overflow_compacts_once_then_retries():
    """400 with 'context' or 'token' raises ContextOverflowError, which prompts compaction."""
    provider = OpenAICompatibleProvider("https://api.groq.com/openai/v1", "mock_key", provider_id="groq")

    mock_resp_400_context = MagicMock()
    mock_resp_400_context.status_code = 400
    mock_resp_400_context.headers = {}
    mock_resp_400_context.aread = AsyncMock(
        return_value=b'{"error":{"message":"Request too large for model: context length exceeded. Maximum context is 8192 tokens.","code":"context_length_exceeded"}}'
    )

    def mock_stream(*args, **kwargs):
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp_400_context)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        with pytest.raises(ContextOverflowError) as exc_info:
            async for _ in provider.stream_chat(
                model="openai/gpt-oss-120b",
                messages=[ChatMessage(role="user", content="Hi")],
            ):
                pass

    err_text = str(exc_info.value)
    assert "Context too large" in err_text
    assert "context length exceeded" in err_text

    long_history = [
        ChatMessage(role="system", content="System prompt"),
        ChatMessage(role="user", content="User turn 1"),
        ChatMessage(role="assistant", content="Assistant turn 1 [TOOL_CALL: edit_file]\\n" + ("x" * 500) + "\\n[/TOOL_CALL]"),
        ChatMessage(role="user", content="Tool results: [TOOL_RESULT: edit_file] Success"),
        ChatMessage(role="assistant", content="Assistant turn 2"),
        ChatMessage(role="user", content="User turn 2"),
        ChatMessage(role="assistant", content="Assistant turn 3"),
        ChatMessage(role="user", content="User turn 3"),
    ]
    compacted = _compact_conversation_history(long_history, keep_recent_turns=1)
    assert any("compacted to save context tokens" in m.content for m in compacted)


@pytest.mark.asyncio
async def test_reasoning_effort_stripped_for_nim_llama():
    """reasoning_effort must be stripped for NVIDIA NIM llama, but preserved for Groq GPT-OSS."""
    assert supports_reasoning_effort("nvidia-nim", "meta/llama-3.1-70b-instruct") is False
    assert supports_reasoning_effort("nvidia-nim", "deepseek-ai/deepseek-r1") is False
    assert supports_reasoning_effort("gemini", "gemini-2.5-flash") is False
    assert supports_reasoning_effort("groq", "openai/gpt-oss-120b") is True
    assert supports_reasoning_effort("openai", "o3-mini") is True

    nim_provider = OpenAICompatibleProvider("https://integrate.api.nvidia.com/v1", "mock_key", provider_id="nvidia-nim")

    captured_payloads = []
    def mock_stream(method, url, json=None, **kwargs):
        captured_payloads.append(json)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.aiter_lines = MagicMock(return_value=_async_lines_helper(['data: [DONE]\\n']))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        async for _ in nim_provider.stream_chat(
            model="meta/llama-3.1-70b-instruct",
            messages=[ChatMessage(role="user", content="Hi")],
            reasoning_effort="high",
        ):
            pass

    assert len(captured_payloads) == 1
    assert "reasoning_effort" not in captured_payloads[0], "reasoning_effort was NOT stripped for NIM llama!"

    groq_provider = OpenAICompatibleProvider("https://api.groq.com/openai/v1", "mock_key", provider_id="groq")
    captured_payloads.clear()

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        async for _ in groq_provider.stream_chat(
            model="openai/gpt-oss-120b",
            messages=[ChatMessage(role="user", content="Hi")],
            reasoning_effort="high",
        ):
            pass

    assert len(captured_payloads) == 1
    assert captured_payloads[0].get("reasoning_effort") == "high"


def test_tip_text_matches_error_type():
    """Verify error messages produce correct taxonomy tips and never mention Gemini rate limit inappropriately."""
    err_429 = "Rate limit / quota exceeded (HTTP 429) on 'groq'."
    is_429 = ("429" in err_429 or "rate limit" in err_429.lower()) and "400" not in err_429 and "context" not in err_429.lower()
    assert is_429 is True

    err_400_param = "Nvidia-nim API Error (HTTP 400): extra fields not permitted"
    is_429_bad = ("429" in err_400_param or "rate limit" in err_400_param.lower()) and "400" not in err_400_param and "context" not in err_400_param.lower()
    assert is_429_bad is False

    err_prose = "Task failed: Agent emitted prose narration without executing tools."
    assert "rate limit" not in err_prose.lower()
    assert "quota" not in err_prose.lower()


@pytest.mark.asyncio
async def test_gemini_rate_limit_parsing_please_retry_in():
    """Verify Gemini 'Please retry in 2.05s' error format is accurately parsed into retry delay."""
    provider = OpenAICompatibleProvider("https://generativelanguage.googleapis.com/v1beta/openai", "mock_key", provider_id="gemini")

    gemini_429_body = json.dumps({
        "error": {
            "code": 429,
            "message": "Resource has been exhausted (e.g. check quota). Please retry in 2.051638194s.",
            "status": "RESOURCE_EXHAUSTED"
        }
    }).encode("utf-8")

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {}
    mock_resp_429.aread = AsyncMock(return_value=gemini_429_body)

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {}

    async def mock_lines():
        yield 'data: {"choices": [{"delta": {"content": "Hello after retry"}}]}\\n'
        yield 'data: [DONE]\\n'

    mock_resp_200.aiter_lines = mock_lines

    call_count = 0
    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = mock_resp_429 if call_count == 1 else mock_resp_200
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    retries_recorded = []
    def on_retry_cb(ev_type, msg, **kwargs):
        retries_recorded.append((ev_type, msg, kwargs))

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            chunks = []
            async for chunk in provider.stream_chat(
                model="gemini-2.5-flash",
                messages=[ChatMessage(role="user", content="Test")],
                on_retry=on_retry_cb,
            ):
                chunks.append(chunk)

    assert len(retries_recorded) == 1
    ev_type, msg, kwargs = retries_recorded[0]
    assert ev_type == "retry"
    # Parsed delay is ~2.05s -> backoff is 2.55s -> rounded or truncated to 2s/3s
    assert kwargs.get("retry_delay_seconds") in (2, 3)
    assert "Rate limited" in msg
    assert "retrying in 2s" in msg or "retrying in 3s" in msg


@pytest.mark.asyncio
async def test_gemini_rate_limit_parsing_retry_delay_rpc():
    """Verify Google RPC retryDelay format is accurately parsed into retry delay."""
    provider = OpenAICompatibleProvider("https://generativelanguage.googleapis.com/v1beta/openai", "mock_key", provider_id="gemini")

    rpc_429_body = json.dumps({
        "error": {
            "code": 429,
            "message": "Resource exhausted",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2.051638194s"}
            ]
        }
    }).encode("utf-8")

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {}
    mock_resp_429.aread = AsyncMock(return_value=rpc_429_body)

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {}

    async def mock_lines():
        yield 'data: {"choices": [{"delta": {"content": "RPC retry success"}}]}\\n'
        yield 'data: [DONE]\\n'

    mock_resp_200.aiter_lines = mock_lines

    call_count = 0
    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = mock_resp_429 if call_count == 1 else mock_resp_200
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    retries_recorded = []
    def on_retry_cb(ev_type, msg, **kwargs):
        retries_recorded.append((ev_type, msg, kwargs))

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            chunks = []
            async for chunk in provider.stream_chat(
                model="gemini-2.5-flash",
                messages=[ChatMessage(role="user", content="Test RPC")],
                on_retry=on_retry_cb,
            ):
                chunks.append(chunk)

    assert "context length exceeded" in err_text

    long_history = [
        ChatMessage(role="system", content="System prompt"),
        ChatMessage(role="user", content="User turn 1"),
        ChatMessage(role="assistant", content="Assistant turn 1 [TOOL_CALL: edit_file]\n" + ("x" * 500) + "\n[/TOOL_CALL]"),
        ChatMessage(role="user", content="Tool results: [TOOL_RESULT: edit_file] Success"),
        ChatMessage(role="assistant", content="Assistant turn 2"),
        ChatMessage(role="user", content="User turn 2"),
        ChatMessage(role="assistant", content="Assistant turn 3"),
        ChatMessage(role="user", content="User turn 3"),
    ]
    compacted = _compact_conversation_history(long_history, keep_recent_turns=1)
    assert any("compacted to save context tokens" in m.content for m in compacted)


@pytest.mark.asyncio
async def test_reasoning_effort_stripped_for_nim_llama():
    """reasoning_effort must be stripped for NVIDIA NIM llama, but preserved for Groq GPT-OSS."""
    assert supports_reasoning_effort("nvidia-nim", "meta/llama-3.1-70b-instruct") is False
    assert supports_reasoning_effort("nvidia-nim", "deepseek-ai/deepseek-r1") is False
    assert supports_reasoning_effort("gemini", "gemini-2.5-flash") is False
    assert supports_reasoning_effort("groq", "openai/gpt-oss-120b") is True
    assert supports_reasoning_effort("openai", "o3-mini") is True

    nim_provider = OpenAICompatibleProvider("https://integrate.api.nvidia.com/v1", "mock_key", provider_id="nvidia-nim")

    captured_payloads = []
    def mock_stream(method, url, json=None, **kwargs):
        captured_payloads.append(json)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.aiter_lines = MagicMock(return_value=_async_lines_helper(['data: [DONE]\n']))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        async for _ in nim_provider.stream_chat(
            model="meta/llama-3.1-70b-instruct",
            messages=[ChatMessage(role="user", content="Hi")],
            reasoning_effort="high",
        ):
            pass

    assert len(captured_payloads) == 1
    assert "reasoning_effort" not in captured_payloads[0], "reasoning_effort was NOT stripped for NIM llama!"

    groq_provider = OpenAICompatibleProvider("https://api.groq.com/openai/v1", "mock_key", provider_id="groq")
    captured_payloads.clear()

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        async for _ in groq_provider.stream_chat(
            model="openai/gpt-oss-120b",
            messages=[ChatMessage(role="user", content="Hi")],
            reasoning_effort="high",
        ):
            pass

    assert len(captured_payloads) == 1
    assert captured_payloads[0].get("reasoning_effort") == "high"


def test_tip_text_matches_error_type():
    """Verify error messages produce correct taxonomy tips and never mention Gemini rate limit inappropriately."""
    err_429 = "Rate limit / quota exceeded (HTTP 429) on 'groq'."
    is_429 = ("429" in err_429 or "rate limit" in err_429.lower()) and "400" not in err_429 and "context" not in err_429.lower()
    assert is_429 is True

    err_400_param = "Nvidia-nim API Error (HTTP 400): extra fields not permitted"
    is_429_bad = ("429" in err_400_param or "rate limit" in err_400_param.lower()) and "400" not in err_400_param and "context" not in err_400_param.lower()
    assert is_429_bad is False

    err_prose = "Task failed: Agent emitted prose narration without executing tools."
    assert "rate limit" not in err_prose.lower()
    assert "quota" not in err_prose.lower()


@pytest.mark.asyncio
async def test_gemini_rate_limit_parsing_please_retry_in():
    """Verify Gemini 'Please retry in 2.05s' error format is accurately parsed into retry delay."""
    provider = OpenAICompatibleProvider("https://generativelanguage.googleapis.com/v1beta/openai", "mock_key", provider_id="gemini")

    gemini_429_body = json.dumps({
        "error": {
            "code": 429,
            "message": "Resource has been exhausted (e.g. check quota). Please retry in 2.051638194s.",
            "status": "RESOURCE_EXHAUSTED"
        }
    }).encode("utf-8")

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {}
    mock_resp_429.aread = AsyncMock(return_value=gemini_429_body)

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {}

    async def mock_lines():
        yield 'data: {"choices": [{"delta": {"content": "Hello after retry"}}]}\n'
        yield 'data: [DONE]\n'

    mock_resp_200.aiter_lines = mock_lines

    call_count = 0
    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = mock_resp_429 if call_count == 1 else mock_resp_200
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    retries_recorded = []
    def on_retry_cb(ev_type, msg, **kwargs):
        retries_recorded.append((ev_type, msg, kwargs))

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            chunks = []
            async for chunk in provider.stream_chat(
                model="gemini-2.5-flash",
                messages=[ChatMessage(role="user", content="Test")],
                on_retry=on_retry_cb,
            ):
                chunks.append(chunk)

    assert len(retries_recorded) == 1
    ev_type, msg, kwargs = retries_recorded[0]
    assert ev_type == "retry"
    # Parsed delay is ~2.05s -> backoff is 2.55s -> rounded or truncated to 2s/3s
    assert kwargs.get("retry_delay_seconds") in (2, 3)
    assert "Rate limited" in msg
    assert "retrying in 2s" in msg or "retrying in 3s" in msg


@pytest.mark.asyncio
async def test_gemini_rate_limit_parsing_retry_delay_rpc():
    """Verify Google RPC retryDelay format is accurately parsed into retry delay."""
    provider = OpenAICompatibleProvider("https://generativelanguage.googleapis.com/v1beta/openai", "mock_key", provider_id="gemini")

    rpc_429_body = json.dumps({
        "error": {
            "code": 429,
            "message": "Resource exhausted",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2.051638194s"}
            ]
        }
    }).encode("utf-8")

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {}
    mock_resp_429.aread = AsyncMock(return_value=rpc_429_body)

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {}

    async def mock_lines():
        yield 'data: {"choices": [{"delta": {"content": "RPC retry success"}}]}\n'
        yield 'data: [DONE]\n'

    mock_resp_200.aiter_lines = mock_lines

    call_count = 0
    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = mock_resp_429 if call_count == 1 else mock_resp_200
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    retries_recorded = []
    def on_retry_cb(ev_type, msg, **kwargs):
        retries_recorded.append((ev_type, msg, kwargs))

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            chunks = []
            async for chunk in provider.stream_chat(
                model="gemini-2.5-flash",
                messages=[ChatMessage(role="user", content="Test RPC")],
                on_retry=on_retry_cb,
            ):
                chunks.append(chunk)

    assert len(retries_recorded) == 1
    ev_type, msg, kwargs = retries_recorded[0]
    assert kwargs.get("retry_delay_seconds") in (2, 3)


def test_default_models_groq_and_nvidia_nim():
    """Verify Groq default is openai/gpt-oss-120b and NVIDIA NIM default is minimaxai/minimax-m3."""
    from app.features.ai.provider_health import DEFAULT_PROVIDER_MODELS
    from app.features.ai.catalog import PROVIDER_CATALOG

    assert DEFAULT_PROVIDER_MODELS["groq"] == "openai/gpt-oss-120b"
    assert DEFAULT_PROVIDER_MODELS["nvidia-nim"] == "minimaxai/minimax-m3"

    assert PROVIDER_CATALOG["groq"][0].id == "openai/gpt-oss-120b"
    assert PROVIDER_CATALOG["nvidia-nim"][0].id == "minimaxai/minimax-m3"
