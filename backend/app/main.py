import asyncio
from contextlib import asynccontextmanager
import logging
import uuid

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

# Generate the session token BEFORE the app processes any requests.
generate_and_store_token()


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

    await cleanup_missing_workspaces()

    watcher.set_event_loop(asyncio.get_running_loop())
    await plugin_manager.load_active_plugins()
    await mcp_manager.initialize_servers()
    from app.features.ai.job_service import register_subscribers

    register_subscribers()

    yield

    # Shutdown: Stop services safely with isolated try/except blocks
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


app = FastAPI(title="CODE OS Backend", version="0.1.0", lifespan=lifespan)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
        "http://127.0.0.1:5176",
        "http://localhost:5176",
        "http://127.0.0.1:5177",
        "http://localhost:5177",
        "http://127.0.0.1:5178",
        "http://localhost:5178",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
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


@app.get("/health")
@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
app.include_router(agent_router, prefix="/api/ai", tags=["agents-alias"])
app.include_router(plugins_router, prefix="/api/plugins", tags=["plugins"])
app.include_router(mcp_router, prefix="/api/mcp", tags=["mcp"])
app.include_router(diagnostics_router, prefix="/api/diagnostics", tags=["diagnostics"])
app.include_router(duo_router, prefix="/api/duo", tags=["duo"])
app.include_router(dual_coder_router, prefix="/api/dual-coder", tags=["dual-coder"])
app.include_router(chat_harness_router, prefix="/api/ai", tags=["chat-agent"])
