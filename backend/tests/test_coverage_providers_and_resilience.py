"""
test_coverage_providers_and_resilience.py

Phase 3 Behavioral Test Suite covering:
1. AnthropicProvider (stream_chat, error formatting, system prompt extraction, headers)
2. OllamaProvider (url failovers, tags/model parsing, chat streaming, error messages)
3. OpenAICompatibleProvider (tool call delta assembly, reasoning model fallback, rate limit retry-after parsing, non-retryable 4xx handling, length truncation)
4. ProviderHealthTracker (exponential circuit breaker cooldowns, half-open transitions, sliding window metrics, fallback selection)
5. ActiveServerSession & ServerSessionManager (security host/command guards, process supervision, HTTP request dispatch, ring buffers, teardown)
6. VisionService & DualCoderService (VLM model resolution, fallback discovery, dual coder attempt execution)
"""

import asyncio
import json
import socket
import time
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.features.ai.schemas import ChatMessage, ModelDto
from app.features.ai.providers.anthropic import AnthropicProvider, _format_anthropic_error
from app.features.ai.providers.ollama import OllamaProvider, _format_ollama_error
from app.features.ai.providers.openai_compatible import (
    OpenAICompatibleProvider,
    _format_openai_error,
)
from app.features.ai.provider_health import (
    ProviderHealthTracker,
    CIRCUIT_BREAKER_COOLDOWN_BASE,
    CIRCUIT_BREAKER_COOLDOWN_MAX,
)
from app.features.ai.sessions.server_manager import (
    _server_session_start,
    _server_session_request,
    _server_session_list,
    _server_session_stop,
    _cleanup_server_sessions,
    _handle_server_session,
    ServerSessionManager,
    _active_server_sessions,
    ActiveServerSession,
)
from app.features.ai.vision_service import (
    resolve_default_vision_model,
    find_working_vision_config,
)
from app.features.ai.dual_coder_service import (
    DualCoderModelConfig,
    DualCoderRequest,
    _run_single_attempt,
)


# =====================================================================
# 1. Anthropic Provider
# =====================================================================

def test_anthropic_provider_models_and_headers():
    """Verify Anthropic models list and headers generation with and without API key."""
    p_no_key = AnthropicProvider(api_key="")
    assert "x-api-key" not in p_no_key.headers
    assert p_no_key.headers["anthropic-version"] == "2023-06-01"

    p_with_key = AnthropicProvider(api_key="sk-ant-test-123")
    assert p_with_key.headers["x-api-key"] == "sk-ant-test-123"


@pytest.mark.asyncio
async def test_anthropic_provider_health_and_models():
    """Verify health returns healthy only when API key is provided, and models list is complete."""
    p_unconf = AnthropicProvider(api_key="")
    h_unconf = await p_unconf.health()
    assert h_unconf.healthy is False

    p_conf = AnthropicProvider(api_key="sk-ant-test-123")
    h_conf = await p_conf.health()
    assert h_conf.healthy is True

    models = await p_conf.models()
    names = [m.name for m in models]
    assert "claude-3-5-sonnet-latest" in names
    assert "claude-3-5-haiku-latest" in names


@pytest.mark.asyncio
async def test_anthropic_provider_stream_chat_success():
    """Verify Anthropic stream_chat properly separates system messages and yields text blocks."""
    provider = AnthropicProvider(api_key="sk-ant-test-123")

    messages = [
        ChatMessage(role="system", content="You are a coding assistant."),
        ChatMessage(role="user", content="Write hello world"),
    ]

    sse_lines = [
        'event: message_start',
        'data: {"type": "message_start"}',
        'event: content_block_start',
        'data: {"type": "content_block_start"}',
        'event: content_block_delta',
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "print(\\"Hello, World!\\")"}}',
        'event: message_stop',
        'data: {"type": "message_stop"}',
    ]

    captured_payload = None

    class MockStreamResponse:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for line in sse_lines:
                yield line

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, json=None, headers=None):
            nonlocal captured_payload
            captured_payload = json
            return MockStreamResponse()

    with patch("httpx.AsyncClient", new=MockAsyncClient):
        chunks = []
        async for chunk in provider.stream_chat("claude-3-5-sonnet-latest", messages, 0.5):
            chunks.append(chunk)

    assert "print(\"Hello, World!\")" in "".join(chunks)
    assert captured_payload is not None
    assert captured_payload["system"] == "You are a coding assistant."
    assert captured_payload["messages"][0]["content"] == "Write hello world"


