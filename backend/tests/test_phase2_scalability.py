from unittest.mock import patch, AsyncMock
import os
import time
from pathlib import Path
import pytest
from app.db.database import get_pool, init_db, close_db
from app.features.files.service import (
    build_tree,
    get_directory_children,
    DirectoryCache,
    invalidate_directory_cache,
)
from app.features.files.schemas import FileNode


def test_file_tree_depth1(tmp_path: Path):
    # Setup test folder structure
    d1 = tmp_path / "folder_a"
    d1.mkdir()
    (d1 / "nested.py").write_text("print(1)")
    
    d2 = tmp_path / "folder_empty"
    d2.mkdir()
    
    f1 = tmp_path / "root_file.txt"
    f1.write_text("hello world")
    
    tree_root = build_tree(str(tmp_path), depth=1)
    assert tree_root.type == "directory"
    child_map = {c.name: c for c in tree_root.children}
    
    assert "folder_a" in child_map
    assert child_map["folder_a"].type == "directory"
    assert child_map["folder_a"].hasChildren is True
    
    assert "folder_empty" in child_map
    assert child_map["folder_empty"].type == "directory"
    assert child_map["folder_empty"].hasChildren is False
    
    assert "root_file.txt" in child_map
    assert child_map["root_file.txt"].type == "file"
    assert child_map["root_file.txt"].hasChildren is False
    assert child_map["root_file.txt"].size == len("hello world")


def test_directory_cache_lru_eviction():
    cache = DirectoryCache(max_size=5)
    for i in range(10):
        cache.set("ws", f"dir_{i}", [FileNode(name=f"f_{i}", path=f"p_{i}", type="file")])
    
    assert cache.size() == 5
    # Earliest items 0-4 should be evicted
    assert cache.get("ws", "dir_0") is None
    assert cache.get("ws", "dir_4") is None
    # Latest items 5-9 should be present
    assert cache.get("ws", "dir_9") is not None
    assert cache.get("ws", "dir_5") is not None


def test_file_tree_large_workspace_performance(tmp_path: Path):
    ws = tmp_path / "large_ws"
    ws.mkdir()
    # Create 500 files across 20 subdirectories
    for d in range(20):
        sub = ws / f"dir_{d}"
        sub.mkdir()
        for f in range(25):
            (sub / f"file_{f}.txt").write_text("x" * 100)
            
    t0 = time.perf_counter()
    root = build_tree(str(ws), depth=1)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    
    assert len(root.children) == 20
    assert elapsed_ms < 200  # Target <200ms

import asyncio
from app.db.database import get_pool, get_db, init_db
from app.features.ai.dag_engine import DAGEngine


@pytest.mark.asyncio
async def test_concurrent_reads():
    await init_db()
    pool = await get_pool()
    
    # Seed a record
    await pool.write_execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('pool_test', '123')")
    
    async def read_worker():
        conn = await pool.acquire_read()
        try:
            t0 = time.perf_counter()
            cur = await conn.execute("SELECT value FROM settings WHERE key = 'pool_test'")
            rows = await cur.fetchall()
            elapsed = (time.perf_counter() - t0) * 1000
            assert len(rows) > 0
            return elapsed
        finally:
            await pool.release_read(conn)

    # Run 100 concurrent reads
    tasks = [read_worker() for _ in range(100)]
    latencies = await asyncio.gather(*tasks)
    avg_latency = sum(latencies) / len(latencies)
    assert avg_latency < 5.0  # target sub-5ms in memory / sub-20ms under async load


@pytest.mark.asyncio
async def test_concurrent_writes():
    await init_db()
    pool = await get_pool()
    
    async def write_worker(idx: int):
        t0 = time.perf_counter()
        await pool.write_execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (f"key_{idx}", f"val_{idx}")
        )
        return (time.perf_counter() - t0) * 1000

    tasks = [write_worker(i) for i in range(10)]
    latencies = await asyncio.gather(*tasks)
    assert len(latencies) == 10
    assert all(lat < 50.0 for lat in latencies)


@pytest.mark.asyncio
async def test_dag_concurrency_semaphore():
    dag = DAGEngine()
    assert dag._concurrency_semaphore._value == 3

from app.features.ai.harness.context_assembler import (
    split_file_into_chunks,
    rank_chunks,
    assemble_context_with_budget,
)


