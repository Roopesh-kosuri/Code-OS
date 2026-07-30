import aiosqlite
import logging
from pathlib import Path
from typing import Optional
from ..core.config import get_settings


logger = logging.getLogger(__name__)

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    """Return the shared single SQLite connection for the application."""
    global _db
    if _db is None:
        await init_db()
    return _db


async def init_db(db_path: str | Path | None = None) -> aiosqlite.Connection:
    """Initialize the shared database connection, configure PRAGMAs, and run schema scripts."""
    global _db
    if _db is not None:
        return _db

    if db_path is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = settings.database_path

    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row


    # Performance, integrity, and concurrency settings
    await _db.execute("PRAGMA journal_mode=WAL;")
    await _db.execute("PRAGMA foreign_keys=ON;")
    await _db.execute("PRAGMA busy_timeout=5000;")
    await _db.execute("PRAGMA cache_size=-2000;")
    await _db.execute("PRAGMA synchronous=NORMAL;")

    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            last_opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            provider_id TEXT PRIMARY KEY,
            encrypted_key TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS edit_proposals (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_edit_proposals_workspace ON edit_proposals(workspace);

        CREATE TABLE IF NOT EXISTS repo_index_status (
            workspace TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            total_files INTEGER NOT NULL DEFAULT 0,
            indexed_files INTEGER NOT NULL DEFAULT 0,
            changed_files INTEGER NOT NULL DEFAULT 0,
            project_type TEXT NOT NULL DEFAULT 'unknown',
            language_summary TEXT NOT NULL DEFAULT '{}',
            frameworks TEXT NOT NULL DEFAULT '[]',
            entry_points TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS repo_index_files (
            workspace TEXT NOT NULL,
            path TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            language TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            symbol_count INTEGER NOT NULL DEFAULT 0,
            imports_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (workspace, path),
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_repo_index_files_workspace ON repo_index_files(workspace);

        CREATE TABLE IF NOT EXISTS repo_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace TEXT NOT NULL,
            path TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            language TEXT NOT NULL,
            line INTEGER NOT NULL,
            column INTEGER NOT NULL DEFAULT 1,
            signature TEXT NOT NULL DEFAULT '',
            parent TEXT,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_repo_symbols_workspace_name ON repo_symbols(workspace, name);
        CREATE INDEX IF NOT EXISTS idx_repo_symbols_workspace ON repo_symbols(workspace);

        CREATE TABLE IF NOT EXISTS repo_import_edges (
            workspace TEXT NOT NULL,
            source_path TEXT NOT NULL,
            module TEXT NOT NULL,
            target_path TEXT,
            kind TEXT NOT NULL DEFAULT 'import',
            PRIMARY KEY (workspace, source_path, module),
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS repo_dependencies (
            workspace TEXT NOT NULL,
            name TEXT NOT NULL,
            version TEXT,
            source TEXT NOT NULL,
            PRIMARY KEY (workspace, name, source),
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS repo_folders (
            workspace TEXT NOT NULL,
            path TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            folder_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (workspace, path),
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS repo_memory (
            workspace TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (workspace, key),
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS agent_jobs (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            workflow TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            token_usage INTEGER DEFAULT 0,
            duration REAL DEFAULT 0.0,
            files_modified TEXT DEFAULT '[]',
            errors TEXT DEFAULT '',
            logs TEXT DEFAULT '[]',
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_jobs_workspace ON agent_jobs(workspace);
        CREATE INDEX IF NOT EXISTS idx_agent_jobs_status ON agent_jobs(status);

        CREATE TABLE IF NOT EXISTS agent_tasks (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            title TEXT NOT NULL,
            agent_role TEXT NOT NULL,
            status TEXT NOT NULL,
            dependencies TEXT DEFAULT '[]',
            assigned_agent TEXT,
            reasoning_summary TEXT DEFAULT '',
            estimated_effort TEXT DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            pending_action TEXT DEFAULT NULL,
            structured_data TEXT DEFAULT NULL,
            FOREIGN KEY (job_id) REFERENCES agent_jobs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_job_id ON agent_tasks(job_id);
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);

        CREATE TABLE IF NOT EXISTS duo_sessions (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            task_description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            current_round INTEGER NOT NULL DEFAULT 0,
            max_rounds INTEGER NOT NULL DEFAULT 5,
            final_proposal_id TEXT,
            generator_config TEXT NOT NULL DEFAULT '{}',
            critic_config TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_duo_sessions_workspace ON duo_sessions(workspace);

        CREATE TABLE IF NOT EXISTS duo_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            round_number INTEGER NOT NULL,
            generator_output TEXT NOT NULL DEFAULT '',
            proposal_id TEXT,
            critic_verdict TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES duo_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_duo_rounds_session ON duo_rounds(session_id, round_number);

        CREATE TABLE IF NOT EXISTS chat_threads (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chat_threads_workspace ON chat_threads(workspace);

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            attached_paths TEXT DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id);

        CREATE TABLE IF NOT EXISTS workspace_trust (
            path TEXT PRIMARY KEY,
            trusted INTEGER NOT NULL DEFAULT 0,
            trust_level TEXT,
            trusted_at TEXT,
            FOREIGN KEY (path) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        """
    )
    await _db.commit()
    return _db


async def close_db() -> None:
    """Close the shared database connection."""
    global _db
    if _db is not None:
        try:
            await _db.close()
        except Exception as exc:
            logger.warning("Error closing database connection: %s", exc)
        finally:
            _db = None



