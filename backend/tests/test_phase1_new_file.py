import pytest
from pathlib import Path
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import get_token
from app.db.database import init_db
from app.features.workspaces.trust_service import set_workspace_trust


@pytest.fixture(autouse=True)
async def setup_test_database():
    await init_db()
    yield


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {get_token()}"}


@pytest.fixture
def client(auth_headers):
    with TestClient(app) as test_client:
        test_client.headers.update(auth_headers)
        yield test_client


def test_new_file_creates_and_opens(client, tmp_path):
    """Verifies creating a new file on disk, listing it, and reading it."""
    ws = str(tmp_path)
    # Ensure workspace is trusted
    import asyncio
    asyncio.run(set_workspace_trust(ws, True))

    # 1. Create a file inside workspace
    res = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "test_script.py",
        "type": "file"
    })
    assert res.status_code == 200
    assert res.json().get("status") == "created"
    created_file = tmp_path / "test_script.py"
    assert created_file.exists()
    assert created_file.is_file()

    # 2. Read the created file (open file endpoint)
    read_res = client.get(f"/api/files/read?workspace={ws}&path=test_script.py")
    assert read_res.status_code == 200
    data = read_res.json()
    assert data["path"] == "test_script.py"
    assert data["language"] == "python"
    assert data["content"] == ""

    # 3. Create a folder and file inside folder
    res_dir = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "submodule",
        "type": "directory"
    })
    assert res_dir.status_code == 200
    assert (tmp_path / "submodule").is_dir()

    res_subfile = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "submodule/helper.ts",
        "type": "file"
    })
    assert res_subfile.status_code == 200
    assert (tmp_path / "submodule" / "helper.ts").exists()


def test_new_file_rejects_escape(client, tmp_path):
    """Verifies that path traversal escaping the workspace is rejected."""
    ws = str(tmp_path)
    import asyncio
    asyncio.run(set_workspace_trust(ws, True))

    # Escape via ..
    res = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "../../escaped.txt",
        "type": "file"
    })
    assert res.status_code == 403
    assert "outside workspace" in res.json().get("detail", "").lower()

    # Escape with absolute path outside
    res = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "C:\\Windows\\System32\\bad.dll",
        "type": "file"
    })
    assert res.status_code == 403


def test_new_file_blocked_restricted(client, tmp_path):
    """Verifies that file creation is blocked when workspace is in Restricted Mode."""
    ws = str(tmp_path)
    import asyncio
    asyncio.run(set_workspace_trust(ws, False))

    res = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "blocked.txt",
        "type": "file"
    })
    assert res.status_code == 403
    assert "restricted mode" in res.json().get("detail", "").lower()


def test_new_file_validation_and_collision(client, tmp_path):
    """Verifies empty names, invalid characters, and collision errors."""
    ws = str(tmp_path)
    import asyncio
    asyncio.run(set_workspace_trust(ws, True))

    # Empty name
    res = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "   ",
        "type": "file"
    })
    assert res.status_code == 400
    assert "cannot be empty" in res.json().get("detail", "").lower()

    # Invalid characters on Windows
    for bad_char in ["*", "?", "<", ">", "|"]:
        res = client.post("/api/files/create", json={
            "workspace": ws,
            "path": f"bad{bad_char}name.txt",
            "type": "file"
        })
        assert res.status_code == 400
        assert "invalid characters" in res.json().get("detail", "").lower()

    # Collision error (409)
    (tmp_path / "existing.txt").write_text("hello", encoding="utf-8")
    res = client.post("/api/files/create", json={
        "workspace": ws,
        "path": "existing.txt",
        "type": "file"
    })
    assert res.status_code == 409
    assert "already exists" in res.json().get("detail", "").lower()