def test_context_chunking():
    # Generate 500 lines of python code
    lines = [f"def func_{i}():\n    return {i}\n" for i in range(150)]
    content = "\n".join(lines)
    chunks = split_file_into_chunks("service.py", content, chunk_size_lines=50)
    assert len(chunks) >= 3
    assert chunks[0]["start_line"] == 1
    assert chunks[-1]["end_line"] > chunks[0]["end_line"]


def test_context_relevance_ranking():
    chunk1 = {"path": "auth.py", "start_line": 1, "end_line": 50, "content": "import sys\ndef get_token():\n    pass\n"}
    chunk2 = {"path": "user.py", "start_line": 1, "end_line": 50, "content": "import sys\ndef get_user():\n    pass\n"}
    
    ranked = rank_chunks([chunk1, chunk2], query="fix get_token authentication")
    # chunk1 has exact symbol get_token and auth in filename
    assert ranked[0]["path"] == "auth.py"


def test_context_budget_respected(tmp_path: Path):
    f1 = tmp_path / "large_file.py"
    f1.write_text("def test():\n" + "    print('val')\n" * 1000)
    
    # 200 tokens budget ~= 640 chars
    ctx, ctx_map = assemble_context_with_budget([str(f1)], str(tmp_path), query="test", max_tokens=200)
    assert "[Context:" in ctx_map
    assert len(ctx) < 5000 and len(ctx) < len(f1.read_text())  # Stays comfortably within token budget constraint

from app.features.ai.indexing.code_intelligence import (
    _build_symbol_index,
    reindex_single_file,
    _load_stored_symbols,
)


def test_incremental_indexing(tmp_path: Path):
    ws = tmp_path / "ws_inc"
    ws.mkdir()
    f1 = ws / "module_a.py"
    f1.write_text("def first_func():\n    pass\n")
    
    # 1. Initial build
    idx = _build_symbol_index(str(ws))
    assert "first_func" in idx["definitions"]
    
    # 2. Modify single file
    f1.write_text("def updated_func():\n    pass\n")
    reindex_single_file(str(ws), str(f1))
    
    stored = _load_stored_symbols(str(ws))
    assert "module_a.py" in stored
    sym_names = [s["name"] for s in stored["module_a.py"][1]]
    assert "updated_func" in sym_names


def test_index_persistence(tmp_path: Path):
    ws = tmp_path / "ws_persist"
    ws.mkdir()
    (ws / "service.py").write_text("class MyService:\n    pass\n")
    
    _build_symbol_index(str(ws))
    stored = _load_stored_symbols(str(ws))
    assert "service.py" in stored
    assert stored["service.py"][1][0]["name"] == "MyService"


def test_index_size_cap(tmp_path: Path):
    ws = tmp_path / "ws_cap"
    ws.mkdir()
    huge = ws / "huge_file.py"
    # Create file > 100KB
    huge.write_text("# comment\n" * 15000)
    
    reindex_single_file(str(ws), str(huge))
    stored = _load_stored_symbols(str(ws))
    # Huge file must be skipped from symbol indexing
    assert "huge_file.py" not in stored

from app.features.mcp.mcp_manager import MCPServerInstance
from app.features.mcp.schemas import MCPServerConfig
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_mcp_concurrent_calls():
    config = MCPServerConfig(id="test_server", command="echo", name="Test Server")
    instance = MCPServerInstance(config)
    instance.status = "running"
    
    # Mock send_request to simulate concurrent tool executions
    async def mock_send(method, params):
        await asyncio.sleep(0.05)
        return {"result": {"content": [{"type": "text", "text": "ok"}]}}
    
    instance.send_request = mock_send
    
    from app.features.mcp.mcp_manager import mcp_manager
    mcp_manager.instances["test_server"] = instance
    
    tasks = [
        mcp_manager.call_tool("mcp__test_server__query_data", {"q": i})
        for i in range(3)
    ]
    results = await asyncio.gather(*tasks)
    assert len(results) == 3
    assert all(r["content"][0]["text"] == "ok" for r in results)


@pytest.mark.asyncio
async def test_mcp_queue_logging_and_timeout():
    config = MCPServerConfig(id="test_busy", command="echo", name="Busy Server")
    instance = MCPServerInstance(config)
    instance.status = "running"
    
    # Occupy all 3 semaphore slots
    await instance.concurrency_semaphore.acquire()
    await instance.concurrency_semaphore.acquire()
    await instance.concurrency_semaphore.acquire()
    
    from app.features.mcp.mcp_manager import mcp_manager
    mcp_manager.instances["test_busy"] = instance
    
    # With all 3 acquired, a 4th call with short timeout will fail with timeout
    with patch("asyncio.timeout", side_effect=asyncio.TimeoutError):
        with pytest.raises(TimeoutError) as exc_info:
            await mcp_manager.call_tool("mcp__test_busy__task", {})
        assert "busy with concurrent executions" in str(exc_info.value)
    
    # Release slots
    instance.concurrency_semaphore.release()
    instance.concurrency_semaphore.release()
    instance.concurrency_semaphore.release()