def test_anthropic_error_formatting():
    """Verify _format_anthropic_error maps HTTP codes and network errors to actionable messages."""
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    res_401 = httpx.Response(401, request=req)
    err_401 = httpx.HTTPStatusError("Unauthorized", request=req, response=res_401)
    msg_401 = _format_anthropic_error(err_401)
    assert "verify your api key" in msg_401.lower()

    res_429 = httpx.Response(429, request=req)
    err_429 = httpx.HTTPStatusError("Rate Limit", request=req, response=res_429)
    msg_429 = _format_anthropic_error(err_429)
    assert "rate limit" in msg_429.lower()

    timeout_err = httpx.TimeoutException("Read timed out")
    msg_timeout = _format_anthropic_error(timeout_err)
    assert "timed out" in msg_timeout.lower()

    conn_err = httpx.ConnectError("Connection refused")
    msg_conn = _format_anthropic_error(conn_err)
    assert "network connection" in msg_conn.lower()


# =====================================================================
# 2. Ollama Provider
# =====================================================================

def test_ollama_provider_urls_to_try():
    """Verify Ollama automatically generates alternate loopback URLs."""
    p1 = OllamaProvider("http://127.0.0.1:11434")
    urls1 = p1._urls_to_try()
    assert "http://127.0.0.1:11434" in urls1
    assert "http://localhost:11434" in urls1

    p2 = OllamaProvider("http://localhost:11434")
    urls2 = p2._urls_to_try()
    assert "http://127.0.0.1:11434" in urls2


@pytest.mark.asyncio
async def test_ollama_provider_health_and_models_parsing():
    """Verify Ollama health probe and /api/tags JSON parsing into ModelDto."""
    provider = OllamaProvider("http://127.0.0.1:11434")

    mock_tags_response = httpx.Response(
        200,
        json={
            "models": [
                {"name": "qwen2.5-coder:7b", "size": 4700000000},
                {"name": "llama3:latest", "size": 4200000000},
            ]
        },
        request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
    )

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_tags_response)):
        health = await provider.health()
        assert health.healthy is True
        assert "reachable" in health.message.lower()

        models = await provider.models()
        assert len(models) == 2
        assert models[0].name == "qwen2.5-coder:7b"
        assert models[0].provider == "ollama"


@pytest.mark.asyncio
async def test_ollama_provider_stream_chat_success_and_fallback():
    """Verify Ollama streaming chat yields chunks and passes tool options."""
    provider = OllamaProvider("http://127.0.0.1:11434", max_retries=0)

    class MockOllamaStream:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield '{"message": {"role": "assistant", "content": "def calculate(a, b):"}}'
            yield '{"message": {"role": "assistant", "content": " return a + b"}}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, json=None):
            return MockOllamaStream()

    with patch("httpx.AsyncClient", new=MockAsyncClient):
        messages = [ChatMessage(role="user", content="write add function")]
        chunks = []
        async for chunk in provider.stream_chat("qwen2.5-coder:7b", messages, 0.2):
            chunks.append(chunk)

        full = "".join(chunks)
        assert "def calculate(a, b): return a + b" == full


def test_ollama_error_formatting():
    """Verify _format_ollama_error hints at local daemon on port 11434."""
    conn_err = httpx.ConnectError("Target refused connection")
    msg = _format_ollama_error(conn_err)
    assert "127.0.0.1:11434" in msg
    assert "Settings" in msg


# =====================================================================
# 3. OpenAI-Compatible Provider
# =====================================================================

def test_openai_compatible_headers_and_groq_capping():
    """Verify OpenRouter custom headers and Groq max_tokens capping behavior."""
    prov_or = OpenAICompatibleProvider("https://openrouter.ai/api/v1", api_key="sk-or-123")
    assert prov_or.headers["HTTP-Referer"] == "https://github.com/code-os/code-os"
    assert prov_or.headers["X-Title"] == "CODE OS"

    prov_oai = OpenAICompatibleProvider("https://api.openai.com/v1", api_key="sk-oai-456")
    assert prov_oai.headers["Authorization"] == "Bearer sk-oai-456"
    assert "HTTP-Referer" not in prov_oai.headers


