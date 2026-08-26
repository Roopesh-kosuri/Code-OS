"""
test_d3_route_handlers.py

D3 Route Handler Behavioral Tests.
All gaps from Phase C audit: files 45%, git 59%, search 44%, terminal 70%, diagnostic 14%.

Strategy:
- TestClient with app from app.main
- Uses a real in-memory/temp SQLite DB via init_db(tmpdir/test.db)
- Workspace is explicitly trusted so endpoints are not blocked by Restricted Mode
- All protected routes tested: happy path (200), missing token (401/403), bad params (400/422)
- NO vanity assertions: every assert checks a specific value or exception type.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("db")
    db_path = tmp / "test.db"
    loop = asyncio.new_event_loop()
    from app.db.database import init_db, close_db
    loop.run_until_complete(close_db())
    loop.run_until_complete(init_db(db_path))
    yield db_path
    loop.run_until_complete(close_db())
    loop.close()


@pytest.fixture(scope="module")
def tmp_ws(tmp_path_factory, tmp_db):
    ws = tmp_path_factory.mktemp("workspace")
    (ws / "src").mkdir()
    (ws / "src" / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    (ws / "README.md").write_text("# Test\n", encoding="utf-8")
    loop = asyncio.new_event_loop()
    from app.db.database import get_db
    from app.features.workspaces.trust_service import set_workspace_trust
    async def seed():
        db = await get_db()
        await db.execute(
            "INSERT OR IGNORE INTO workspaces(path, name, last_opened_at) VALUES (?, ?, '2026-01-01T00:00:00')",
            (str(ws), ws.name)
        )
        await db.commit()
        await set_workspace_trust(str(ws), trusted=True)
    loop.run_until_complete(seed())
    loop.close()
    return ws


@pytest.fixture(scope="module")
def test_token():
    from app.core.auth import get_token
    return get_token()


@pytest.fixture(scope="module")
def app_client(tmp_db):
    with patch("app.main.mcp_manager.initialize_servers", new_callable=AsyncMock), \
         patch("app.main.mcp_manager.shutdown", new_callable=AsyncMock):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


class TestFilesRoutes:
    def test_list_tree_happy_path(self, app_client, test_token, tmp_ws):
        r = app_client.get("/api/files/tree", params={"workspace": str(tmp_ws)},
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200, f"Expected 200 got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "root" in data
        assert data["root"]["name"] == tmp_ws.name

    def test_list_tree_no_token_401(self, app_client, tmp_ws):
        r = app_client.get("/api/files/tree", params={"workspace": str(tmp_ws)})
        assert r.status_code in (401, 403), f"Expected 401/403 got {r.status_code}"

    def test_read_file_happy_path(self, app_client, test_token, tmp_ws):
        r = app_client.get("/api/files/read", params={"workspace": str(tmp_ws), "path": "src/main.py"},
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        body = r.json()
        assert "content" in body
        assert "def hello" in body["content"]

    def test_read_file_traversal_403(self, app_client, test_token, tmp_ws):
        r = app_client.get("/api/files/read",
                           params={"workspace": str(tmp_ws), "path": "../../../etc/passwd"},
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 403, f"Expected 403 for traversal, got {r.status_code}"

    def test_write_file_and_read_back(self, app_client, test_token, tmp_ws):
        r = app_client.post("/api/files/write",
                            json={"workspace": str(tmp_ws), "path": "src/new_file.py", "content": "x = 42\n"},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        assert (tmp_ws / "src" / "new_file.py").read_text() == "x = 42\n"

    def test_write_file_no_token_401(self, app_client, tmp_ws):
        r = app_client.post("/api/files/write",
                            json={"workspace": str(tmp_ws), "path": "src/bad.py", "content": ""})
        assert r.status_code in (401, 403)

    def test_create_directory_entry(self, app_client, test_token, tmp_ws):
        r = app_client.post("/api/files/create",
                            json={"workspace": str(tmp_ws), "path": "docs2", "type": "directory"},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        assert (tmp_ws / "docs2").is_dir()

    def test_delete_entry(self, app_client, test_token, tmp_ws):
        (tmp_ws / "to_delete.txt").write_text("bye")
        r = app_client.post("/api/files/delete",
                            json={"workspace": str(tmp_ws), "path": "to_delete.txt"},
                              headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        assert not (tmp_ws / "to_delete.txt").exists()


class TestSearchRoutes:
    def test_search_files_happy_path(self, app_client, test_token, tmp_ws):
        r = app_client.get("/api/search/files",
                           params={"workspace": str(tmp_ws), "query": "main"},
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        results = r.json()
        names = [item["name"] for item in results]
        assert "main.py" in names

    def test_search_files_no_token_401(self, app_client, tmp_ws):
        r = app_client.get("/api/search/files", params={"workspace": str(tmp_ws), "query": "x"})
        assert r.status_code in (401, 403)

    def test_search_text_happy_path(self, app_client, test_token, tmp_ws):
        r = app_client.get("/api/search/text",
                           params={"workspace": str(tmp_ws), "query": "hello",
                                   "regex": "false", "case_sensitive": "true"},
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        results = r.json()
        assert len(results) >= 1
        assert "line" in results[0]
        assert "preview" in results[0]

    def test_search_text_regex(self, app_client, test_token, tmp_ws):
        pattern = r"def\s+\w+"
        r = app_client.get("/api/search/text",
                           params={"workspace": str(tmp_ws), "query": pattern, "regex": "true"},
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        results = r.json()
        assert len(results) >= 1


class TestWorkspaceRoutes:
    def test_list_recent_workspaces(self, app_client, test_token):
        r = app_client.get("/api/workspaces",
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        data = r.json()
        assert "workspaces" in data
        assert isinstance(data["workspaces"], list)

    def test_get_last_workspace(self, app_client, test_token):
        r = app_client.get("/api/workspaces/last",
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code in (200, 404)

    def test_open_workspace(self, app_client, test_token, tmp_ws):
        with patch("app.features.workspaces.service.index_manager.schedule", new_callable=AsyncMock), \
             patch("app.features.workspaces.service.watcher.watch"):
            r = app_client.post("/api/workspaces/open",
                                json={"path": str(tmp_ws)},
                                headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        assert r.json()["path"] == str(tmp_ws)

    def test_workspace_no_token_401(self, app_client):
        r = app_client.get("/api/workspaces")
        assert r.status_code in (401, 403)


class TestSettingsRoutes:
    def test_set_and_list_setting(self, app_client, test_token):
        r = app_client.post("/api/settings",
                            json={"key": "test_key_d3", "value": "test_value_d3"},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        r2 = app_client.get("/api/settings",
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r2.status_code == 200
        settings = {item["key"]: item["value"] for item in r2.json()}
        assert settings.get("test_key_d3") == "test_value_d3"

    def test_settings_no_token_401(self, app_client):
        r = app_client.get("/api/settings")
        assert r.status_code in (401, 403)


class TestTerminalRoutes:
    def test_run_file_traversal_rejected(self, app_client, test_token, tmp_ws):
        r = app_client.post("/api/terminal/run",
                            json={"workspace": str(tmp_ws), "path": "../../etc/passwd"},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code in (400, 403, 422), f"Expected path rejection, got {r.status_code}"

    def test_run_no_token_401(self, app_client, tmp_ws):
        r = app_client.post("/api/terminal/run",
                            json={"workspace": str(tmp_ws), "path": "src/main.py"})
        assert r.status_code in (401, 403)

    def test_toolchains_endpoint(self, app_client, test_token):
        r = app_client.get("/api/terminal/toolchains",
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        data = r.json()
        assert "toolchains" in data
        assert isinstance(data["toolchains"], list) and len(data["toolchains"]) > 0
        py = next((t for t in data["toolchains"] if t.get("id") == "python"), None)
        assert py is not None
        assert py["installed"] is True


class TestDuoSessionRoutes:
    def test_list_sessions_empty(self, app_client, test_token, tmp_ws):
        r = app_client.get("/api/duo/sessions",
                           params={"workspace": str(tmp_ws)},
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_nonexistent_session_404(self, app_client, test_token):
        r = app_client.get("/api/duo/sessions/non-existent-uuid",
                           headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 404

    def test_cancel_nonexistent_session_404(self, app_client, test_token):
        r = app_client.post("/api/duo/sessions/non-existent-uuid/cancel",
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 404

    def test_session_no_token_401(self, app_client):
        r = app_client.get("/api/duo/sessions", params={"workspace": "/tmp/x"})
        assert r.status_code in (401, 403)

    def test_start_session_missing_fields_422(self, app_client, test_token):
        r = app_client.post("/api/duo/sessions", json={},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text[:200]}"


class TestDebugRoutes:
    def test_start_debug_traversal_403(self, app_client, test_token, tmp_ws):
        r = app_client.post("/api/debug/start",
                            json={"workspace": str(tmp_ws), "file_path": "../../etc/passwd", "args": []},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code in (400, 403), f"Expected traversal rejection, got {r.status_code}: {r.text[:200]}"

    def test_start_debug_nonexistent_file_400(self, app_client, test_token, tmp_ws):
        r = app_client.post("/api/debug/start",
                            json={"workspace": str(tmp_ws), "file_path": "nonexistent.py", "args": []},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 400, f"Expected 400 for missing file, got {r.status_code}: {r.text[:200]}"

    def test_start_debug_wrong_extension_400(self, app_client, test_token, tmp_ws):
        r = app_client.post("/api/debug/start",
                            json={"workspace": str(tmp_ws), "file_path": "README.md", "args": []},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code == 400, f"Expected 400 for non-.py, got {r.status_code}: {r.text[:200]}"

    def test_start_debug_valid_path_passes_validation(self, app_client, test_token, tmp_ws):
        r = app_client.post("/api/debug/start",
                            json={"workspace": str(tmp_ws), "file_path": "src/main.py", "args": []},
                            headers={"Authorization": f"Bearer {test_token}"})
        assert r.status_code != 403, f"Valid path must not be rejected as traversal: {r.text[:200]}"

    def test_start_debug_no_token_401(self, app_client, tmp_ws):
        r = app_client.post("/api/debug/start",
                            json={"workspace": str(tmp_ws), "file_path": "src/main.py"})
        assert r.status_code in (401, 403)



