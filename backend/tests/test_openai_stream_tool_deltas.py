import pytest
import json
from app.features.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.features.ai.schemas import ChatMessage
from app.features.ai.harness.plan_parser import _parse_tool_calls_extended
from app.features.ai.harness.sse_streamer import StreamReasoningFilter
from app.features.ai.providers.base import ProviderRequestError

REAL_RECORDED_GROQ_CHUNKS = [
    {"choices": [{"delta": {"reasoning": "We need to create calculator files in Python, Java, C, CPP. Use edit_file with original=\'\' for each. Proceed.", "channel": "analysis"}}]},
    {"choices": [{"delta": {"tool_calls": [{"id": "fc_01", "type": "function", "function": {"name": "edit_file", "arguments": "{\"path\": \"calculator/Calculator.java\","}, "index": 0}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"id": "fc_01", "type": "function", "function": {"arguments": " \"original\": \"\", \"updated\": \"public class Calculator {}\"}"}, "index": 0}]}}]},
    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
]


@pytest.mark.asyncio
async def test_accumulate_real_groq_deltas(monkeypatch):
    """Test that tool calls streamed across multiple deltas are properly accumulated into executable format."""
    provider = OpenAICompatibleProvider(base_url="https://api.groq.com/openai/v1", api_key="test_key", provider_id="groq")
    
    # Mock httpx response stream
    class MockStreamResponse:
        status_code = 200
        async def aiter_lines(self):
            for chunk in REAL_RECORDED_GROQ_CHUNKS:
                yield f"data: {json.dumps(chunk)}"
            yield "data: [DONE]"

    class MockAsyncClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            class ContextManager:
                async def __aenter__(self): return MockStreamResponse()
                async def __aexit__(self, *args): pass
            return ContextManager()

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    tokens = []
    reasoning_filter = StreamReasoningFilter()
    thinking_events = []
    visible_tokens = []

    async for token in provider.stream_chat(
        model="openai/gpt-oss-120b",
        messages=[ChatMessage(role="user", content="create calculator in 4 languages")],
        tools=[{"type": "function", "function": {"name": "edit_file"}}]
    ):
        tokens.append(token)
        for ev_type, ev_content in reasoning_filter.feed(token):
            if ev_type == "thinking":
                thinking_events.append(ev_content)
            elif ev_type == "token":
                visible_tokens.append(ev_content)

    for ev_type, ev_content in reasoning_filter.flush():
        if ev_type == "thinking":
            thinking_events.append(ev_content)
        elif ev_type == "token":
            visible_tokens.append(ev_content)

    full_output = "".join(tokens)
    
    # 1. Reasoning was converted to thinking events and stripped from visible tokens
    assert any("We need to create calculator files" in th for th in thinking_events)
    assert not any("We need to create calculator files" in tok for tok in visible_tokens)

    # 2. Tool calls were accumulated and formatted
    parsed_calls = _parse_tool_calls_extended(full_output)
    assert len(parsed_calls) == 1
    assert parsed_calls[0].name == "edit_file"
    assert parsed_calls[0].arguments.get("path") == "calculator/Calculator.java"
    assert parsed_calls[0].arguments.get("original") == ""
    assert "public class Calculator" in parsed_calls[0].arguments.get("updated", "")


@pytest.mark.asyncio
async def test_agent_stream_emits_complete_structured_call_without_text_parser(monkeypatch):
    """The agent contract exposes a validated call, not synthetic tool text."""
    provider = OpenAICompatibleProvider(base_url="https://api.groq.com/openai/v1", api_key="test_key", provider_id="groq")

    class Response:
        status_code = 200
        async def aiter_lines(self):
            for chunk in REAL_RECORDED_GROQ_CHUNKS:
                yield f"data: {json.dumps(chunk)}"
            yield "data: [DONE]"

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs):
            class Context:
                async def __aenter__(self): return Response()
                async def __aexit__(self, *args): pass
            return Context()

    monkeypatch.setattr("httpx.AsyncClient", Client)
    events = [event async for event in provider.stream_agent(
        "openai/gpt-oss-120b", [ChatMessage(role="user", content="create calculator")], 0.2,
        tools=[{"type": "function", "function": {"name": "edit_file"}}],
    )]
    calls = [event for event in events if event.type == "tool_calls"]
    assert len(calls) == 1
    assert calls[0].tool_calls[0].complete is True
    assert calls[0].tool_calls[0].arguments == {
        "path": "calculator/Calculator.java", "original": "", "updated": "public class Calculator {}"
    }
    assert all("[TOOL_CALL:" not in event.content for event in events)


@pytest.mark.asyncio
async def test_agent_stream_never_marks_truncated_json_executable(monkeypatch):
    """A length-stopped tool call remains incomplete and cannot reach execution."""
    provider = OpenAICompatibleProvider(base_url="https://api.groq.com/openai/v1", api_key="test_key", provider_id="groq")

    class Response:
        status_code = 200
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"edit_file","arguments":"{\\"path\\": \\"partial.py\\""}}]}}]}'
            yield 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}'
            yield "data: [DONE]"

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs):
            class Context:
                async def __aenter__(self): return Response()
                async def __aexit__(self, *args): pass
            return Context()

    monkeypatch.setattr("httpx.AsyncClient", Client)
    events = [event async for event in provider.stream_agent(
        "openai/gpt-oss-120b", [ChatMessage(role="user", content="create file")], 0.2,
        tools=[{"type": "function", "function": {"name": "edit_file"}}],
    )]
    incomplete = [event for event in events if event.type == "incomplete_tool_call"]
    assert len(incomplete) == 1
    assert incomplete[0].tool_calls[0].complete is False
    assert incomplete[0].tool_calls[0].arguments is None


@pytest.mark.asyncio
async def test_http_500_retry_is_not_labeled_rate_limited(monkeypatch):
    """Only actual HTTP 429 retries may set the rate-limit UI flag."""
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="test_key", provider_id="test")

    class Response:
        status_code = 500
        headers = {}
        async def aread(self): return b'{"error":"upstream unavailable"}'

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs):
            class Context:
                async def __aenter__(self): return Response()
                async def __aexit__(self, *args): pass
            return Context()

    async def no_sleep(*args, **kwargs): pass
    monkeypatch.setattr("httpx.AsyncClient", Client)
    monkeypatch.setattr("app.features.ai.providers.openai_compatible.asyncio.sleep", no_sleep)
    retries = []
    with pytest.raises(ProviderRequestError) as raised:
        async for event in provider.stream_agent("test", [ChatMessage(role="user", content="hello")], 0.2):
            retries.append(event)
    assert raised.value.status_code == 500
    assert len(retries) == 2
    assert all(event.is_rate_limit is False for event in retries)
    assert all("rate limited" not in event.content.lower() for event in retries)