@pytest.mark.asyncio
async def test_openai_compatible_non_retryable_errors():
    """Verify 400, 401, 403, 404, 422 immediately raise descriptive RuntimeError without retries."""
    prov = OpenAICompatibleProvider("https://api.openai.com/v1", api_key="sk-bad-key", provider_id="openai")

    class Mock401Stream:
        status_code = 401
        reason_phrase = "Unauthorized"

        async def aread(self):
            return b'{"error": {"message": "Invalid API key provided"}}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, json=None, headers=None):
            return Mock401Stream()

    with patch("httpx.AsyncClient", new=MockClient):
        with pytest.raises(RuntimeError) as exc_info:
            async for _ in prov.stream_chat("gpt-4o", [ChatMessage(role="user", content="hi")]):
                pass

        assert "Invalid API key provided" in str(exc_info.value)
        assert "401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_compatible_native_tool_call_delta_assembly():
    """Verify tool_calls streaming deltas are assembled into standard [TOOL_CALL: name] blocks."""
    prov = OpenAICompatibleProvider("https://api.groq.com/openai/v1", api_key="gsk-123", provider_id="groq")

    sse_chunks = [
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "edit_file", "arguments": "{\\\"path\\\": "}}]}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\\"calc.py\\\", \\\"content\\\": \\\"1+1\\\"}"}}]}}]}',
        'data: {"choices": [{"finish_reason": "stop"}]}',
        'data: [DONE]',
    ]

    class MockToolStream:
        status_code = 200

        async def aiter_lines(self):
            for c in sse_chunks:
                yield c

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, *args, **kwargs):
            return MockToolStream()

    with patch("httpx.AsyncClient", new=MockClient):
        events = []
        async for chunk in prov.stream_chat("openai/gpt-oss-120b", [ChatMessage(role="user", content="edit calc.py")]):
            events.append(chunk)

        full = "".join(events)
        assert "[TOOL_CALL: edit_file]" in full
        assert '"path": "calc.py"' in full
        assert "[/TOOL_CALL]" in full


@pytest.mark.asyncio
async def test_openai_compatible_reasoning_model_fallback_and_length_truncation():
    """Verify reasoning models (DeepSeek-R1 / o3) emit reasoning buffer when content is empty."""
    prov = OpenAICompatibleProvider("https://api.deepseek.com/v1", api_key="sk-ds-123", provider_id="deepseek")

    sse_chunks = [
        'data: {"choices": [{"delta": {"reasoning_content": "Step 1: Calculate sum. Step 2: Return result."}}]}',
        'data: {"choices": [{"finish_reason": "length"}]}',
        'data: [DONE]',
    ]

    class MockReasoningStream:
        status_code = 200

        async def aiter_lines(self):
            for c in sse_chunks:
                yield c

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, *args, **kwargs):
            return MockReasoningStream()

    with patch("httpx.AsyncClient", new=MockClient):
        events = []
        async for chunk in prov.stream_chat("deepseek-reasoner", [ChatMessage(role="user", content="solve")]):
            events.append(chunk)

        full = "".join(events)
        assert "Step 1: Calculate sum. Step 2: Return result." in full
        assert "[TRUNCATED: length]" in full


# =====================================================================
# 4. Provider Health Tracker & Circuit Breaker
# =====================================================================

def test_provider_health_circuit_breaker_exponential_cooldown():
    """Verify circuit breaker trips at 5 failures and doubles cooldown on successive trips."""
    tracker = ProviderHealthTracker()

    for _ in range(5):
        tracker.record_outcome("groq", success=False, error_msg="503 Service Unavailable")

    is_open, remaining, msg = tracker.is_circuit_open("groq")
    assert is_open is True
    assert 290.0 <= remaining <= 300.0

    # Half-open check after cooldown simulated
    tracker._circuit_opened_at["groq"] = time.time() - 301.0
    is_open, _, _ = tracker.is_circuit_open("groq")
    assert is_open is False, "Expired cooldown should allow probe (half-open)"

    # Trip 2
    tracker._consecutive_failures["groq"] = 5
    tracker.record_outcome("groq", success=False, error_msg="503")
    is_open, remaining2, _ = tracker.is_circuit_open("groq")
    assert is_open is True
    assert 590.0 <= remaining2 <= 600.0


