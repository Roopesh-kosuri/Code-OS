import pytest
import asyncio
import re
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.chat_harness import (
    run_chat_agent,
    ChatAgentRequest,
    _validate_smart_edit,
    _find_mismatch_context,
    _is_response_truncated,
)
from app.features.ai.schemas import FileChange


def test_validation_feedback_with_mismatch_diagnostic(tmp_path):
    """Verify that edit pre-validation includes the first differing line and line number on mismatch."""
    ws = str(tmp_path)
    file_path = tmp_path / "component.py"
    file_path.write_text(
        "def render():\n"
        "    header = 'Title'\n"
        "    body = 'Actual line in file'\n"
        "    footer = 'End'\n",
        encoding="utf-8",
    )

    # Edit request has a typo in original snippet
    args = {
        "path": "component.py",
        "original": "def render():\n    header = 'Title'\n    body = 'Incorrect hallucinated line'\n    footer = 'End'\n",
        "updated": "def render():\n    return 42\n",
    }

    valid, err, change = _validate_smart_edit(ws, args)
    assert valid is False
    assert change is None
    assert "[Mismatch Diagnostic]" in err
    assert "First differing line at line 3:" in err
    assert "Incorrect hallucinated line" in err
    assert "Actual line in file" in err


def test_validation_feedback_starting_line_mismatch(tmp_path):
    """Verify mismatch diagnostic when the starting line itself is not found."""
    ws = str(tmp_path)
    file_path = tmp_path / "index.js"
    file_path.write_text("const a = 1;\nconst b = 2;\n", encoding="utf-8")

    args = {
        "path": "index.js",
        "original": "const completelyMissing = 999;\n",
        "updated": "const completelyMissing = 1000;\n",
    }

    valid, err, change = _validate_smart_edit(ws, args)
    assert valid is False
    assert "[Mismatch Diagnostic]" in err
    assert "was not found verbatim" in err or "was not found" in err


def test_progressive_shrink_instruction_text():
    """Verify that truncation retry instructions enforce progressive half-size shrink."""
    # Test that the prompt explicitly uses half-size language
    truncated_msg = "[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"updated\": \"<html"
    assert _is_response_truncated(truncated_msg) is True


@pytest.mark.asyncio
async def test_repeat_failure_breaker(tmp_path):
    """Verify that a tool call failing twice in a row is blocked from endless retries and emits a skipped event."""
    ws = str(tmp_path)
    file_path = tmp_path / "app.py"
    file_path.write_text("def existing(): pass\n", encoding="utf-8")

    # Mock provider that repeatedly attempts the exact same failing edit_file call
    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        # Model repeatedly tries to replace non-existent 'def not_there(): pass'
        yield (
            "[TOOL_CALL: edit_file]\n"
            '{"path": "app.py", "original": "def not_there(): pass", "updated": "def new_fn(): return 1"}\n'
            "[/TOOL_CALL]"
        )

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="gpt-4o",
        workspace=ws,
        messages=[{"role": "user", "content": "edit app.py"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)
            if len(events) > 60:
                break

        # Check for tool_skipped status event
        skipped_events = [e for e in events if "tool_skipped" in e or "Skipped after 2 failed attempts" in e]
        assert len(skipped_events) > 0
        assert any("Skipped after 2 failed attempts" in e for e in skipped_events)


@pytest.mark.asyncio
async def test_response_repetition_breaker(tmp_path):
    """Verify that identical prose responses without tool execution trigger the response repetition breaker."""
    ws = str(tmp_path)

    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        # Emits the exact same explanation repeatedly without any tool calls
        yield "I will create the full portfolio by breaking it into smaller chunks: Part 1 will contain the HTML skeleton and styles."

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="gpt-4o",
        workspace=ws,
        messages=[{"role": "user", "content": "build the portfolio"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)

        # Check that loop was broken early
        error_events = [e for e in events if "event: error" in e or "repeating near-identical responses" in e]
        done_events = [e for e in events if "event: done" in e]
        assert len(error_events) > 0
        assert any("repeating" in e for e in error_events)
        assert any('"success": false' in d or '"success":false' in d for d in done_events)


@pytest.mark.asyncio
async def test_honest_partial_report_on_iteration_cap(tmp_path):
    """Verify that hitting the iteration cap outputs a structured partial report listing completed and skipped items."""
    ws = str(tmp_path)

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        # Emits different read_file tool calls each turn to burn iterations without concluding
        yield f"[TOOL_CALL: read_file]\n{{\"path\": \"file_{turn_count}.txt\"}}\n[/TOOL_CALL]"

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="gpt-4o",
        workspace=ws,
        messages=[{"role": "user", "content": "analyze files in workspace"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness._handle_read_file", MagicMock(return_value=MagicMock(success=True, output="content", error=""))):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)

        # Check for partial_report event and structured done event
        done_events = [e for e in events if "event: done" in e]
        assert len(done_events) > 0
        done_payload = done_events[-1]
        assert "Partial progress report" in done_payload
        assert "Completed Items" in done_payload
        assert "completed_items" in done_payload
        assert "skipped_items" in done_payload
