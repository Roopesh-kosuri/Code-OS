"""
test_command_failure_reasons_and_recovery.py
Unit & integration tests for:
- Structured failure reasons (approval_timeout, execution_timeout, governor_kill, exit_code, not_found)
- Approval-timeout re-issue (single re-issue with status reminder before final failure)
- Zero-tool retry question interceptor & auto-recovery (never ask 'Would you like me to try again?')
- Path quoting & implicit parent directory creation
- Full end-to-end task reproduction and verification
"""
import asyncio
import json
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.agents.agent_tools import ToolResult
from app.features.ai.sandbox.executor import _execute_command_async
from app.features.ai.chat_harness import (
    run_chat_agent,
    ChatAgentRequest,
    _is_command_safe,
    _validate_smart_edit,
    COMMAND_APPROVAL_TIMEOUT_SECONDS,
)
from app.features.ai.service import apply_proposal, create_proposal
from app.features.ai.schemas import ChatMessage, EditProposalRequest, FileChange


@pytest.mark.asyncio
async def test_structured_failure_reason_not_found(tmp_path):
    """Verify that a nonexistent command returns structured not_found failure reason."""
    result = await _execute_command_async(str(tmp_path), "nonexistent_custom_binary_123456xyz")
    assert not result.success
    assert result.failure_reason == "not_found"
    assert "not_found" in result.error
    data = json.loads(result.error)
    assert data["reason"] == "not_found"
    assert "nonexistent_custom_binary_123456xyz" in data["command"]


@pytest.mark.asyncio
async def test_structured_failure_reason_exit_code(tmp_path):
    """Verify that a failing command returns structured exit_code failure reason."""
    cmd = "python -c \"import sys; sys.exit(42)\""
    result = await _execute_command_async(str(tmp_path), cmd)
    assert not result.success
    assert result.failure_reason == "exit_code"
    data = json.loads(result.error)
    assert data["reason"] == "exit_code"
    assert data["exit_code"] != 0


@pytest.mark.asyncio
async def test_structured_failure_reason_execution_timeout(tmp_path):
    """Verify that a timed-out command returns structured execution_timeout failure reason."""
    cmd = "python -c \"import time; time.sleep(10)\""
    result = await _execute_command_async(str(tmp_path), cmd, timeout=0.5)
    assert not result.success
    assert result.failure_reason == "execution_timeout"
    assert "Command ran 0s and was killed." in result.failure_detail or "Command ran" in result.failure_detail
    data = json.loads(result.error)
    assert data["reason"] == "execution_timeout"


@pytest.mark.asyncio
async def test_parent_directory_creation_via_edit_file(tmp_path):
    """Verify that edit_file with subfolder automatically creates parent directory on disk."""
    workspace = str(tmp_path)
    rel_path = "nigropo puzzle game/NigropoPuzzleGame.java"
    java_code = """public class NigropoPuzzleGame {
    public static void main(String[] args) {
        System.out.println("Nigropo Puzzle Game Started!");
    }
}
"""
    # 1. Validate edit
    valid, err, change = _validate_smart_edit(workspace, {
        "path": rel_path,
        "original": "",
        "updated": java_code,
    })
    assert valid, f"Edit validation failed: {err}"
    assert change is not None

    # 2. Create proposal and apply
    prop = await create_proposal(EditProposalRequest(
        workspace=workspace,
        summary="Create folder and Java game file",
        changes=[FileChange(path=change.path, original=change.original, updated=change.updated)],
    ))
    applied = await apply_proposal(prop.id)
    assert applied.status == "applied"

    # 3. Verify on disk
    target_file = tmp_path / "nigropo puzzle game" / "NigropoPuzzleGame.java"
    assert target_file.is_file(), "Target Java file was not created"
    assert (tmp_path / "nigropo puzzle game").is_dir(), "Parent directory was not created"
    assert "NigropoPuzzleGame" in target_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_approval_timeout_reissue_and_structured_error(tmp_path):
    """Verify that approval timeout re-issues approval once, then reports structured approval_timeout."""
    workspace = str(tmp_path)
    cmd = "mkdir \"nigropo puzzle game\""

    req = ChatAgentRequest(
        workspace=workspace,
        messages=[{"role": "user", "content": "create folder 'nigropo puzzle game'"}],
        provider="ollama",
        model="qwen2.5-coder:7b",
    )

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            yield f"[TOOL_CALL: run_command]{{\"command\": \"{cmd}\"}}[/TOOL_CALL]"
        else:
            yield "The command approval timed out.\n✓ change verified on disk\n[DONE]"

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.COMMAND_APPROVAL_TIMEOUT_SECONDS", 0.05):

        events = []
        async for sse_event in run_chat_agent(req):
            events.append(sse_event)

        event_str = "".join(events)
        # Verify re-issue status was emitted
        assert "Waiting on your approval" in event_str
        # Verify specific approval_timeout reason was emitted in command_result or tool_error
        assert "approval_timeout" in event_str
        assert "Approval card timed out" in event_str