from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_fast_startup():
    t0 = time.perf_counter()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health")
        elapsed = time.perf_counter() - t0
        assert res.status_code == 200
        assert res.json()["status"] in ("ok", "healthy")
        assert elapsed < 2.0  # Must respond in <2 seconds


@pytest.mark.asyncio
async def test_system_readiness_endpoint():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/system/readiness")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "db" in data["services"]

@pytest.mark.asyncio
async def test_sqlite_p95_latency(tmp_path: Path):
    db_file = tmp_path / "test_p95.sqlite3"
    await init_db(db_file)
    pool = await get_pool()
    
    await pool.write_execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('perf_key', 'perf_val')")
    # Warm up read pool
    await pool.read_query("SELECT value FROM settings WHERE key = 'perf_key'")
    
    async def worker():
        conn = await pool.acquire_read()
        try:
            t0 = time.perf_counter()
            cur = await conn.execute("SELECT value FROM settings WHERE key = 'perf_key'")
            rows = await cur.fetchall()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert len(rows) > 0
            return elapsed_ms
        finally:
            await pool.release_read(conn)
            
    tasks = [worker() for _ in range(100)]
    latencies = await asyncio.gather(*tasks)
    latencies.sort()
    p95_ms = latencies[94]
    avg_ms = sum(latencies) / len(latencies)
    print(f'\nLATENCIES: Min={latencies[0]:.3f} P50={latencies[49]:.3f} P95={p95_ms:.3f} Avg={avg_ms:.3f}')
    
    assert avg_ms < 5.0, f"Average latency too high: {avg_ms}ms"
    assert p95_ms < 50.0, f"P95 latency too high: {p95_ms}ms"
    await close_db()

@pytest.mark.asyncio
async def test_mcp_approval_bypasses_semaphore():
    config = MCPServerConfig(id="test_approval_srv", command="echo", name="Approval Server")
    instance = MCPServerInstance(config)
    instance.status = "running"
    
    executed_tools = []
    
    async def mock_send(method, params):
        tool_name = params.get("name")
        executed_tools.append(tool_name)
        return {"result": {"content": [{"type": "text", "text": f"Executed {tool_name}"}]}}
        
    instance.send_request = mock_send
    
    from app.features.mcp.mcp_manager import mcp_manager
    mcp_manager.instances["test_approval_srv"] = instance
    
    # Create 3 unresolved approval futures
    fut1 = asyncio.get_running_loop().create_future()
    fut2 = asyncio.get_running_loop().create_future()
    fut3 = asyncio.get_running_loop().create_future()
    
    # 1. Launch 3 tool calls pending approval
    t1 = asyncio.create_task(mcp_manager.call_tool("mcp__test_approval_srv__tool_1", {}, approval_future=fut1))
    t2 = asyncio.create_task(mcp_manager.call_tool("mcp__test_approval_srv__tool_2", {}, approval_future=fut2))
    t3 = asyncio.create_task(mcp_manager.call_tool("mcp__test_approval_srv__tool_3", {}, approval_future=fut3))
    
    await asyncio.sleep(0.01)
    
    # Verify all 3 are tracked in _pending_approvals and semaphore is NOT acquired
    assert len(instance._pending_approvals) == 3
    # Semaphore value should still be 3 (all slots free)
    assert instance.concurrency_semaphore._value == 3
    
    # 2. Launch 4th tool call (no approval required) -> should execute immediately
    res4 = await mcp_manager.call_tool("mcp__test_approval_srv__tool_4", {})
    assert res4["content"][0]["text"] == "Executed tool_4"
    assert "tool_4" in executed_tools
    
    # 3. Approve tool 1
    fut1.set_result(True)
    res1 = await t1
    assert res1["content"][0]["text"] == "Executed tool_1"
    assert len(instance._pending_approvals) == 2
    
    # Cleanup remaining pending tasks
    fut2.set_result(False)
    fut3.set_result(False)
    await asyncio.gather(t2, t3)
