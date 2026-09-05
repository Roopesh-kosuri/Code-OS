from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.middleware import request_id_var
from app.core.logging_config import StructuredFormatter
from app.core.errors import AppError, ErrorCode
from app.core.auth import get_token
from app.features.workspaces.trust_service import set_workspace_trust
from app.db.database import init_db, close_db, get_pool


@pytest.mark.asyncio
async def test_request_id_propagation():
    """Send request with and without X-Request-ID; verify header is echoed or generated."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = get_token()
        # 1. Custom request ID
        res = await client.get("/api/health", headers={"X-Request-ID": "custom-trace-123", "Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.headers.get("X-Request-ID") == "custom-trace-123"

        # 2. Auto-generated request ID
        res_auto = await client.get("/api/health", headers={"Authorization": f"Bearer {token}"})
        assert res_auto.status_code == 200
        assert res_auto.headers.get("X-Request-ID") is not None
        assert len(res_auto.headers.get("X-Request-ID")) >= 8


def test_structured_log_format():
    """Verify StructuredFormatter generates valid JSON with all required FAANG metadata fields."""
    formatter = StructuredFormatter(datefmt="%Y-%m-%dT%H:%M:%S")
    request_id_var.set("trace-abc-999")

    record = logging.LogRecord(
        name="app.features.ai.harness",
        level=logging.INFO,
        pathname="tool_executor.py",
        lineno=42,
        msg="Executing tool %s with args %s",
        args=("write_file", "{'path': 'app.py'}"),
        exc_info=None,
    )

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["level"] == "INFO"
    assert data["logger"] == "app.features.ai.harness"
    assert data["message"] == "Executing tool write_file with args {'path': 'app.py'}"
    assert data["request_id"] == "trace-abc-999"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_check_all_subsystems(tmp_path: Path):
    """Verify /api/health verifies all subsystems and returns valid metrics."""
    db_file = tmp_path / "health_test.sqlite3"
    await init_db(db_file)
    token = get_token()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()

        assert data["status"] in ("healthy", "ok")
        assert data["version"] == "3.1.0"
        assert "uptime_seconds" in data
        assert "subsystems" in data
        assert "database" in data["subsystems"]
        assert data["subsystems"]["database"]["status"] == "ok"
        assert "latency_ms" in data["subsystems"]["database"]
        assert "file_watcher" in data["subsystems"]
        assert "mcp_servers" in data["subsystems"]
        assert "indexer" in data["subsystems"]
        assert "metrics" in data
        assert "memory_mb" in data["metrics"]
        assert "active_tasks" in data["metrics"]
        assert "pending_approvals" in data["metrics"]

    await close_db()


@pytest.mark.asyncio
async def test_health_check_degraded():
    """Verify /api/health reports degraded status when database errors out."""
    token = get_token()

    with patch("app.db.database.get_pool", side_effect=RuntimeError("Database connection lost")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/health", headers={"Authorization": f"Bearer {token}"})
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "degraded"
            assert data["subsystems"]["database"]["status"] == "degraded"
            assert "Database connection lost" in data["subsystems"]["database"]["error"]


@pytest.mark.asyncio
async def test_error_response_format(tmp_path: Path):
    """Verify AppError is handled and formatted with standard error taxonomy."""
    missing_ws = str(tmp_path / "non_existent_subdir_xyz")
    await set_workspace_trust(missing_ws, True)

    transport = ASGITransport(app=app)
    token = get_token()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/files/tree?workspace={missing_ws}", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 404
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == ErrorCode.WORKSPACE_NOT_FOUND.value
        assert "message" in data["error"]


def test_openapi_schema_generation():
    """Verify OpenAPI JSON schema builds successfully with documented response models."""
    schema = app.openapi()
    assert schema["info"]["title"] == "CODE OS Backend"
    assert schema["info"]["version"] == "3.1.0"
    components = schema.get("components", {}).get("schemas", {})
    assert "HealthCheckResponse" in components
    assert "ResumeResponse" in components
    assert "InterruptedTask" in components
    assert "PendingApprovalDto" in components
    assert "TreeResponse" in components
    assert "ReadinessStatus" in components