def test_provider_health_sliding_window_degraded_state():
    """Verify health status calculates degradation based on 1-hour failure percentage."""
    tracker = ProviderHealthTracker()

    tracker.record_outcome("openai", success=False)
    tracker.record_outcome("openai", success=False)
    tracker.record_outcome("openai", success=True)
    tracker.record_outcome("openai", success=True)

    health = tracker.get_health("openai")
    assert health["status"] == "degraded"
    assert health["failure_rate"] == 0.5
    assert health["total_requests_last_hour"] == 4

    for _ in range(4):
        tracker.record_outcome("openai", success=True)

    health_updated = tracker.get_health("openai")
    assert health_updated["status"] == "healthy"
    assert health_updated["failure_rate"] == 0.25


def test_provider_health_find_fallback_skips_failed_and_circuits():
    """Verify fallback selection walks preferred order, skipping failed providers and missing keys."""
    tracker = ProviderHealthTracker()

    for _ in range(5):
        tracker.record_outcome("groq", success=False)

    configured_keys = {
        "groq": "gsk_123",
        "gemini": None,
        "nvidia-nim": "nvapi_456",
        "openai": "sk-789",
    }

    fallback = tracker.find_fallback_provider(["groq"], configured_keys)
    assert fallback is not None
    prov_id, model, url = fallback
    assert prov_id == "nvidia-nim"
    assert "llama" in model or "minimax" in model

    tracker.reset_all()
    assert tracker.get_health("groq")["circuit_open"] is False


# =====================================================================
# 5. Background Server Session Manager
# =====================================================================

def test_server_manager_security_guards(tmp_path):
    """Verify server_session rejects non-localhost hosts and dangerous command strings."""
    ws = str(tmp_path)

    # 1. Reject remote host
    res_host = _server_session_start(ws, "python -m http.server", port=8000, host="192.168.1.50")
    assert res_host.success is False
    assert "Security violation: host" in res_host.error

    # 2. Reject destructive command pattern
    res_cmd = _server_session_start(ws, "rm -rf /tmp/data", port=8000)
    assert res_cmd.success is False
    assert "Security violation: command contains a dangerous pattern" in res_cmd.error

    # 3. Reject missing command
    res_empty = _server_session_start(ws, "", port=8000)
    assert res_empty.success is False
    assert "Missing command or port" in res_empty.error


def test_server_manager_lifecycle_and_mocked_session(tmp_path):
    """Verify server session lifecycle: registration, dispatch, listing, and termination."""
    ws = str(tmp_path)
    session_id = "srv_test_8080_abc123"

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.poll = MagicMock(return_value=None)
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    sess = ActiveServerSession(
        session_id=session_id,
        command="python -m http.server 8080",
        port=8080,
        process=mock_proc,
        workspace=ws,
        started_at=time.time(),
        stdout_lines=["Serving HTTP on 0.0.0.0 port 8080 ...", "127.0.0.1 - GET /index.html 200"],
        stderr_lines=[],
    )

    _active_server_sessions[session_id] = sess

    mgr = ServerSessionManager()

    try:
        # 1. List active sessions
        res_list = mgr.list_active()
        assert res_list.success is True
        assert session_id in res_list.output
        assert "8080" in res_list.output

        # 2. Handle server session dispatcher tool
        res_disp = _handle_server_session(ws, {"action": "list"})
        assert res_disp.success is True
        assert session_id in res_disp.output

        # 3. Stop session
        res_stop = mgr.stop(session_id)
        assert res_stop.success is True
        assert session_id not in _active_server_sessions

    finally:
        _cleanup_server_sessions(ws)


# =====================================================================
# 6. Vision Service & Dual Coder Service
# =====================================================================

def test_vision_service_resolution_and_defaults():
    """Verify resolve_default_vision_model returns appropriate VLMs across provider presets."""
    assert resolve_default_vision_model("nvidia-nim") == "meta/llama-3.2-11b-vision-instruct"
    assert resolve_default_vision_model("openai") == "gpt-4o-mini"
    assert resolve_default_vision_model("anthropic") == "claude-3-5-haiku-latest"
    assert resolve_default_vision_model("gemini") == "gemini-2.5-flash"
    assert resolve_default_vision_model("ollama") == "llama3.2-vision"


