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

    try:
        await init_db(db_path)
        yield db_path
    finally:
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
