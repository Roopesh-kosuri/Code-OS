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