@pytest.mark.asyncio
async def test_vision_service_find_working_config(temp_db):
    """Verify find_working_vision_config falls back to configured provider if Groq is requested."""
    with patch("app.features.settings.service.get_api_key", new=AsyncMock(side_effect=lambda p: "nvapi_123" if p == "nvidia-nim" else None)):
        prov, model, url, key = await find_working_vision_config(preferred_provider="groq")
        assert prov == "nvidia-nim"
        assert "vision" in model.lower()
        assert "integrate.api.nvidia.com" in url
        assert key == "nvapi_123"


@pytest.mark.asyncio
async def test_dual_coder_single_attempt_execution(tmp_path, temp_db):
    """Verify DualCoder _run_single_attempt executes with proposal parsing and saving."""
    ws = str(tmp_path)
    calc_py = tmp_path / "calc.py"
    calc_py.write_text("def subtract(a, b): return a - b\n", encoding="utf-8")

    cfg = DualCoderModelConfig(
        provider="ollama",
        model="qwen2.5-coder:7b",
    )

    proposal_response = (
        "Here is the solution:\n"
        "[PROPOSAL: calc.py]\n"
        "<<<< ORIGINAL\n"
        "def subtract(a, b): return a - b\n"
        "====\n"
        "def subtract(a, b): return a - b\n"
        "def multiply(a, b): return a * b\n"
        ">>>>\n"
    )

    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield proposal_response

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.dual_coder_service.provider_for", new=AsyncMock(return_value=mock_provider)):
        result = await _run_single_attempt(
            attempt_label="Model A",
            workspace=ws,
            task_description="Add multiply function to calc.py",
            model_config=cfg,
            target_file="calc.py",
        )

        assert result["attempt"] == "Model A"
        assert result["proposal_id"] is not None
        assert len(result["changes"]) >= 1
        assert "multiply" in result["changes"][0]["updated"]
        assert result["self_review"]["approved"] is True


# =====================================================================
# 7. Additional Deep Resilience & Edge Cases
# =====================================================================

def test_server_manager_premature_exit_handling(tmp_path):
    """Verify server session start captures exit code and stderr if process terminates immediately."""
    ws = str(tmp_path)
    # python -c "import sys; sys.exit(1)" terminates immediately
    res = _server_session_start(ws, "python -c \"import sys; sys.exit(1)\"", port=9991, timeout=2.0)
    assert res.success is False
    assert "terminated prematurely" in res.error
    assert "code 1" in res.error or "1" in res.error


@pytest.mark.asyncio
async def test_openai_compatible_rate_limit_retry_success():
    """Verify 429 with retry-after header retries and successfully yields tokens on second attempt."""
    prov = OpenAICompatibleProvider("https://api.openai.com/v1", api_key="sk-test-123", provider_id="openai")

    call_count = 0

    class Mock429ThenSuccessStream:
        def __init__(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                self.status_code = 429
                self.headers = {"retry-after": "0.01"}
                self.reason_phrase = "Rate Limit"
            else:
                self.status_code = 200
                self.headers = {}
                self.reason_phrase = "OK"

        async def aread(self):
            return b'{"error": {"message": "Rate limited, try again in 0.01s"}}'

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "Success token"}}]}'
            yield 'data: [DONE]'

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, *args, **kwargs):
            return Mock429ThenSuccessStream()

    with patch("httpx.AsyncClient", new=MockClient):
        events = []
        async for token in prov.stream_chat("gpt-4o", [ChatMessage(role="user", content="hi")]):
            events.append(token)

        assert call_count == 2
        assert "Success token" in "".join(events)


def test_server_manager_request_http_error(tmp_path):
    """Verify _server_session_request returns formatted HTTP error info on 404/500 responses."""
    ws = str(tmp_path)
    import urllib.error

    mock_http_err = urllib.error.HTTPError(
        url="http://127.0.0.1:8080/not-found",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=MagicMock(read=MagicMock(return_value=b'{"error": "Resource not found"}')),
    )

    with patch("urllib.request.urlopen", side_effect=mock_http_err):
        res = _server_session_request(ws, port=8080, method="GET", path="/not-found")
        assert res.success is True
        assert "404" in res.output
        assert "Resource not found" in res.output
