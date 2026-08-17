"""
Integration tests for run_chat_agent in chat_harness.py.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest


@pytest.mark.asyncio
async def test_run_chat_agent_tool_loop_to_done(tmp_path):
    """Simulate a multi-turn tool interaction ending in [DONE]."""
    ws = str(tmp_path)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=ws,
        messages=[{"role": "user", "content": "Inspect app.py and edit it to return 42"}],
    )

    # Mock provider response stream
    # Turn 1: Outputs a plan and tool call to read_file
    turn1_chunks = [
        "[PLAN]\n1. Read app.py\n2. Update run to return 42\n[/PLAN]\n\n",
        "[TOOL_CALL: read_file]\n",
        '{"path": "app.py"}\n',
        "[/TOOL_CALL]",
    ]
    # Turn 2: Outputs edit_file and [DONE]
    turn2_chunks = [
        "Now editing the file:\n",
        "[TOOL_CALL: edit_file]\n",
        '{"path": "app.py", "original": "def run(): pass", "updated": "def run():\\n    return 42\\n"}\n',
        "[/TOOL_CALL]\n\n",
        "All changes complete!\n[DONE]",
    ]

    async def mock_stream_turn1(*args, **kwargs):
        for c in turn1_chunks:
            yield c

    async def mock_stream_turn2(*args, **kwargs):
        for c in turn2_chunks:
            yield c

    mock_provider = MagicMock()
    # Alternate stream responses
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream_turn1(), mock_stream_turn2()])

    from app.features.ai.chat_harness import _pending_approvals, approve_action

    async def auto_approver():
        for _ in range(20):
            await asyncio.sleep(0.05)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    await approve_action(act_id)
                break

    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        with patch("app.features.ai.chat_harness.create_proposal", new=AsyncMock(return_value=MagicMock(id="prop-123"))):
            with patch("app.features.ai.service.apply_proposal", new=AsyncMock(return_value=MagicMock())):
                approver_task = asyncio.create_task(auto_approver())
                events = []
                async for chunk in run_chat_agent(req):
                    events.append(chunk)

                await approver_task
                full_sse_output = "".join(events)
                assert "event: status" in full_sse_output
                assert "event: plan" in full_sse_output
                assert "Read app.py" in full_sse_output
                assert "event: token" in full_sse_output
                assert "event: proposal" in full_sse_output
                assert "event: done" in full_sse_output
                assert '"success": true' in full_sse_output


@pytest.mark.asyncio
async def test_run_chat_agent_rejection_resumes_with_adapted_plan(tmp_path):
    """Simulate user rejecting an edit proposal and agent adapting plan gracefully."""
    from app.features.ai.chat_harness import _pending_approvals, reject_action
    ws = str(tmp_path)
    (tmp_path / "config.py").write_text("DEBUG = True\n", encoding="utf-8")

    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=ws,
        messages=[{"role": "user", "content": "Set DEBUG = False in config.py"}],
    )

    turn1_chunks = [
        "[TOOL_CALL: edit_file]\n",
        '{"path": "config.py", "original": "DEBUG = True", "updated": "DEBUG = False"}\n',
        "[/TOOL_CALL]",
    ]
    turn2_chunks = [
        "Understood. Since you rejected the edit, I will leave config.py unchanged.\n[DONE]",
    ]

    async def mock_stream_turn1(*args, **kwargs):
        for c in turn1_chunks:
            yield c

    async def mock_stream_turn2(*args, **kwargs):
        for c in turn2_chunks:
            yield c

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream_turn1(), mock_stream_turn2()])

    async def auto_rejector():
        for _ in range(20):
            await asyncio.sleep(0.05)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    await reject_action(act_id)
                break

    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        with patch("app.features.ai.chat_harness.create_proposal", new=AsyncMock(return_value=MagicMock(id="prop-reject-1"))):
            with patch("app.features.ai.service.reject_proposal", new=AsyncMock(return_value=MagicMock())):
                rejector_task = asyncio.create_task(auto_rejector())
                events = []
                async for chunk in run_chat_agent(req):
                    events.append(chunk)

                await rejector_task
                full_sse_output = "".join(events)
                assert "event: approval_request" in full_sse_output
                assert "event: command_result" in full_sse_output
                assert "rejected" in full_sse_output.lower()
                assert "event: done" in full_sse_output
