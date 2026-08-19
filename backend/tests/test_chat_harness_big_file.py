"""
test_chat_harness_big_file.py — Tests for large file chunking, truncation detection, honest completion guard, and append_file.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.chat_harness import (
    run_chat_agent,
    ChatAgentRequest,
    _handle_append_file,
    _validate_smart_edit,
    _is_response_truncated,
    _declares_tool_intent,
    _extract_heuristic_tool_calls,
    FileChange,
    _pending_approvals,
    approve_action,
)


def test_handle_append_file_chunks(tmp_path):
    """Verify that multiple append_file calls aggregate into a single FileChange."""
    staged: list[FileChange] = []
    ws = str(tmp_path)

    # 1. Edit file first chunk (300 lines)
    valid, err, change = _validate_smart_edit(ws, {
        "path": "hello.html",
        "original": "",
        "updated": "\n".join([f"<!-- Line {i} -->" for i in range(1, 301)]) + "\n",
    })
    assert valid is True
    staged.append(change)
    assert len(staged) == 1
    assert len(staged[0].updated.splitlines()) == 300

    # 2. Append chunk 2 (400 lines)
    chunk2 = "\n".join([f"<!-- Chunk2 Line {i} -->" for i in range(301, 701)])
    valid2, err2, change2 = _handle_append_file(ws, {
        "path": "hello.html",
        "content": chunk2,
    }, staged)
    assert valid2 is True
    assert len(staged) == 1  # Still 1 consolidated FileChange
    assert len(staged[0].updated.splitlines()) == 700

    # 3. Append chunk 3 (350 lines)
    chunk3 = "\n".join([f"<!-- Chunk3 Line {i} -->" for i in range(701, 1051)])
    valid3, err3, change3 = _handle_append_file(ws, {
        "path": "hello.html",
        "content": chunk3,
    }, staged)
    assert valid3 is True
    assert len(staged) == 1
    assert len(staged[0].updated.splitlines()) == 1050


def test_truncation_detection():
    """Verify detection of truncated tool calls and length limit markers."""
    # Truncated tool call (open tag, no close tag)
    assert _is_response_truncated("[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"original\": \"\", \"updated\": \"<div") is True

    # Complete tool call
    assert _is_response_truncated("[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"updated\": \"ok\"}\n[/TOOL_CALL]") is False

    # Explicit length truncation marker
    assert _is_response_truncated("Some text [TRUNCATED: length]") is True


def test_declares_tool_intent_and_heuristics():
    """Verify tool intent phrases and heuristic rescue."""
    assert _declares_tool_intent("We'll output edit_file call for hello.html") is True
    assert _declares_tool_intent("I will create hello.html with 1000+ lines") is True
    assert _declares_tool_intent("Let's write the portfolio code") is True

    # Heuristic extraction of code block into edit_file
    resp = "I will create the file:\n```html\n<!DOCTYPE html>\n<html><body>Portfolio</body></html>\n```"
    calls = _extract_heuristic_tool_calls(resp, "create hello.html")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "hello.html"


@pytest.mark.asyncio
async def test_truncation_retry_then_recovery(tmp_path):
    """Verify that a truncated tool call triggers a retry prompting chunking."""
    ws = str(tmp_path)
    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=ws,
        messages=[{"role": "user", "content": "create hello.html, 1000+ line portfolio"}],
    )

    # Turn 1: Truncated response mid-JSON
    turn1 = ["[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"updated\": \"<html"]
    # Turn 2: Recovered chunked tool call
    turn2 = [
        "[TOOL_CALL: edit_file]\n",
        '{"path": "hello.html", "original": "", "updated": "<!DOCTYPE html>\\n<html>\\n<body>\\n"}\n',
        "[/TOOL_CALL]\n",
        "[TOOL_CALL: append_file]\n",
        '{"path": "hello.html", "content": "<h1>My 1000+ Line Portfolio</h1>\\n</body>\\n</html>"}\n',
        "[/TOOL_CALL]\n\n",
        "Portfolio created!\n[DONE]"
    ]

    async def mock_s1(*args, **kwargs):
        for c in turn1:
            yield c

    async def mock_s2(*args, **kwargs):
        for c in turn2:
            yield c


    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_s1(), mock_s2()])


    async def auto_approver():
        for _ in range(20):
            await asyncio.sleep(0.05)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    await approve_action(act_id)
                break

    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        with patch("app.features.ai.chat_harness.create_proposal", new=AsyncMock(return_value=MagicMock(id="prop-big"))):
            with patch("app.features.ai.service.apply_proposal", new=AsyncMock(return_value=MagicMock())):
                approver_task = asyncio.create_task(auto_approver())
                events = []
                async for chunk in run_chat_agent(req):
                    events.append(chunk)

                await approver_task
                full = "".join(events)
                assert "truncated by token limit" in full or "instructing agent to chunk" in full
                assert "event: proposal" in full
                assert "event: done" in full
                assert '"success": true' in full


@pytest.mark.asyncio
async def test_honest_completion_guard_on_zero_tools(tmp_path):
    """Verify that a run ending with 0 tool executions on a create request reports honest failure."""
    ws = str(tmp_path)
    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=ws,
        messages=[{"role": "user", "content": "create hello.html with a huge layout"}],
    )

    # Agent just says some prose and outputs nothing / no tool call (2 responses needed:
    # initial attempt + 1 retry before an honest-failure guard fires).
    # Either the zero-tools guard ("Nothing was generated") or the repetition-breaker
    # ("repeating near-identical responses") fires — both are valid honest-failure paths.
    prose1 = ["Here is an explanation of what a portfolio should look like. That concludes the advice."]
    prose2 = ["As I mentioned, a portfolio should have these key elements. This concludes my response."]

    async def mock_stream_prose(*args, **kwargs):
        for c in prose1:
            yield c

    async def mock_stream_prose2(*args, **kwargs):
        for c in prose2:
            yield c

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream_prose(), mock_stream_prose2()])

    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        events = []
        async for chunk in run_chat_agent(req):
            events.append(chunk)

        full = "".join(events)
        # Both "Nothing was generated" and repetition-breaker are valid honest-failure signals
        assert (
            "Nothing was generated" in full
            or "repeating" in full.lower()
            or "no tool" in full.lower()
        ), f"Expected an honest failure signal, got: {full[:500]}"
        assert '"success": false' in full
