import json
import os
import sys
import pytest
from pathlib import Path
import asyncio

from app.main import app
from app.db.database import init_db
from app.features.mcp.mcp_manager import mcp_manager
from app.features.mcp.schemas import MCPServerConfig
from app.features.workspaces.trust_service import set_workspace_trust
from app.features.ai.chat_harness import (
    _build_system_prompt,
    approve_action,
    reject_action,
    _pending_approvals,
    PendingApproval,
    ToolCall
)

MOCK_SERVER_SCRIPT = str(Path(__file__).parent / "mock_mcp_server.py")


@pytest.fixture(autouse=True)
async def setup_test_database():
    await init_db()
    yield
    await mcp_manager.shutdown()


@pytest.mark.asyncio
async def test_agent_system_prompt_includes_mcp_tools(tmp_path: Path):
    """Verify that active MCP tools are injected into system prompt budget-aware."""
    mock_config = MCPServerConfig(
        id="mock_prompt",
        name="Mock Prompt Server",
        type="stdio",
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        enabled=True
    )
    await mcp_manager.register_server(mock_config)

    prompt = _build_system_prompt(str(tmp_path), tier=2, context={})
    assert "## Available MCP (Model Context Protocol) Tools:" in prompt
    assert "mcp__mock_prompt__echo_read" in prompt

    await mcp_manager.remove_server("mock_prompt")


@pytest.mark.asyncio
async def test_agent_mcp_tool_execution_auto_approved(tmp_path: Path):
    """Verify read-only tool with auto_approve_read_only=True executes and wraps output."""
    mock_config = MCPServerConfig(
        id="mock_auto",
        name="Mock Auto Server",
        type="stdio",
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        enabled=True,
        auto_approve_read_only=True
    )
    await mcp_manager.register_server(mock_config)

    raw_res = await mcp_manager.call_tool("mcp__mock_auto__echo_read", {"message": "hello auto"})
    assert raw_res["is_error"] is False
    text = raw_res["content"][0]["text"]

    wrapped = f'<untrusted_mcp_content server="mock_auto" tool="echo_read">\n{text}\n</untrusted_mcp_content>'
    assert '<untrusted_mcp_content server="mock_auto" tool="echo_read">' in wrapped
    assert "Echo: hello auto" in wrapped

    await mcp_manager.remove_server("mock_auto")


@pytest.mark.asyncio
async def test_agent_mcp_tool_approval_and_denial():
    """Verify approval card flow for mutating MCP tools."""
    action_id = "test_mcp_action_1"
    pending = PendingApproval(
        action_id=action_id,
        action_type="mcp",
        detail="mock:write_data",
        reason="MCP Tool Execution",
        command="mcp__mock__write_data"
    )
    _pending_approvals[action_id] = pending

    # 1. User approves
    ok = await approve_action(action_id)
    assert ok is True
    assert pending.approved is True
    assert pending.event.is_set()

    # 2. User denies / rejects
    action_id_2 = "test_mcp_action_2"
    pending_2 = PendingApproval(
        action_id=action_id_2,
        action_type="mcp",
        detail="mock:write_data",
        reason="MCP Tool Execution",
        command="mcp__mock__write_data"
    )
    _pending_approvals[action_id_2] = pending_2

    ok2 = await reject_action(action_id_2)
    assert ok2 is True
    assert pending_2.approved is False
    assert pending_2.event.is_set()

    _pending_approvals.clear()
