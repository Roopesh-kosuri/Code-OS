import asyncio
import os
import sys
import time
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

import psutil
from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import create_job, create_task
from app.features.ai.step_tracker import log_step_pending, mark_step_completed, mark_step_running


async def soak_test(duration_seconds: float = 7200.0, interval_seconds: float = 30.0):
    """Run a 2-hour soak test with continuous task creation and memory monitoring."""
    db_path = backend_dir / "soak_test.sqlite3"
    await init_db(db_path)
    pool = await get_pool()
    await pool.write_execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", ("/tmp/soak_ws", "soak_ws"))

    process = psutil.Process()
    initial_rss = process.memory_info().rss / (1024 * 1024)  # MB
    
    start_time = time.time()
    tasks_created = 0
    steps_completed = 0
    
    print(f"Starting Soak Test (Duration: {duration_seconds}s, Initial RSS: {initial_rss:.1f}MB)")

    while (time.time() - start_time) < duration_seconds:
        job_id = f"soak_job_{tasks_created}"
        task_id = f"soak_task_{tasks_created}"
        
        await create_job(job_id, "/tmp/soak_ws", "soak_workflow")
        await create_task(task_id, job_id, f"Soak Task {tasks_created}", "Tester", dependencies=[])
        
        # Complete 5 steps per task
        for step_num in range(1, 6):
            step_id = await log_step_pending(task_id, job_id, step_num, "test", {"step": step_num})
            await mark_step_running(step_id)
            await mark_step_completed(step_id, {"result": "ok"})
            steps_completed += 1
        
        tasks_created += 1
        
        # Log memory progress
        if tasks_created % 20 == 0:
            current_rss = process.memory_info().rss / (1024 * 1024)
            print(f"[{tasks_created} tasks] RSS: {current_rss:.1f}MB (delta: {current_rss - initial_rss:.1f}MB)")

        await asyncio.sleep(interval_seconds)
    
    final_rss = process.memory_info().rss / (1024 * 1024)
    growth = final_rss - initial_rss
    print(f"\nSoak test complete:")
    print(f"  Tasks created: {tasks_created}")
    print(f"  Steps completed: {steps_completed}")
    print(f"  Memory growth: {growth:.1f}MB")
    print(f"  Result: {'PASS' if growth < 50 else 'FAIL'} (target: <50MB growth)")

    await close_db()
    if db_path.exists():
        try:
            os.remove(db_path)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(soak_test())
