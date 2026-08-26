import subprocess
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from git import Repo

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


@pytest.mark.asyncio
async def test_blame_on_known_commit_returns_correct_author(tmp_path: Path, client: TestClient):
    """Verify git blame returns correct commit hash, author, line numbers, and summary."""
    ws = tmp_path / "git_repo"
    ws.mkdir()

    # Initialize a clean git repo
    repo = Repo.init(ws)
    repo.config_writer().set_value("user", "name", "Test Author").release()
    repo.config_writer().set_value("user", "email", "author@test.com").release()

    sample_file = ws / "main.py"
    sample_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    repo.index.add(["main.py"])
    commit = repo.index.commit("feat: initial commit for blame test")

    await set_workspace_trust(str(ws), True)

    resp = client.get("/api/git/blame", params={
        "workspace": str(ws),
        "file_path": "main.py",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["git"] is True
    lines = data["lines"]
    assert len(lines) == 2

    line1 = lines[0]
    assert line1["line"] == 1
    assert line1["author"] == "Test Author"
    assert line1["summary"] == "feat: initial commit for blame test"
    assert line1["commit"] == commit.hexsha


@pytest.mark.asyncio
async def test_blame_non_git_workspace_no_crash(tmp_path: Path, client: TestClient):
    """Verify non-git workspaces return git: false without crashing or raising 500."""
    ws = tmp_path / "regular_folder"
    ws.mkdir()

    test_file = ws / "script.js"
    test_file.write_text("console.log('no git');", encoding="utf-8")

    await set_workspace_trust(str(ws), True)

    resp = client.get("/api/git/blame", params={
        "workspace": str(ws),
        "file_path": "script.js",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["git"] is False
    assert data["lines"] == []


@pytest.mark.asyncio
async def test_blame_path_escape_rejected(tmp_path: Path, client: TestClient):
    """Verify path traversal / escape is strictly rejected with HTTP 400."""
    ws = tmp_path / "safe_ws"
    ws.mkdir()
    (ws / "dummy.txt").write_text("dummy", encoding="utf-8")

    await set_workspace_trust(str(ws), True)

    # Relative path escape attempt
    resp = client.get("/api/git/blame", params={
        "workspace": str(ws),
        "file_path": "../../outside_secret.txt",
    })
    assert resp.status_code == 400
    assert "path escape" in resp.json()["detail"].lower()
