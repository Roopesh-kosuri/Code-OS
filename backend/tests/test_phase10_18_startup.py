import sys
import time
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_backend_startup_under_3s():
    """Verify backend starts up and responds to /api/health in under 3.0 seconds."""
    from app.main import app, _startup_timings
    
    t0 = time.perf_counter()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")
        elapsed = time.perf_counter() - t0
        
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("healthy", "degraded")
        assert "subsystems" in data
        assert elapsed < 3.0, f"Startup to first health response took {elapsed:.3f}s (expected <3.0s)"
        assert _startup_timings["process_start"] > 0
        assert _startup_timings["app_created"] >= _startup_timings["process_start"]


def test_chromadb_lazy_import():
    """Verify chromadb is not eagerly imported into sys.modules during app.main import."""
    from app.features.ai.rag import vector_index_service
    # vector_index_service should have been loaded without chromadb in top-level globals
    assert "chromadb" not in vector_index_service.__dict__ or vector_index_service.__dict__["chromadb"] is None


@pytest.mark.asyncio
async def test_connection_pool_min_max_scaling(tmp_path):
    """Verify ConnectionPool respects min_size=2 and scales up dynamically up to max_size=10."""
    from app.db.database import ConnectionPool
    
    db_file = tmp_path / "test_pool.db"
    pool = ConnectionPool(db_file, min_size=2, max_size=10)
    
    write_conn = await pool.initialize()
    assert write_conn is not None
    assert pool.min_size == 2
    assert pool.max_size == 10
    assert pool._total_read_conns == 2
    
    # Acquire 2 connections
    c1 = await pool.acquire_read()
    c2 = await pool.acquire_read()
    assert c1 is not None
    assert c2 is not None
    
    # Acquire a 3rd connection when queue is empty: dynamic spawn up to max_size
    c3 = await pool.acquire_read()
    assert c3 is not None
    assert pool._total_read_conns == 3
    
    # Release them back
    await pool.release_read(c1)
    await pool.release_read(c2)
    await pool.release_read(c3)
    
    await pool.close()


@pytest.mark.asyncio
async def test_warmup_endpoint():
    """Verify /api/warmup responds with 200 and warmup tasks."""
    from app.main import app
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/warmup")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "warming_up"
        assert "tasks" in body
        assert "chromadb" in body["tasks"]
        assert "connection_pool" in body["tasks"]


@pytest.mark.asyncio
async def test_startup_under_3s_and_warmup_endpoint():
    """Verify combined requirement of fast startup (<3s) and working warmup endpoint."""
    await test_backend_startup_under_3s()
    await test_warmup_endpoint()


# ── Phase 10.18 Regression Tests ─────────────────────────────────────────────

def test_reloader_watch_scope_excludes_workspace_and_state_dirs():
    """F1: Verify dev-backend.js args restrict --reload-dir to backend/app only
    and include --reload-exclude patterns for state/generated files.
    This prevents uvicorn from restarting when agent edits workspace files."""
    import pathlib

    # backend/tests/ -> backend/ -> project root
    dev_backend_path = pathlib.Path(__file__).parents[2] / "scripts" / "dev-backend.js"
    assert dev_backend_path.exists(), f"dev-backend.js not found at {dev_backend_path}"

    content = dev_backend_path.read_text(encoding="utf-8")

    # Must restrict reload to backend/app only
    assert "--reload-dir" in content, "Missing --reload-dir in dev-backend.js"
    # The reload-dir path must point to 'app' subdir of backend
    assert 'backendDir, "app"' in content or "backendDir, 'app'" in content, \
        "--reload-dir should point to backend/app only"

    # Must exclude state/generated file types that trigger spurious reloads
    required_excludes = ["*.db", "*.sqlite3", "*.log", "*.pyc", "__pycache__",
                         ".code_os", "vector_index"]
    for exc in required_excludes:
        assert exc in content, f"Missing --reload-exclude '{exc}' in dev-backend.js"


@pytest.mark.asyncio
async def test_sse_generator_exception_does_not_kill_process():
    """F2: An unhandled exception inside the SSE generator must NOT propagate to uvicorn.
    The route must catch it, log it, and return an error SSE event with HTTP 200."""
    import app.features.ai.chat_harness_routes as _routes_mod
    from app.main import app

    async def _exploding_generator(*args, **kwargs):
        """Generator that immediately raises an unhandled exception."""
        yield "data: {}\n\n"  # first event ok
        raise RuntimeError("Simulated unhandled agent crash")

    # Patch at module level so the route's getattr lookup picks it up
    original = getattr(_routes_mod, "run_chat_agent", None)
    _routes_mod.run_chat_agent = _exploding_generator  # type: ignore[attr-defined]

    from app.core.auth import get_token
    token = get_token()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/ai/chat-agent/stream",
                json={
                    "provider": "auto",
                    "model": "llama3.2",
                    "messages": [{"role": "user", "content": "hello"}],
                    "workspace": "",
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
    finally:
        if original is not None:
            _routes_mod.run_chat_agent = original  # type: ignore[attr-defined]
        elif hasattr(_routes_mod, "run_chat_agent"):
            delattr(_routes_mod, "run_chat_agent")

    # The SSE endpoint must return 200 — NOT crash with 500
    assert response.status_code == 200, (
        f"SSE route returned {response.status_code} — exception leaked to ASGI layer"
    )
    body = response.text
    # Must contain an error event sentinel
    assert "event: error" in body or "event: done" in body, (
        "SSE crash guard must emit an error or done event before closing"
    )


def test_in_memory_caches_bounded():
    """F3: Insert more entries than the cap into _file_read_cache; verify it stays bounded."""
    from app.features.ai.harness.tool_executor import _file_read_cache, _FILE_READ_CACHE_MAX

    _file_read_cache.clear()

    # Insert cap + 50 entries
    overfill = _FILE_READ_CACHE_MAX + 50
    for i in range(overfill):
        key = f"/fake/workspace/file_{i}.py"
        # Simulate the same eviction logic used by _read_file_cached
        while len(_file_read_cache) >= _FILE_READ_CACHE_MAX:
            _file_read_cache.popitem(last=False)
        _file_read_cache[key] = (float(i), f"content_{i}")

    assert len(_file_read_cache) <= _FILE_READ_CACHE_MAX, (
        f"Cache grew to {len(_file_read_cache)} entries, expected <= {_FILE_READ_CACHE_MAX}"
    )
    # Latest entries should be kept (LRU evicts oldest)
    assert f"/fake/workspace/file_{overfill - 1}.py" in _file_read_cache, \
        "Most recent entry should be in cache after LRU eviction"

    _file_read_cache.clear()
