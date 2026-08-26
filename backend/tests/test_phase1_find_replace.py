import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import get_token
from app.db.database import init_db
from app.features.workspaces.trust_service import set_workspace_trust
from app.features.search.service import is_binary_file


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
async def test_multifile_replace_works(tmp_path: Path, client: TestClient):
    """Verify replace works across multiple text files in a workspace."""
    ws = tmp_path / "replace_ws"
    ws.mkdir()
    
    file1 = ws / "file1.txt"
    file1.write_text("Hello World! Welcome to World.", encoding="utf-8")
    
    file2 = ws / "file2.py"
    file2.write_text("msg = 'Hello World'\nprint(msg)", encoding="utf-8")

    # Mark workspace as trusted
    await set_workspace_trust(str(ws), True)

    # 1. Preview replace
    resp_preview = client.post("/api/search/replace", json={
        "workspace": str(ws),
        "query": "World",
        "replacement": "Universe",
        "apply": False,
    })
    assert resp_preview.status_code == 200
    data = resp_preview.json()
    assert len(data) == 2
    # Verify file1 still has original content
    assert "World" in file1.read_text(encoding="utf-8")

    # 2. Apply replace
    resp_apply = client.post("/api/search/replace", json={
        "workspace": str(ws),
        "query": "World",
        "replacement": "Universe",
        "apply": True,
    })
    assert resp_apply.status_code == 200
    assert file1.read_text(encoding="utf-8") == "Hello Universe! Welcome to Universe."
    assert "Universe" in file2.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_regex_timeout_and_backtracking_rejected(tmp_path: Path, client: TestClient):
    """Verify regexes with nested quantifiers (ReDoS) or timeouts are rejected with HTTP 400."""
    ws = tmp_path / "regex_ws"
    ws.mkdir()
    (ws / "test.txt").write_text("a" * 50, encoding="utf-8")
    await set_workspace_trust(str(ws), True)

    # 1. Static catastrophic backtracking pattern rejection
    resp_evil = client.post("/api/search/replace", json={
        "workspace": str(ws),
        "query": r"(a+)+$",
        "replacement": "b",
        "apply": False,
        "regex": True,
    })
    assert resp_evil.status_code == 400
    assert "backtracking" in resp_evil.json()["detail"].lower()

    # 2. Search endpoint also rejects evil pattern
    resp_search = client.get("/api/search/text", params={
        "workspace": str(ws),
        "query": r"(x+)+$",
        "regex": "true",
    })
    assert resp_search.status_code == 400
    assert "backtracking" in resp_search.json()["detail"].lower()


@pytest.mark.asyncio
async def test_restricted_mode_blocks_replace(tmp_path: Path, client: TestClient):
    """Verify replace with apply=True is strictly blocked in Restricted Mode (HTTP 403)."""
    ws = tmp_path / "restricted_ws"
    ws.mkdir()
    test_file = ws / "secret.txt"
    test_file.write_text("sensitive info", encoding="utf-8")

    # Explicitly mark workspace as untrusted
    await set_workspace_trust(str(ws), False)

    # Attempt to apply replacement in untrusted workspace
    resp = client.post("/api/search/replace", json={
        "workspace": str(ws),
        "query": "sensitive",
        "replacement": "corrupted",
        "apply": True,
    })
    assert resp.status_code == 403
    assert "restricted mode" in resp.json()["detail"].lower()
    # Ensure file content was never modified
    assert test_file.read_text(encoding="utf-8") == "sensitive info"


@pytest.mark.asyncio
async def test_binary_files_untouched(tmp_path: Path, client: TestClient):
    """Verify binary files and ignored directories are untouched during find & replace."""
    ws = tmp_path / "binary_ws"
    ws.mkdir()

    # Binary file with null bytes containing search string in between
    bin_file = ws / "image.png"
    bin_content = b"\x89PNG\r\n\x1a\n\x00World\x00\xff\xfe"
    bin_file.write_bytes(bin_content)

    # Text file
    txt_file = ws / "normal.txt"
    txt_file.write_text("Hello World", encoding="utf-8")

    # Ignored directory file
    nm_dir = ws / "node_modules" / "pkg"
    nm_dir.mkdir(parents=True)
    (nm_dir / "index.js").write_text("const World = 1;", encoding="utf-8")

    assert is_binary_file(bin_file) is True

    # Mark workspace as trusted
    await set_workspace_trust(str(ws), True)

    resp = client.post("/api/search/replace", json={
        "workspace": str(ws),
        "query": "World",
        "replacement": "Earth",
        "apply": True,
    })
    assert resp.status_code == 200

    # Binary file MUST be completely untouched
    assert bin_file.read_bytes() == bin_content
    # Node modules MUST be completely untouched
    assert (nm_dir / "index.js").read_text(encoding="utf-8") == "const World = 1;"
    # Normal text file replaced
    assert txt_file.read_text(encoding="utf-8") == "Hello Earth"
