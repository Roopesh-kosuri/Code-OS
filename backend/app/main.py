import os
os.environ["GIT_PYTHON_REFRESH"] = "quiet"
import asyncio
from contextlib import asynccontextmanager
import logging
import uuid
import time
from collections import deque
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import configure_logging, request_id_var

# Configure logging at the very start before module initializations
configure_logging()

logger = logging.getLogger(__name__)

from app.core.auth import generate_and_store_token, get_token, require_token
from app.db.database import get_db, init_db, close_db
from app.features.ai.routes import router as ai_router
from app.features.ai.agent_routes import router as agent_router
from app.features.files.routes import router as files_router
from app.features.git.routes import router as git_router
from app.features.debug.python_debugger import router as debug_router, websocket_router as debug_websocket_router
from app.features.indexing.routes import router as indexing_router
from app.features.search.routes import router as search_router
from app.features.settings.routes import router as settings_router
from app.features.terminal.routes import router as terminal_router
from app.features.workspaces.routes import router as workspaces_router
from app.features.workspaces.file_watcher import watcher
from app.core.plugins.routes import router as plugins_router
from app.core.plugins.plugin_manager import plugin_manager
from app.features.mcp.routes import router as mcp_router
from app.features.mcp.mcp_manager import mcp_manager
from app.features.diagnostics.routes import router as diagnostics_router
from app.features.duo.routes import router as duo_router
from app.features.ai.dual_coder_routes import router as dual_coder_router
from app.features.ai.chat_harness_routes import router as chat_harness_router
from app.core.monitoring import monitor
from app.core.errors import AppError, app_error_handler
_START_TIME = time.time()

# Generate the session token BEFORE the app processes any requests.
generate_and_store_token()


_system_readiness: dict[str, str] = {
    "db": "ready",
    "watcher": "initializing",
    "plugins": "initializing",
    "mcp": "initializing",
    "indexing": "ready",
}

async def _wal_checkpoint_worker() -> None:
    """Periodically checkpoints WAL file if it exceeds 100MB."""
    from app.core.config import get_settings
    from app.db.database import checkpoint_wal
    while True:
        try:
            await asyncio.sleep(300)
            settings = get_settings()
            wal_file = settings.database_path.with_name(settings.database_path.name + "-wal")
            if wal_file.is_file() and wal_file.stat().st_size > 100 * 1024 * 1024:
                logger.info("WAL file exceeds 100MB (%d bytes), checkpointing", wal_file.stat().st_size)
                await checkpoint_wal()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("WAL checkpoint worker: %s", exc)


async def _deferred_startup_tasks() -> None:
    try:
        loop = asyncio.get_running_loop()
        watcher.set_event_loop(loop)
        _system_readiness["watcher"] = "ready"
    except Exception as exc:
        logger.warning("Deferred startup watcher: %s", exc)
        _system_readiness["watcher"] = "error"

    try:
        await plugin_manager.load_active_plugins()
        _system_readiness["plugins"] = "ready"
    except Exception as exc:
        logger.warning("Deferred startup plugins: %s", exc)
        _system_readiness["plugins"] = "error"

    try:
        await mcp_manager.initialize_servers()
        _system_readiness["mcp"] = "ready"
    except Exception as exc:
        logger.warning("Deferred startup MCP servers: %s", exc)
        _system_readiness["mcp"] = "error"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("backend starting up")
    # Startup: Initialize shared DB and run schema migrations
    await init_db()
    db = await get_db()

    # Clean up orphaned running/queued jobs from previous session crashes
    await db.execute(
        "UPDATE agent_jobs SET status = 'failed', errors = 'Server restarted' WHERE status IN ('running', 'queued')"
    )
    await db.execute("UPDATE agent_tasks SET status = 'failed' WHERE status IN ('running', 'queued')")
    await db.commit()

    # Clean up missing workspace directories from DB
    from app.features.workspaces.service import cleanup_missing_workspaces
    from app.features.process_tracker import reap_orphaned_processes

    await cleanup_missing_workspaces()
    try:
        from app.features.ai.harness.approval_coordinator import load_pending_approvals_from_db
        await load_pending_approvals_from_db()
    except Exception as exc:
        logger.warning('Error reloading pending approvals on startup: %s', exc)

    try:
        from app.features.ai.step_tracker import recover_interrupted_tasks
        await recover_interrupted_tasks()
    except Exception as exc:
        logger.warning('Error recovering interrupted tasks on startup: %s', exc)
    try:
        await reap_orphaned_processes()
    except Exception as exc:
        logger.warning("Error during startup orphan process reaping: %s", exc)

    # Launch heavy background startup workers asynchronously without blocking /health
    asyncio.create_task(_deferred_startup_tasks())
    from app.features.ai.job_service import register_subscribers

    register_subscribers()
    wal_worker_task = asyncio.create_task(_wal_checkpoint_worker())

    yield

    # Shutdown: Stop services safely with isolated try/except blocks
    try:
        wal_worker_task.cancel()
    except Exception:
        pass

    try:
        from app.db.database import checkpoint_wal
        await checkpoint_wal()
    except Exception as exc:
        logger.warning("Error checkpointing WAL on shutdown: %s", exc)

    try:
        watcher.stop()
    except Exception as exc:
        logger.warning("Error stopping workspace watcher: %s", exc)

    try:
        await mcp_manager.shutdown()
    except Exception as exc:
        logger.warning("Error shutting down MCP manager: %s", exc)

    try:
        await close_db()
    except Exception as exc:
        logger.warning("Error closing database connection: %s", exc)

    logger.info("backend stopped")


