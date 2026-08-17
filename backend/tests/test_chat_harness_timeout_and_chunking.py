import pytest
import asyncio
import re
from unittest.mock import AsyncMock, patch, MagicMock
from collections.abc import AsyncIterator

from app.features.ai.chat_harness import (
    _is_response_truncated,
    _declares_tool_intent,
    _extract_heuristic_tool_calls,
    _handle_append_file,
    _finalize_staged_changes,
    run_chat_agent,
    ChatAgentRequest,
)
from app.features.ai.schemas import FileChange, EditProposalRequest
from app.features.ai.providers.openai_compatible import OpenAICompatibleProvider


def test_is_response_truncated_markers():
    """Verify truncation detection on length, unclosed tool calls, and timeout errors."""
    assert _is_response_truncated("Some text\n[TRUNCATED: length]\n") is True
    assert _is_response_truncated("Some text\n[TRUNCATED: timeout]\n") is True
    assert _is_response_truncated("Generating file...\n[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\"") is True
    assert _is_response_truncated("Generating file...\n[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\"}\n[/TOOL_CALL]") is False
    assert _is_response_truncated("[Error: openai-compatible provider request timed out. Please check your connection and try again.]") is True
    assert _is_response_truncated("[Error: Network timeout / connection error with openai-compatible: read timeout]") is True
    assert _is_response_truncated("Here is the completed code. [DONE]") is False


def test_declares_tool_intent_extensions():
    """Verify expanded intent phrases for file creation and generation."""
    assert _declares_tool_intent("I will create hello.html with a complete 1000 line portfolio.") is True
    assert _declares_tool_intent("Let's build the portfolio in hello.html now.") is True
    assert _declares_tool_intent("We'll output edit_file for hello.html.") is True
    assert _declares_tool_intent("I will generate the portfolio website.") is True
    assert _declares_tool_intent("The test passed with code 0.") is False
    assert _declares_tool_intent("Here is the explanation. [DONE]") is False


def test_extract_heuristic_tool_calls_edit_file():
    """Verify heuristic extraction of code blocks into edit_file tool calls."""
    response = "I will create hello.html for you:\n```html\n<!DOCTYPE html>\n<html>\n<head><title>Portfolio</title></head>\n<body><h1>Hello</h1></body>\n</html>\n```"
    calls = _extract_heuristic_tool_calls(response, "create hello.html 1000+ line portfolio")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "hello.html"
    assert "<title>Portfolio</title>" in calls[0].arguments["updated"]


def test_append_file_staging_and_consolidation(tmp_path):
    """Verify chunked append_file staging merges into ONE consolidated FileChange."""
    workspace = str(tmp_path)
    staged_changes: list[FileChange] = []

    # Chunk 1: edit_file (create new file)
    c1 = FileChange(path="hello.html", original="", updated="<!DOCTYPE html>\n<html>\n<head><style>body { color: red; }</style></head>\n")
    staged_changes.append(c1)

    # Chunk 2: append_file (body section)
    valid2, err2, change2 = _handle_append_file(
        workspace,
        {"path": "hello.html", "content": "<body>\n<header><h1>My Portfolio</h1></header>\n"},
        staged_changes,
    )
    assert valid2 is True
    assert len(staged_changes) == 1
    assert "<style>" in staged_changes[0].updated
    assert "<header>" in staged_changes[0].updated

    # Chunk 3: append_file (scripts and closing tags)
    valid3, err3, change3 = _handle_append_file(
        workspace,
        {"path": "hello.html", "content": "<script>console.log('ready');</script>\n</body>\n</html>\n"},
        staged_changes,
    )
    assert valid3 is True
    assert len(staged_changes) == 1
    assert "console.log" in staged_changes[0].updated
    assert staged_changes[0].updated.endswith("</html>\n")


@pytest.mark.asyncio
async def test_honest_completion_when_nothing_generated(tmp_path):
    """Verify that a run ending with 0 tools executed on a creation request fails honestly with an error card."""
    workspace = str(tmp_path)

    # Mock provider returning pure conversational text without executing any tools
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "I understand you want a 1000+ line hello.html portfolio. It will have sections for About, Projects, and Contact."
    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="gpt-4o",
        workspace=workspace,
        messages=[{"role": "user", "content": "create hello.html, 1000+ line portfolio"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)
        
        # Check that we received an error event and done=False
        error_events = [e for e in events if "event: error" in e or "Nothing was generated" in e]
        done_events = [e for e in events if "event: done" in e]
        
        assert len(error_events) > 0
        assert any("Nothing was generated" in e for e in error_events)
        assert any('"success": false' in d or '"success":false' in d for d in done_events)


@pytest.mark.asyncio
async def test_truncation_recovery_chunked_success(tmp_path):
    """Verify that on truncation / timeout, the agent is prompted to chunk and succeeds across turns."""
    workspace = str(tmp_path)

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            # Turn 1: Truncated response mid-tool-call
            yield "I will generate hello.html:\n[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"original\": \"\", \"updated\": \"<!DOCTYPE html><html>"
            yield "\n[TRUNCATED: length]\n"
        elif turn_count == 2:
            # Turn 2: Follows chunking prompt -> emits Part 1
            yield "Here is Part 1 with styles:\n[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"original\": \"\", \"updated\": \"<!DOCTYPE html>\\n<html>\\n<head><title>Portfolio</title></head>\\n\"}\n[/TOOL_CALL]\n"
        elif turn_count == 3:
            # Turn 3: Emits Part 2
            yield "Here is Part 2 with body:\n[TOOL_CALL: append_file]\n{\"path\": \"hello.html\", \"content\": \"<body>\\n<section>Hero</section>\\n\"}\n[/TOOL_CALL]\n"
        else:
            # Turn 4: Finalizes and finishes
            yield "Here is Part 3 with closing tags:\n[TOOL_CALL: append_file]\n{\"path\": \"hello.html\", \"content\": \"</body>\\n</html>\\n\"}\n[/TOOL_CALL]\nAll done! [DONE]"

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="gpt-4o",
        workspace=workspace,
        messages=[{"role": "user", "content": "create hello.html, 1000+ line portfolio"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.create_proposal", AsyncMock(return_value=MagicMock(id="prop-123"))), \
         patch("app.features.ai.service.apply_proposal", AsyncMock()):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)
            # Auto-approve if approval requested during test
            if "approval_request" in event:
                match = re.search(r'"action_id":\s*"([^"]+)"', event)
                if match:
                    from app.features.ai.chat_harness import approve_action
                    await approve_action(match.group(1))
        
        # Verify status updates showed chunking instruction
        status_events = [e for e in events if "event: status" in e or "Response was cut off" in e]
        assert any("Response was cut off or timed out" in s for s in status_events)

        # Verify proposal was created
        proposal_events = [e for e in events if "event: proposal" in e or "prop-123" in e]
        assert len(proposal_events) > 0
