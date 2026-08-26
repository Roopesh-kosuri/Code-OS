import os
import tempfile
from pathlib import Path
import httpx
import pytest
from fastapi import HTTPException

from app.core import auth
from app.core.paths import ensure_within_workspace, normalize_path
from app.features.terminal.service import _sanitize_env
from app.features.workspaces.trust_service import set_workspace_trust, get_workspace_trust


@pytest.mark.asyncio
async def test_etc_passwd_reading_blocked(temp_db, async_client, trusted_workspace):
    """Verify reading /etc/passwd outside workspace or via tilde traversal is blocked."""
    # 1. Tilde workspace traversal -> 400
    res = await async_client.post(
        "/api/ai/context",
        json={"workspace": "~/etc", "active_path": "/etc/passwd"},
    )
    assert res.status_code == 400

    # 2. Path outside workspace -> active_file is None
    res = await async_client.post(
        "/api/ai/context",
        json={"workspace": trusted_workspace, "active_path": "/etc/passwd"},
    )
    assert res.status_code == 200
    assert res.json().get("active_file") is None


@pytest.mark.asyncio
async def test_ssh_id_rsa_attachment_blocked(temp_db, async_client, trusted_workspace):
    """Verify attached path pointing outside workspace is blocked in context/attachments."""
    ssh_path = str(Path.home() / ".ssh" / "id_rsa")
    res = await async_client.post(
        "/api/ai/context",
        json={
            "workspace": trusted_workspace,
            "active_path": ssh_path,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data.get("active_file") is None


@pytest.mark.asyncio
async def test_api_without_token_returns_401(temp_db, trusted_workspace):
    """Verify API calls without Bearer token return HTTP 401."""
    from httpx import ASGITransport
    from app.main import app
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/files/write", json={"workspace": trusted_workspace, "path": "a.txt", "content": "x"})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_with_wrong_token_returns_401(temp_db, trusted_workspace):
    """Verify API calls with wrong Bearer token return HTTP 401."""
    from httpx import ASGITransport
    from app.main import app
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    bad_headers = {"Authorization": "Bearer invalid-wrong-token-999"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=bad_headers) as client:
        res = await client.post("/api/files/write", json={"workspace": trusted_workspace, "path": "a.txt", "content": "x"})
        assert res.status_code == 401


def test_env_sanitizer_security():
    """Verify env sanitizer removes secrets while keeping PATH, SSH_AGENT_PID, and TERM."""
    raw = {
        "PATH": "/usr/bin:/bin",
        "SSH_AGENT_PID": "5678",
        "TERM": "xterm-256color",
        "AWS_SECRET_ACCESS_KEY": "AKIA1234567890",
        "DATABASE_PASSWORD": "supersecretpassword",
        "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx",
    }
    clean = _sanitize_env(raw)
    assert "PATH" in clean
    assert "SSH_AGENT_PID" in clean
    assert "TERM" in clean
    assert "AWS_SECRET_ACCESS_KEY" not in clean
    assert "DATABASE_PASSWORD" not in clean
    assert "GITHUB_TOKEN" not in clean


def test_tilde_traversal_blocked():
    """Verify normalize_path raises HTTP 400 on tilde traversal (~)."""
    with pytest.raises(Exception) as exc_info:
        normalize_path("~/secret.txt")
    assert "400" in str(exc_info.value)


def test_symlink_escape_blocked(tmp_path):
    """Verify ensure_within_workspace blocks path traversal escaping workspace root."""
    ws_dir = str(tmp_path)
    with pytest.raises(HTTPException):
        ensure_within_workspace(ws_dir, f"{ws_dir}/../../etc/passwd")


@pytest.mark.asyncio
async def test_terminal_session_untrusted_cwd_blocked(temp_db, async_client, untrusted_workspace):
    """Verify creating terminal session in untrusted workspace returns 403."""
    res = await async_client.post(
        "/api/terminal/sessions",
        json={"cwd": untrusted_workspace},
    )
    assert res.status_code == 403