app = FastAPI(title="CODE OS Backend", version="3.1.0", lifespan=lifespan)


async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)


app.add_middleware(BaseHTTPMiddleware, dispatch=require_token)
app.add_middleware(BaseHTTPMiddleware, dispatch=request_id_middleware)
app.add_exception_handler(AppError, app_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



_error_window: deque[float] = deque()
_error_window_lock = threading.Lock()
_ERROR_RATE_LIMIT_MAX = 100
_ERROR_RATE_LIMIT_WINDOW = 60.0  # seconds


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    now = time.time()
    with _error_window_lock:
        while _error_window and _error_window[0] < now - _ERROR_RATE_LIMIT_WINDOW:
            _error_window.popleft()
        if len(_error_window) >= _ERROR_RATE_LIMIT_MAX:
            logger.warning(
                "Error rate limit exceeded: %d errors in last %.0fs window. Throttling error reporting for %s (req_id=%s)",
                len(_error_window),
                _ERROR_RATE_LIMIT_WINDOW,
                request.url.path,
                req_id,
            )
            return JSONResponse(
                status_code=500,
                content={"error": "Rate limited"},
                headers={"X-Request-ID": req_id},
            )
        _error_window.append(now)

    error_id = monitor.capture_exception(exc, context={"path": request.url.path, "request_id": req_id})
    logger.error(
        "Unhandled exception processing request %s (%s): %s",
        req_id,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "type": exc.__class__.__name__,
            "request_id": req_id,
            "error_id": error_id,
        },
        headers={"X-Request-ID": req_id},
    )


from app.features.ai.schemas import HealthCheckResponse, ReadinessStatus, SubsystemHealth, HealthMetrics

