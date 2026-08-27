import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from httpx import ASGITransport
import pytest
import pytest_asyncio

from app.core import auth
from app.db.database import get_db, init_db
from app.main import app
from app.features.workspaces.trust_service import set_workspace_trust


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def auth_token():
    token = "test-session-token-1234567890abcdef"
    auth._SESSION_TOKEN = token
    return token


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def temp_db():
    """Create a clean temporary database with WAL mode and foreign keys for tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    from app.db import database
    if database._db is not None:
        try:
            await database._db.close()
        except Exception:
            pass
        database._db = None

    try:
        await init_db(db_path)
        yield db_path
    finally:
        if database._db is not None:
            try:
                await database._db.close()
            except Exception:
                pass
            database._db = None
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


@pytest_asyncio.fixture
async def async_client(auth_headers):
    """Async HTTP test client bound to FastAPI app with valid auth headers."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        yield client



@pytest_asyncio.fixture
async def trusted_workspace(tmp_path):
    ws_dir = str(tmp_path / "trusted_ws")
    os.makedirs(ws_dir, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)
    return ws_dir


@pytest_asyncio.fixture
async def untrusted_workspace(tmp_path):
    ws_dir = str(tmp_path / "untrusted_ws")
    os.makedirs(ws_dir, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=False)
    return ws_dir

@pytest_asyncio.fixture
async def ws_with_db(tmp_path, temp_db):
    ws = tmp_path / "test_workspace"
    ws.mkdir(exist_ok=True)
    (ws / "src").mkdir(exist_ok=True)
    (ws / "src" / "main.py").write_text("print('hello world')\n", encoding="utf-8")
    
    from app.db.database import get_db
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO workspaces(path, name, last_opened_at) VALUES (?, ?, '2026-01-01T00:00:00')",
        (str(ws), ws.name)
    )
    await db.commit()
    return ws
