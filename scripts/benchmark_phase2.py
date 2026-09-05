import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.features.files.service import build_tree, get_directory_children, directory_cache
from app.db.database import init_db, get_pool, close_db
from app.features.ai.harness.context_assembler import assemble_context_with_budget
from app.main import app
from httpx import ASGITransport, AsyncClient


async def benchmark_virtual_tree():
    print("===================================================================")
    print("BENCHMARK 1: Virtual File Tree (50,000 Files Workspace)")
    print("===================================================================")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir) / "large_repo"
        ws.mkdir()
        
        # Create structure with 50 top-level dirs, each having 1,000 files (50,000 files total)
        print("Creating mock 50,000-file workspace structure...")
        for d in range(50):
            sub = ws / f"package_{d}"
            sub.mkdir()
            for f in range(1000):
                (sub / f"file_{f}.py").write_text("x = 1\n")
        
        directory_cache.clear()
        
        # Measure Initial Root Tree Load (depth=1)
        t0 = time.perf_counter()
        root = build_tree(str(ws), depth=1)
        initial_load_ms = (time.perf_counter() - t0) * 1000
        
        # Measure Folder Expansion (depth=1 on package_0)
        t0 = time.perf_counter()
        child_nodes = get_directory_children(str(ws), "package_0")
        expand_ms = (time.perf_counter() - t0) * 1000
        
        print(f"Top-level directories loaded: {len(root.children)}")
        print(f"Initial Tree Load Time: {initial_load_ms:.2f} ms (Target: <200 ms)")
        print(f"Folder Expand Time:     {expand_ms:.2f} ms (Target: <100 ms)")
        assert initial_load_ms < 200.0, f"Initial load too slow: {initial_load_ms}ms"
        assert expand_ms < 100.0, f"Folder expand too slow: {expand_ms}ms"
        print("[PASS] Virtual Tree benchmark passed within targets.\n")


async def benchmark_sqlite_concurrency():
    print("===================================================================")
    print("BENCHMARK 2: SQLite Connection Pool (100 Concurrent Reads)")
    print("===================================================================")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "bench.db"
        await init_db(db_file)
        pool = await get_pool()
        
        await pool.write_execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('perf_key', 'perf_val')")
        
        async def worker():
            conn = await pool.acquire_read()
            try:
                t0 = time.perf_counter()
                cur = await conn.execute("SELECT value FROM settings WHERE key = 'perf_key'")
                rows = await cur.fetchall()
                elapsed = (time.perf_counter() - t0) * 1000
                assert len(rows) > 0
                return elapsed
            finally:
                await pool.release_read(conn)
        
        t_total_start = time.perf_counter()
        tasks = [worker() for _ in range(100)]
        latencies = await asyncio.gather(*tasks)
        total_time_ms = (time.perf_counter() - t_total_start) * 1000
        avg_latency = sum(latencies) / len(latencies)
        
        print(f"100 Concurrent Reads Executed in: {total_time_ms:.2f} ms")
        print(f"Average Query Latency:            {avg_latency:.3f} ms (Target: <5.0 ms)")
        print(f"P95 Query Latency:                {sorted(latencies)[94]:.3f} ms")
        assert avg_latency < 5.0, f"Query latency too high: {avg_latency}ms"
        print("[PASS] SQLite connection pooling benchmark passed within targets.\n")
        await close_db()


async def benchmark_context_assembly():
    print("===================================================================")
    print("BENCHMARK 3: Smart Context Assembly (Token Budgeting)")
    print("===================================================================")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir) / "context_repo"
        ws.mkdir()
        
        file_paths = []
        for i in range(10):
            fp = ws / f"module_{i}.py"
            fp.write_text(f"# Module {i}\n" + f"def compute_{i}():\n    return {i}\n" * 100)
            file_paths.append(str(fp))
            
        t0 = time.perf_counter()
        ctx, ctx_map = assemble_context_with_budget(
            file_paths,
            str(ws),
            query="fix compute_3 logic in module_3",
            max_tokens=4000
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        
        print(f"Context Assembly Time: {elapsed_ms:.2f} ms")
        print(f"Context Map Header:   {ctx_map[:120]}...")
        print(f"Total Context Chars:  {len(ctx)} chars")
        assert len(ctx) > 0
        print("[PASS] Smart Context Assembly benchmark passed.\n")


async def benchmark_backend_startup():
    print("===================================================================")
    print("BENCHMARK 4: Deferred Backend Startup to /health")
    print("===================================================================")
    
    t0 = time.perf_counter()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health")
        startup_ms = (time.perf_counter() - t0) * 1000
        
        print(f"HTTP Status:          {res.status_code}")
        print(f"Response Payload:     {res.json()}")
        print(f"Startup Response Time:{startup_ms:.2f} ms (Target: <2000 ms)")
        assert res.status_code == 200
        assert startup_ms < 2000.0
        print("[PASS] Deferred Backend Startup benchmark passed within targets.\n")


async def main():
    print("\n>> STARTING CODE OS v3.1.0 PHASE 2 SCALABILITY BENCHMARKS >>\n")
    await benchmark_virtual_tree()
    await benchmark_sqlite_concurrency()
    await benchmark_context_assembly()
    await benchmark_backend_startup()
    print("===================================================================")
    print("[SUCCESS] ALL PHASE 2 BENCHMARKS COMPLETED SUCCESSFULLY [SUCCESS]")
    print("===================================================================")


if __name__ == "__main__":
    asyncio.run(main())