@app.get("/health", response_model=HealthCheckResponse)
@app.get("/api/health", response_model=HealthCheckResponse)
async def health() -> HealthCheckResponse:
    """Comprehensive production health check verifying all critical subsystems and metrics."""
    import psutil
    from app.db.database import get_pool
    from app.features.ai.indexing.code_intelligence import _last_indexed_at
    from app.features.ai.harness.approval_coordinator import _pending_approvals

    subsystems: dict[str, SubsystemHealth] = {}
    is_healthy = True

    # 1. Database subsystem check
    try:
        pool = await get_pool()
        t0 = time.perf_counter()
        rows = await pool.read_query("PRAGMA quick_check(1);")
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        if rows and rows[0][0] == "ok":
            subsystems["database"] = SubsystemHealth(status="ok", latency_ms=latency_ms)
        else:
            subsystems["database"] = SubsystemHealth(status="degraded", latency_ms=latency_ms, error="Quick check failed")
            is_healthy = False
    except Exception as exc:
        subsystems["database"] = SubsystemHealth(status="degraded", error=str(exc))
        is_healthy = False

    # 2. File watcher check
    subsystems["file_watcher"] = SubsystemHealth(
        status="ok" if getattr(watcher, "_running", False) or getattr(watcher, "_observer", None) else "degraded"
    )

    # 3. MCP Manager check
    active_mcp = len(getattr(mcp_manager, "_sessions", {}))
    total_mcp = len(getattr(mcp_manager, "_servers", {}))
    subsystems["mcp_servers"] = SubsystemHealth(status="ok", active=active_mcp, total=total_mcp)

    # 4. Indexer check
    subsystems["indexer"] = SubsystemHealth(status="ok", files_indexed=len(_last_indexed_at))

    # Metrics
    memory_mb = 0.0
    try:
        proc = psutil.Process()
        memory_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
    except Exception:
        pass

    active_tasks = 0
    open_conns = 0
    try:
        pool = await get_pool()
        if pool:
            open_conns = len(pool._all_conns)
            task_rows = await pool.read_query("SELECT count(*) as cnt FROM agent_tasks WHERE status = 'running'")
            if task_rows:
                active_tasks = task_rows[0]["cnt"]
    except Exception:
        pass

    metrics = HealthMetrics(
        active_tasks=active_tasks,
        pending_approvals=len(_pending_approvals),
        memory_mb=memory_mb,
        open_connections=open_conns,
    )

    return HealthCheckResponse(
        status="healthy" if is_healthy else "degraded",
        version="3.1.0",
        uptime_seconds=round(time.time() - _START_TIME, 1),
        subsystems=subsystems,
        metrics=metrics,
    )


@app.get("/api/system/readiness", response_model=ReadinessStatus)
async def system_readiness() -> ReadinessStatus:
    """Return backend service readiness status."""
    return ReadinessStatus(status="ok", services=_system_readiness)


@app.get("/api/auth/token")
async def get_session_token():
    return {"token": get_token()}


# ── Monitoring & Performance Routes ──────────────────────────────────────────

@app.get("/api/monitoring/metrics")
async def get_metrics() -> dict:
    """Return latency percentiles (p50, p95, p99) and performance stats."""
    return {
        "status": "healthy",
        "metrics": monitor.get_metrics_summary(),
    }


@app.get("/api/monitoring/errors")
async def get_recent_errors(limit: int = 20) -> dict:
    """Return sanitized recent error events."""
    return {"errors": monitor.get_recent_errors(limit=limit)}


@app.post("/api/monitoring/report-error")
async def report_user_error(payload: dict) -> dict:
    """User-facing error report submission with sanitized context."""
    msg = payload.get("message", "User reported error")
    ctx = payload.get("context", {})
    err = RuntimeError(msg)
    err_id = monitor.capture_exception(err, context=ctx, user_reported=True)
    return {"success": True, "report_id": err_id, "message": "Error report received and sanitized."}


app.include_router(workspaces_router, prefix="/api/workspaces", tags=["workspaces"])
app.include_router(files_router, prefix="/api/files", tags=["files"])
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(terminal_router, prefix="/api/terminal", tags=["terminal"])
app.include_router(ai_router, prefix="/api/ai", tags=["ai"])
app.include_router(git_router, prefix="/api/git", tags=["git"])
app.include_router(debug_router, prefix="/api/debug", tags=["debug"])
app.include_router(debug_websocket_router, tags=["debug"])
app.include_router(indexing_router, prefix="/api/index", tags=["indexing"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(agent_router, prefix="/api/agents", tags=["agents"])
app.include_router(plugins_router, prefix="/api/plugins", tags=["plugins"])
app.include_router(mcp_router, prefix="/api/mcp", tags=["mcp"])
app.include_router(diagnostics_router, prefix="/api/diagnostics", tags=["diagnostics"])
app.include_router(duo_router, prefix="/api/duo", tags=["duo"])
app.include_router(dual_coder_router, prefix="/api/dual-coder", tags=["dual-coder"])
app.include_router(chat_harness_router, prefix="/api/ai", tags=["chat-agent"])
