from fastapi import APIRouter, HTTPException
import sys
import threading
from typing import Dict, Any

from backend.app.core.plugins.plugin_manager import plugin_manager
from backend.app.db.database import get_connection

router = APIRouter()

@router.get("/metrics")
async def get_metrics():
    # 1. Fetch system RAM/CPU info
    cpu_percent = 0.0
    memory_percent = 0.0
    memory_used_mb = 0.0
    memory_total_mb = 0.0

    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        memory_percent = mem.percent
        memory_used_mb = mem.used / (1024 * 1024)
        memory_total_mb = mem.total / (1024 * 1024)
    except ImportError:
        # Fallback for Windows wmic if psutil is not available
        if sys.platform == "win32":
            try:
                import subprocess
                output = subprocess.check_output(
                    "wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /Value",
                    shell=True,
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                lines = [line.strip() for line in output.split("\n") if "=" in line]
                mem_info = dict(line.split("=", 1) for line in lines)
                
                # values are in KB
                free_kb = float(mem_info.get("FreePhysicalMemory", 0))
                total_kb = float(mem_info.get("TotalVisibleMemorySize", 0))
                
                if total_kb > 0:
                    used_kb = total_kb - free_kb
                    memory_total_mb = total_kb / 1024.0
                    memory_used_mb = used_kb / 1024.0
                    memory_percent = (used_kb / total_kb) * 100.0
                    
                # CPU load percentage
                cpu_output = subprocess.check_output(
                    "wmic cpu get LoadPercentage /Value",
                    shell=True,
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                cpu_lines = [line.strip() for line in cpu_output.split("\n") if "=" in line]
                cpu_info = dict(line.split("=", 1) for line in cpu_lines)
                cpu_percent = float(cpu_info.get("LoadPercentage", 0))
            except Exception:
                # Mock fallback if commands fail
                cpu_percent = 15.4
                memory_percent = 45.2
                memory_used_mb = 7232.0
                memory_total_mb = 16000.0
        else:
            # Unix/Mac fallbacks (mock)
            cpu_percent = 12.0
            memory_percent = 50.0
            memory_used_mb = 4096.0
            memory_total_mb = 8192.0

    # 2. Get active agent tasks/jobs
    active_jobs_count = 0
    total_tokens = 0
    avg_duration_sec = 0.0
    total_jobs = 0
    estimated_cost_usd = 0.0

    try:
        db = await get_connection()
        try:
            # Query active (running) jobs
            cursor = await db.execute("SELECT COUNT(*) FROM agent_jobs WHERE status = 'running'")
            active_jobs_count = (await cursor.fetchone())[0]

            # Query overall tokens/duration
            cursor = await db.execute(
                "SELECT SUM(token_usage) as total_tokens, AVG(duration) as avg_duration, COUNT(*) as total_jobs FROM agent_jobs"
            )
            row = await cursor.fetchone()
            if row and row["total_jobs"] > 0:
                total_tokens = row["total_tokens"] or 0
                avg_duration_sec = row["avg_duration"] or 0.0
                total_jobs = row["total_jobs"]
                # Assuming $0.0015 per 1k tokens average (combining input/output costs)
                estimated_cost_usd = (total_tokens / 1000.0) * 0.0015
        finally:
            await db.close()
    except Exception:
        pass

    return {
        "system": {
            "cpu_usage_percent": round(cpu_percent, 1),
            "memory_usage_percent": round(memory_percent, 1),
            "memory_used_mb": round(memory_used_mb, 1),
            "memory_total_mb": round(memory_total_mb, 1),
            "active_threads": threading.active_count(),
            "active_agent_jobs": active_jobs_count
        },
        "ai": {
            "total_tokens": total_tokens,
            "average_latency_sec": round(avg_duration_sec, 2),
            "total_requests": total_jobs,
            "estimated_cost_usd": round(estimated_cost_usd, 4)
        },
        "plugins": {
            "loaded_count": len(plugin_manager.loaded_plugins),
            "load_times_ms": plugin_manager.load_times
        }
    }