@pytest.mark.asyncio
async def test_zero_tool_retry_question_interceptor(tmp_path):
    """Verify that asking 'Would you like me to try again?' with 0 tool calls triggers auto-recovery."""
    workspace = str(tmp_path)

    req = ChatAgentRequest(
        workspace=workspace,
        messages=[{"role": "user", "content": "create puzzle game"}],
        provider="ollama",
        model="qwen2.5-coder:7b",
    )

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            yield "I encountered an issue creating the folder. Would you like me to try again?"
        else:
            yield "[TOOL_CALL: edit_file]{\"path\": \"nigropo puzzle game/NigropoPuzzleGame.java\", \"original\": \"\", \"updated\": \"public class NigropoPuzzleGame {}\"}[/TOOL_CALL]\n✓ change verified on disk\n[DONE]"

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.EDIT_APPROVAL_TIMEOUT_SECONDS", 0.05):
        events = []
        async for sse_event in run_chat_agent(req):
            events.append(sse_event)

        event_str = "".join(events)
        assert "Instructing agent to" in event_str
        assert turn_count >= 2


@pytest.mark.asyncio
async def test_full_task_nigropo_puzzle_game_execution(tmp_path):
    """Full task test: create folder 'nigropo puzzle game' + Java game inside it."""
    workspace = str(tmp_path)
    cmd = "mkdir \"nigropo puzzle game\""
    java_file = "nigropo puzzle game/NigropoPuzzleGame.java"

    req = ChatAgentRequest(
        workspace=workspace,
        messages=[{"role": "user", "content": "create folder 'nigropo puzzle game' + Java game inside it"}],
        provider="ollama",
        model="qwen2.5-coder:7b",
    )

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            # First turn: creates Java game file with parent directory directly
            yield (
                f"[TOOL_CALL: edit_file]{{\"path\": \"{java_file}\", \"original\": \"\", \"updated\": \"public class NigropoPuzzleGame {{\\n    public static void main(String[] args) {{\\n        System.out.println(\\\"Puzzle Started\\\");\\n    }}\\n}}\"}}[/TOOL_CALL]\n"
                "✓ change verified on disk\n[DONE]"
            )

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.EDIT_APPROVAL_TIMEOUT_SECONDS", 0.05):
        events = []
        async for sse_event in run_chat_agent(req):
            events.append(sse_event)

        event_str = "".join(events)
        assert "nigropo puzzle game" in event_str
        # Verify no "try again?" question occurred
        assert "Would you like me to try again?" not in event_str


@pytest.mark.asyncio
async def test_give_up_statement_interceptor_and_auto_recovery(tmp_path):
    """Verify that when an agent attempts to give up on folder creation, the harness intercepts and directs file creation."""
    workspace = str(tmp_path)
    java_file = "nigropo puzzle game/NigropoPuzzleGame.java"

    req = ChatAgentRequest(
        workspace=workspace,
        messages=[{"role": "user", "content": "create folder 'nigropo puzzle game' + Java game inside it"}],
        provider="ollama",
        model="qwen2.5-coder:7b",
    )

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            # Turn 1: model tries mkdir which times out
            yield "[TOOL_CALL: run_command]{\"command\": \"mkdir \\\"nigropo puzzle game\\\"\"}[/TOOL_CALL]"
        elif turn_count == 2:
            # Turn 2: model attempts to give up with zero tool calls
            yield "I am unable to create the folder for the \"nigropo puzzle game\". I have tried multiple times to create directories with different names, but each attempt has resulted in an 'Execution error'. This indicates a problem with the environment that prevents me from creating new folders. Therefore, I cannot proceed with creating the game files as requested."
        else:
            # Turn 3: after directive injection, model recovers and stages the file directly
            yield (
                f"[TOOL_CALL: edit_file]{{\"path\": \"{java_file}\", \"original\": \"\", \"updated\": \"public class NigropoPuzzleGame {{}}\"}}[/TOOL_CALL]\n"
                "✓ change verified on disk\n[DONE]"
            )

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.COMMAND_APPROVAL_TIMEOUT_SECONDS", 0.05), \
         patch("app.features.ai.chat_harness.EDIT_APPROVAL_TIMEOUT_SECONDS", 0.05):
        events = []
        async for sse_event in run_chat_agent(req):
            events.append(sse_event)

        event_str = "".join(events)
        assert "Instructing agent to bypass directory creation and execute tools directly" in event_str or "Instructing agent to bypass directory creation" in event_str
        assert turn_count == 3


@pytest.mark.asyncio
async def test_permission_and_environmental_question_interceptor(tmp_path):
    """Verify that asking permission or asking user to diagnose environment is intercepted and redirected."""
    workspace = str(tmp_path)
    java_file = "nigropo_game/NigropoGame.java"

    req = ChatAgentRequest(
        workspace=workspace,
        messages=[{"role": "user", "content": "create puzzle game in nigropo_game"}],
        provider="ollama",
        model="qwen2.5-coder:7b",
    )

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            # Turn 1: model asks permission and diagnostic questions with zero tool calls
            yield (
                "Could you please confirm if there are any specific restrictions on directory creation in your environment, "
                "or if you have sufficient permissions to create folders? In the meantime, I can try to list the current directory contents. Would you like me to do that?"
            )
        else:
            # Turn 2: after directive injection, model recovers and stages the file directly
            yield (
                f"[TOOL_CALL: edit_file]{{\"path\": \"{java_file}\", \"original\": \"\", \"updated\": \"public class NigropoGame {{}}\"}}[/TOOL_CALL]\n"
                "✓ change verified on disk\n[DONE]"
            )

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.EDIT_APPROVAL_TIMEOUT_SECONDS", 0.05):
        events = []
        async for sse_event in run_chat_agent(req):
            events.append(sse_event)

        event_str = "".join(events)
        assert "Instructing agent to bypass directory creation and execute tools directly" in event_str or "Instructing agent to" in event_str
        assert turn_count == 2


async def _mock_stream(text: str):
    yield text
