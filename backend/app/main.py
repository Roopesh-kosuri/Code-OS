import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.logging import configure_logging
from backend.app.db.database import get_connection, init_db
from backend.app.features.ai.routes import router as ai_router
from backend.app.features.ai.agent_routes import router as agent_router
from backend.app.features.files.routes import router as files_router
from backend.app.features.git.routes import router as git_router
from backend.app.features.indexing.routes import router as indexing_router
from backend.app.features.search.routes import router as search_router
from backend.app.features.settings.routes import router as settings_router
from backend.app.features.terminal.routes import router as terminal_router
from backend.app.features.workspaces.routes import router as workspaces_router
from backend.app.features.workspaces.file_watcher import watcher
from backend.app.core.plugins.routes import router as plugins_router
from backend.app.core.plugins.plugin_manager import plugin_manager
from backend.app.features.mcp.routes import router as mcp_router
from backend.app.features.mcp.mcp_manager import mcp_manager
from backend.app.features.diagnostics.routes import router as diagnostics_router
from backend.app.features.duo.routes import router as duo_router

configure_logging()

app = FastAPI(title="CODE OS Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:5174", "http://localhost:5174",
        "http://127.0.0.1:5175", "http://localhost:5175",
        "http://127.0.0.1:5176", "http://localhost:5176",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    
    # Clean up any orphaned running/queued jobs from previous session crashes
    db = await get_connection()
    try:
        await db.execute("UPDATE agent_jobs SET status = 'failed', errors = 'Server restarted' WHERE status IN ('running', 'queued')")
        await db.execute("UPDATE agent_tasks SET status = 'failed' WHERE status IN ('running', 'queued')")
        await db.commit()
    finally:
        await db.close()
        
    watcher.set_event_loop(asyncio.get_running_loop())
    await plugin_manager.load_active_plugins()
    await mcp_manager.initialize_servers()
    from backend.app.features.ai.job_service import register_subscribers
    register_subscribers()


@app.on_event("shutdown")
async def shutdown() -> None:
    await mcp_manager.shutdown()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(workspaces_router, prefix="/api/workspaces", tags=["workspaces"])
app.include_router(files_router, prefix="/api/files", tags=["files"])
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(terminal_router, prefix="/api/terminal", tags=["terminal"])
app.include_router(ai_router, prefix="/api/ai", tags=["ai"])
app.include_router(git_router, prefix="/api/git", tags=["git"])
app.include_router(indexing_router, prefix="/api/index", tags=["indexing"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(agent_router, prefix="/api/agents", tags=["agents"])
app.include_router(plugins_router, prefix="/api/plugins", tags=["plugins"])
app.include_router(mcp_router, prefix="/api/mcp", tags=["mcp"])
app.include_router(diagnostics_router, prefix="/api/diagnostics", tags=["diagnostics"])
app.include_router(duo_router, prefix="/api/duo", tags=["duo"])
