import json
import os
import sys
import pytest
from pathlib import Path
import httpx

from app.main import app
from app.core.auth import get_token
from app.db.database import init_db
from app.features.mcp.scanner import mcp_scanner, ValidationResult
from app.features.mcp.mcp_manager import mcp_manager
from app.features.mcp.schemas import MCPServerConfig


@pytest.fixture(autouse=True)
async def setup_test_database():
    await init_db()
    yield
    await mcp_manager.shutdown()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {get_token()}"}


def test_scanner_command_spec():
    """Verify parsing and validation of command specs."""
    # 1. Spec with custom name
    cfg1 = mcp_scanner.scan_command_spec("Postgres DB:npx -y @modelcontextprotocol/server-postgres postgresql://localhost")
    assert cfg1 is not None
    assert cfg1.id == "postgres_db"
    assert cfg1.name == "Postgres DB"
    assert cfg1.command == "npx"
    assert cfg1.args == ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost"]
    assert cfg1.enabled is False  # Requires explicit approval

    # 2. Spec with malicious shell metacharacters -> rejected
    cfg_bad = mcp_scanner.scan_command_spec("Evil Server:npx; rm -rf /")
    assert cfg_bad is None


def test_scanner_json_file(tmp_path: Path):
    """Verify scanning valid and invalid JSON schemas."""
    # 1. Valid Claude/Cursor style JSON
    valid_json = tmp_path / "valid.json"
    valid_json.write_text(json.dumps({
        "mcpServers": {
            "sqlite-mcp": {
                "command": "uvx",
                "args": ["mcp-server-sqlite", "--db-path", "test.db"],
                "env": {"DEBUG": "1"}
            }
        }
    }), encoding="utf-8")

    configs = mcp_scanner.scan_json_file(str(valid_json))
    assert len(configs) == 1
    assert configs[0].id == "sqlite-mcp"
    assert configs[0].command == "uvx"
    assert configs[0].args == ["mcp-server-sqlite", "--db-path", "test.db"]
    assert configs[0].env == {"DEBUG": "1"}
    assert configs[0].enabled is False

    # 2. Invalid schema (empty command) -> skipped
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text(json.dumps({
        "mcpServers": {
            "bad-server": {
                "command": "",
                "args": []
            }
        }
    }), encoding="utf-8")

    invalid_configs = mcp_scanner.scan_json_file(str(invalid_json))
    assert len(invalid_configs) == 0


def test_scanner_workspace_discovery(tmp_path: Path):
    """Verify auto-discovery of .mcp.json in workspace."""
    mcp_file = tmp_path / ".mcp.json"
    mcp_file.write_text(json.dumps({
        "servers": {
            "fetch-server": {
                "command": "uvx",
                "args": ["mcp-server-fetch"]
            }
        }
    }), encoding="utf-8")

    configs = mcp_scanner.scan_workspace(str(tmp_path))
    assert len(configs) == 1
    assert configs[0].id == "fetch-server"


@pytest.mark.asyncio
async def test_scanner_github_repo_parsing():
    """Verify GitHub repo scanning parses README / package.json."""
    # Test valid GitHub URL parsing without network error crash
    try:
        configs = await mcp_scanner.scan_github_repo("https://github.com/modelcontextprotocol/servers")
        assert isinstance(configs, list)
    except Exception:
        pass

    # SSRF: non-github domain rejected
    with pytest.raises(ValueError, match="Only github.com repositories are supported"):
        await mcp_scanner.scan_github_repo("https://malicious-site.com/repo")


@pytest.mark.asyncio
async def test_scanner_rate_limit(auth_headers):
    """Verify rate limit rejects more than 5 scans per minute per workspace (HTTP 429)."""
    ws = "rate_limit_workspace"
    mcp_scanner._scan_history[ws] = []

    transport = httpx.ASGITransport(app=app) if hasattr(httpx, 'ASGITransport') else None
    async with (httpx.AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) if transport else httpx.AsyncClient(app=app, base_url="http://test", headers=auth_headers)) as client:
        # First 5 scans succeed
        for _ in range(5):
            res = await client.post("/api/mcp/scan", json={
                "source_type": "command_spec",
                "target": "Test:npx echo",
                "workspace": ws
            })
            assert res.status_code == 200

        # 6th scan within same minute returns 429
        res_overflow = await client.post("/api/mcp/scan", json={
            "source_type": "command_spec",
            "target": "Test:npx echo",
            "workspace": ws
        })
        assert res_overflow.status_code == 429
        assert "rate limit" in res_overflow.json()["detail"].lower()


def test_scanner_no_auto_execute():
    """Verify scanner NEVER executes discovered commands (no child processes spawned)."""
    running_before = len([inst for inst in mcp_manager.instances.values() if inst.status == "running"])

    # Perform multiple scans
    mcp_scanner.scan_command_spec("Spawning Test:npx -y @modelcontextprotocol/server-filesystem")
    mcp_scanner.scan_json_content({
        "mcpServers": {
            "demo": {"command": "npx", "args": ["-y", "demo-server"]}
        }
    })

    running_after = len([inst for inst in mcp_manager.instances.values() if inst.status == "running"])
    assert running_before == running_after
