import json
import os
import sys
import pytest
from pathlib import Path
import httpx

from app.main import app
from app.core.auth import get_token
from app.db.database import init_db
from app.features.mcp.mcp_manager import mcp_manager
from app.features.mcp.schemas import MCPServerConfig
from app.features.workspaces.trust_service import set_workspace_trust


@pytest.fixture(autouse=True)
async def setup_test_database():
    await init_db()
    yield
    await mcp_manager.shutdown()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {get_token()}"}


MOCK_SERVER_SCRIPT = str(Path(__file__).parent / "mock_mcp_server.py")


@pytest.mark.asyncio
async def test_stdio_environment_isolation_no_leaks(auth_headers):
    """Verify that child MCP stdio processes NEVER inherit sensitive parent environment variables."""
    os.environ["SECRET_HOST_API_KEY"] = "super_secret_leak_attempt_999"

    mock_config = MCPServerConfig(
        id="mock_iso",
        name="Mock Isolation Server",
        type="stdio",
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        env={"USER_ALLOWED_VAR": "my_safe_value"},
        enabled=True
    )

    status = await mcp_manager.register_server(mock_config)
    assert status.status == "running"

    res = await mcp_manager.call_tool("mcp__mock_iso__check_env", {})
    assert res["is_error"] is False
    env_keys = json.loads(res["content"][0]["text"])

    assert "SECRET_HOST_API_KEY" not in env_keys
    assert "USER_ALLOWED_VAR" in env_keys

    await mcp_manager.remove_server("mock_iso")


@pytest.mark.asyncio
async def test_initialize_handshake_and_tool_discovery(auth_headers):
    """Verify MCP standard initialize handshake, protocol negotiation, and tools/list discovery."""
    mock_config = MCPServerConfig(
        id="mock_proto",
        name="Mock Protocol Server",
        type="stdio",
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        enabled=True
    )

    status = await mcp_manager.register_server(mock_config)
    assert status.status == "running"

    instance = mcp_manager.instances["mock_proto"]
    assert instance.protocol_version == "2024-11-05"
    assert len(instance.tools) >= 4

    tool_names = [t.name for t in instance.tools]
    assert "echo_read" in tool_names
    assert "write_data" in tool_names

    echo_tool = next(t for t in instance.tools if t.name == "echo_read")
    assert echo_tool.namespaced_name == "mcp__mock_proto__echo_read"
    assert echo_tool.read_only is True

    write_tool = next(t for t in instance.tools if t.name == "write_data")
    assert write_tool.namespaced_name == "mcp__mock_proto__write_data"
    assert write_tool.read_only is False

    await mcp_manager.remove_server("mock_proto")


@pytest.mark.asyncio
async def test_tools_call_success_error_and_output_cap(auth_headers):
    """Verify tools/call execution, error reporting, and 100KB output capping."""
    mock_config = MCPServerConfig(
        id="mock_exec",
        name="Mock Exec Server",
        type="stdio",
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        enabled=True
    )
    await mcp_manager.register_server(mock_config)

    # 1. Successful tool call
    res_echo = await mcp_manager.call_tool("mcp__mock_exec__echo_read", {"message": "Hello MCP"})
    assert res_echo["is_error"] is False
    assert res_echo["content"][0]["text"] == "Echo: Hello MCP"

    # 2. Output capping: 120KB output truncated to 100KB
    res_large = await mcp_manager.call_tool("mcp__mock_exec__generate_large_output", {})
    assert res_large["is_error"] is False
    large_text = res_large["content"][0]["text"]
    assert "[MCP Output Truncated at 100KB]" in large_text
    assert len(large_text.encode("utf-8")) <= 105 * 1024

    # 3. Non-existent tool returns error
    res_err = await mcp_manager.call_tool("mcp__mock_exec__does_not_exist", {})
    assert res_err["is_error"] is True

    await mcp_manager.remove_server("mock_exec")


@pytest.mark.asyncio
async def test_restricted_mode_blocks_mutating_mcp_tools(tmp_path: Path, auth_headers):
    """Verify Restricted Mode allows read-only MCP tools and blocks mutating tools with HTTP 403."""
    ws = tmp_path / "restricted_ws"
    ws.mkdir()
    await set_workspace_trust(str(ws), False)

    mock_config = MCPServerConfig(
        id="mock_sec",
        name="Mock Security Server",
        type="stdio",
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        enabled=True
    )
    await mcp_manager.register_server(mock_config)

    transport = httpx.ASGITransport(app=app) if hasattr(httpx, 'ASGITransport') else None
    async with (httpx.AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) if transport else httpx.AsyncClient(app=app, base_url="http://test", headers=auth_headers)) as async_client:
        # 1. Read-only tool is allowed in Restricted Mode
        resp_read = await async_client.post("/api/mcp/call", json={
            "tool_name": "mcp__mock_sec__echo_read",
            "arguments": {"message": "safe query"},
            "workspace": str(ws)
        })
        assert resp_read.status_code == 200
        assert "Echo: safe query" in resp_read.json()["content"][0]["text"]

        # 2. Mutating tool is strictly blocked in Restricted Mode (HTTP 403)
        resp_write = await async_client.post("/api/mcp/call", json={
            "tool_name": "mcp__mock_sec__write_data",
            "arguments": {"data": "malicious payload"},
            "workspace": str(ws)
        })
        assert resp_write.status_code == 403
        assert "restricted mode" in resp_write.json()["detail"].lower()

    await mcp_manager.remove_server("mock_sec")


@pytest.mark.asyncio
async def test_server_crash_detection_and_auto_restart_cap(auth_headers):
    """Verify server crash detection and auto-restart cap (max 3 attempts before moving to crashed state)."""
    mock_config = MCPServerConfig(
        id="mock_crash",
        name="Mock Crash Server",
        type="stdio",
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        enabled=True
    )
    await mcp_manager.register_server(mock_config)
    instance = mcp_manager.instances["mock_crash"]

    # Trigger crash multiple times
    instance.restart_count = 3
    await instance._handle_crash()

    assert instance.status == "crashed"
    assert "exceeded 3 auto-restart limit" in (instance.error_message or "")

    # Manual restart resets crash counter
    restart_ok = await instance.restart()
    assert restart_ok is True
    assert instance.status == "running"
    assert instance.restart_count == 0

    await mcp_manager.remove_server("mock_crash")
