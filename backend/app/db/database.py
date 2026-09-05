import aiosqlite
import sqlite3
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, List
from ..core.config import get_settings


logger = logging.getLogger(__name__)

_db: Optional[aiosqlite.Connection] = None
_db_lock: Optional[asyncio.Lock] = None


class ConnectionPool:
    """aiosqlite connection pool with 3 read connections and 1 serialized write connection."""
    def __init__(self, db_path: Path, read_count: int = 3) -> None:
        self.db_path = db_path
        self.read_count = read_count
        self._read_queue: Optional[asyncio.Queue[aiosqlite.Connection]] = None
        self._write_conn: Optional[aiosqlite.Connection] = None
        self._write_lock: Optional[asyncio.Lock] = None
        self._all_conns: List[aiosqlite.Connection] = []

    async def initialize(self) -> aiosqlite.Connection:
        self._read_queue = asyncio.Queue()
        self._write_lock = asyncio.Lock()
        self._all_conns.clear()

        try:
            # 1. Initialize write connection
            self._write_conn = await aiosqlite.connect(self.db_path)
            self._all_conns.append(self._write_conn)
            self._write_conn.row_factory = aiosqlite.Row
            await self._configure_pragmas(self._write_conn)

            # 2. Initialize read connections
            for _ in range(self.read_count):
                r_conn = await aiosqlite.connect(self.db_path)
                self._all_conns.append(r_conn)
                r_conn.row_factory = aiosqlite.Row
                await self._configure_pragmas(r_conn)
                await r_conn.execute("PRAGMA query_only=ON;")
                await self._read_queue.put(r_conn)

            return self._write_conn
        except Exception:
            await self.close()
            raise

    async def _configure_pragmas(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA busy_timeout=5000;")
        await conn.execute("PRAGMA cache_size=-64000;")
        await conn.execute("PRAGMA mmap_size=268435456;")
        await conn.execute("PRAGMA temp_store=MEMORY;")
        # Health check
        cur = await conn.execute("PRAGMA quick_check(1);")
        res = await cur.fetchone()
        if res and res[0] != "ok":
            logger.warning("Database quick_check warning: %s", res[0])

    async def acquire_read(self) -> aiosqlite.Connection:
        if self._read_queue is None:
            return self._write_conn
        return await self._read_queue.get()

    async def release_read(self, conn: aiosqlite.Connection) -> None:
        if self._read_queue is not None:
            await self._read_queue.put(conn)

    async def read_query(self, sql: str, params: tuple = ()) -> list:
        t0 = time.perf_counter()
        conn = await self.acquire_read()
        try:
            try:
                async with asyncio.timeout(10.0):
                    cur = await conn.execute(sql, params)
                    rows = await cur.fetchall()
                    elapsed = time.perf_counter() - t0
                    if elapsed > 1.0:
                        logger.warning("Slow read query (%.2fs): %s", elapsed, sql[:100])
                    return rows
            except asyncio.TimeoutError:
                logger.error("Read query timed out (>10s): %s", sql[:100])
                raise TimeoutError("Database query timed out")
        finally:
            await self.release_read(conn)

    async def write_execute(self, sql: str, params: tuple = ()) -> None:
        t0 = time.perf_counter()
        if self._write_lock is None or self._write_conn is None:
            raise RuntimeError("Database pool not initialized")
        async with self._write_lock:
            try:
                async with asyncio.timeout(10.0):
                    await self._write_conn.execute(sql, params)
                    await self._write_conn.commit()
                    elapsed = time.perf_counter() - t0
                    if elapsed > 1.0:
                        logger.warning("Slow write query (%.2fs): %s", elapsed, sql[:100])
            except asyncio.TimeoutError:
                logger.error("Write query timed out (>10s): %s", sql[:100])
                try:
                    await self._write_conn.rollback()
                except Exception:
                    pass
                raise TimeoutError("Database write timed out")
            except Exception:
                try:
                    await self._write_conn.rollback()
                except Exception:
                    pass
                raise

    async def close(self) -> None:
        conns_to_close = list(self._all_conns)
        if self._write_conn in conns_to_close:
            conns_to_close.remove(self._write_conn)
            conns_to_close.append(self._write_conn)
        for conn in conns_to_close:
            try:
                try:
                    async with asyncio.timeout(0.5):
                        await conn.rollback()
                except Exception:
                    pass
                async with asyncio.timeout(1.5):
                    await conn.close()
            except Exception as exc:
                logger.debug("Error closing connection: %s", exc)
        self._all_conns.clear()
        self._write_conn = None
        self._read_queue = None


_pool: Optional[ConnectionPool] = None


def _get_db_lock() -> asyncio.Lock:
    global _db_lock
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _db_lock is None or (getattr(_db_lock, "_loop", None) is not None and _db_lock._loop is not current_loop):
        _db_lock = asyncio.Lock()
    return _db_lock


async def get_db() -> aiosqlite.Connection:
    """Return the shared single SQLite connection for the application."""
    global _db
    if _db is None:
        async with _get_db_lock():
            if _db is None:
                await init_db()
    return _db


async def get_pool() -> ConnectionPool:
    """Return the aiosqlite connection pool."""
    global _pool
    if _pool is None or _pool._write_conn is None:
        await get_db()
    return _pool


async def _run_migrations(db: aiosqlite.Connection) -> None:
    """Lightweight schema migration system using ordered migration versions."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur = await db.execute("SELECT version FROM _schema_migrations")
    rows = await cur.fetchall()
    applied = {r[0] for r in rows}

    # Migration 1: workspaces and agent_jobs dynamic column additions
    if 1 not in applied:
        try:
            cur = await db.execute("PRAGMA table_info(workspaces)")
            w_rows = await cur.fetchall()
            cols = [r["name"] for r in w_rows]
            if "is_active" not in cols:
                await db.execute("ALTER TABLE workspaces ADD COLUMN is_active INTEGER DEFAULT 0")
            if "last_opened_at" not in cols:
                await db.execute("ALTER TABLE workspaces ADD COLUMN last_opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
        except Exception as exc:
            logger.debug("Migration 1 workspaces: %s", exc)

        try:
            cur = await db.execute("PRAGMA table_info(agent_jobs)")
            j_rows = await cur.fetchall()
            cols = [r["name"] for r in j_rows]
            if "workspace_manifest" not in cols:
                await db.execute("ALTER TABLE agent_jobs ADD COLUMN workspace_manifest TEXT DEFAULT '{}'")
            if "user_request" not in cols:
                await db.execute("ALTER TABLE agent_jobs ADD COLUMN user_request TEXT DEFAULT ''")
        except Exception as exc:
            logger.debug("Migration 1 agent_jobs: %s", exc)

        await db.execute("INSERT OR IGNORE INTO _schema_migrations (version, name) VALUES (1, 'column_additions')")
        await db.commit()

    # Migration 2: status CHECK validation triggers for pre-existing tables
    if 2 not in applied:
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_agent_jobs_status_insert
            BEFORE INSERT ON agent_jobs
            FOR EACH ROW
            WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'cancelled', 'waiting')
            BEGIN
                SELECT RAISE(ABORT, 'Invalid status in agent_jobs');
            END;
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_agent_jobs_status_update
            BEFORE UPDATE OF status ON agent_jobs
            FOR EACH ROW
            WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'cancelled', 'waiting')
            BEGIN
                SELECT RAISE(ABORT, 'Invalid status in agent_jobs');
            END;
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_agent_tasks_status_insert
            BEFORE INSERT ON agent_tasks
            FOR EACH ROW
            WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'waiting', 'cancelled', 'skipped')
            BEGIN
                SELECT RAISE(ABORT, 'Invalid status in agent_tasks');
            END;
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_agent_tasks_status_update
            BEFORE UPDATE OF status ON agent_tasks
            FOR EACH ROW
            WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'waiting', 'cancelled', 'skipped')
            BEGIN
                SELECT RAISE(ABORT, 'Invalid status in agent_tasks');
            END;
        """)
        await db.execute("INSERT OR IGNORE INTO _schema_migrations (version, name) VALUES (2, 'status_triggers')")
        await db.commit()

    # Migration 3: Phase 2 performance indexes & symbol_index table
    if 3 not in applied:
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON agent_jobs(status);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_proposals_workspace ON edit_proposals(workspace);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);")
            try:
                cur = await db.execute("PRAGMA table_info(edit_proposals)")
                ep_rows = await cur.fetchall()
                ep_cols = [r["name"] for r in ep_rows]
                if "payload" not in ep_cols:
                    await db.execute("ALTER TABLE edit_proposals ADD COLUMN payload TEXT DEFAULT '{}'")
            except Exception:
                pass

            await db.execute("""
                CREATE TABLE IF NOT EXISTS symbol_index (
                    workspace TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    symbols_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (workspace, file_path),
                    FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_symbol_index_workspace ON symbol_index(workspace);")
        except Exception as exc:
            logger.debug("Migration 3 performance indexes: %s", exc)

        await db.execute("INSERT OR IGNORE INTO _schema_migrations (version, name) VALUES (3, 'phase2_indexes')")
        await db.commit()

    # Migration 4: Phase 3A spawned_processes tracking
    if 4 not in applied:
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS spawned_processes (
                    pid INTEGER PRIMARY KEY,
                    process_type TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    spawned_at REAL NOT NULL
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_spawned_processes_workspace ON spawned_processes(workspace);")
        except Exception as exc:
            logger.debug("Migration 4 spawned_processes: %s", exc)

        await db.execute("INSERT OR IGNORE INTO _schema_migrations (version, name) VALUES (4, 'spawned_processes')")
        await db.commit()

    # Migration 5: Phase 3B pending_approvals and paused status triggers
    if 5 not in applied:
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_approvals (
                    action_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pending_approvals_workspace ON pending_approvals(workspace);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pending_approvals_expires ON pending_approvals(expires_at);")

            # Add pause_reason and retry_after columns to agent_jobs if not present
            try:
                cur = await db.execute("PRAGMA table_info(agent_jobs)")
                j_rows = await cur.fetchall()
                j_cols = [r["name"] for r in j_rows]
                if "pause_reason" not in j_cols:
                    await db.execute("ALTER TABLE agent_jobs ADD COLUMN pause_reason TEXT DEFAULT ''")
                if "retry_after" not in j_cols:
                    await db.execute("ALTER TABLE agent_jobs ADD COLUMN retry_after REAL DEFAULT 0.0")
            except Exception as exc:
                logger.debug("Migration 5 agent_jobs cols: %s", exc)

            # Re-create triggers to support 'paused' status
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_jobs_status_insert;")
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_jobs_status_update;")
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_tasks_status_insert;")
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_tasks_status_update;")

            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_jobs_status_insert
                BEFORE INSERT ON agent_jobs
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'cancelled', 'waiting', 'paused')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_jobs');
                END;
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_jobs_status_update
                BEFORE UPDATE OF status ON agent_jobs
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'cancelled', 'waiting', 'paused')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_jobs');
                END;
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_tasks_status_insert
                BEFORE INSERT ON agent_tasks
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'waiting', 'cancelled', 'skipped', 'paused')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_tasks');
                END;
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_tasks_status_update
                BEFORE UPDATE OF status ON agent_tasks
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'waiting', 'cancelled', 'skipped', 'paused')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_tasks');
                END;
            """)
        except Exception as exc:
            logger.debug("Migration 5 pending_approvals: %s", exc)

        await db.execute("INSERT OR IGNORE INTO _schema_migrations (version, name) VALUES (5, 'pending_approvals_and_paused')")
        await db.commit()

    # Migration 6: Phase 3C task_steps table and 'interrupted' status triggers
    if 6 not in applied:
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS task_steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    step_num INTEGER NOT NULL,
                    step_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
                    payload_hash TEXT NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (job_id) REFERENCES agent_jobs(id) ON DELETE CASCADE
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_status ON task_steps(status);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_task_hash ON task_steps(task_id, payload_hash);")

            # Re-create triggers to support 'interrupted' status on agent_tasks and agent_jobs
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_jobs_status_insert;")
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_jobs_status_update;")
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_tasks_status_insert;")
            await db.execute("DROP TRIGGER IF EXISTS trg_agent_tasks_status_update;")

            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_jobs_status_insert
                BEFORE INSERT ON agent_jobs
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'cancelled', 'waiting', 'paused', 'interrupted')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_jobs');
                END;
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_jobs_status_update
                BEFORE UPDATE OF status ON agent_jobs
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'cancelled', 'waiting', 'paused', 'interrupted')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_jobs');
                END;
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_tasks_status_insert
                BEFORE INSERT ON agent_tasks
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'waiting', 'cancelled', 'skipped', 'paused', 'interrupted')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_tasks');
                END;
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_agent_tasks_status_update
                BEFORE UPDATE OF status ON agent_tasks
                FOR EACH ROW
                WHEN NEW.status NOT IN ('queued', 'pending', 'running', 'completed', 'failed', 'waiting', 'cancelled', 'skipped', 'paused', 'interrupted')
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid status in agent_tasks');
                END;
            """)
        except Exception as exc:
            logger.debug("Migration 6 task_steps: %s", exc)

        await db.execute("INSERT OR IGNORE INTO _schema_migrations (version, name) VALUES (6, 'task_steps_and_interrupted')")
        await db.commit()


async def init_db(db_path: Path | str | None = None) -> aiosqlite.Connection:
    """Initialize connection pool and tables if they do not exist."""
    global _db, _pool
    if db_path is not None:
        db_path = Path(db_path)
    else:
        settings = get_settings()
        db_path = settings.database_path

    db_path.parent.mkdir(parents=True, exist_ok=True)

    _pool = ConnectionPool(db_path, read_count=4)
    try:
        _db = await _pool.initialize()
    except (sqlite3.DatabaseError, Exception) as init_err:
        logger.error("Failed to initialize database (possible corruption): %s. Attempting auto-recovery...", init_err)
        await _pool.close()
        _pool = None
        corrupt_backup = db_path.with_suffix(f".corrupted_{int(time.time())}.bak")
        try:
            if db_path.exists():
                db_path.rename(corrupt_backup)
        except Exception as ren_err:
            logger.warning("Could not rename corrupted db file: %s", ren_err)
        _pool = ConnectionPool(db_path, read_count=4)
        _db = await _pool.initialize()

    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            last_opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT,
            size INTEGER,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS edit_proposals (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            task_id TEXT,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'applied')),
            diff TEXT NOT NULL DEFAULT '',
            changes TEXT NOT NULL DEFAULT '[]',
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_edit_proposals_workspace ON edit_proposals(workspace);

        CREATE TABLE IF NOT EXISTS activity_log (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            turn_number INTEGER NOT NULL,
            agent_role TEXT NOT NULL,
            message TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'info',
            tools_used TEXT NOT NULL DEFAULT '[]',
            files_touched TEXT NOT NULL DEFAULT '[]',
            commit_hash TEXT,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_activity_log_workspace ON activity_log(workspace);
        CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);

        CREATE TABLE IF NOT EXISTS file_index (
            path TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            content TEXT,
            embedding BLOB,
            tokens INTEGER,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_file_index_workspace ON file_index(workspace);

        CREATE TABLE IF NOT EXISTS symbol_index (
            workspace TEXT NOT NULL,
            file_path TEXT NOT NULL,
            mtime REAL NOT NULL,
            symbols_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (workspace, file_path),
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_symbol_index_workspace ON symbol_index(workspace);

        CREATE TABLE IF NOT EXISTS spawned_processes (
            pid INTEGER PRIMARY KEY,
            process_type TEXT NOT NULL,
            workspace TEXT NOT NULL,
            spawned_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_spawned_processes_workspace ON spawned_processes(workspace);

        CREATE TABLE IF NOT EXISTS pending_approvals (
            action_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            workspace TEXT NOT NULL,
            action_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pending_approvals_workspace ON pending_approvals(workspace);
        CREATE INDEX IF NOT EXISTS idx_pending_approvals_expires ON pending_approvals(expires_at);

        CREATE TABLE IF NOT EXISTS task_steps (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            step_num INTEGER NOT NULL,
            step_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
            payload_hash TEXT NOT NULL,
            result_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES agent_jobs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id);
        CREATE INDEX IF NOT EXISTS idx_task_steps_status ON task_steps(status);
        CREATE INDEX IF NOT EXISTS idx_task_steps_task_hash ON task_steps(task_id, payload_hash);

        CREATE TABLE IF NOT EXISTS repo_architecture (
            workspace TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            key_patterns TEXT NOT NULL DEFAULT '[]',
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
            status TEXT NOT NULL CHECK (status IN ('queued', 'pending', 'running', 'completed', 'failed', 'cancelled', 'waiting', 'paused', 'interrupted')),
            started_at TEXT,
            completed_at TEXT,
            token_usage INTEGER DEFAULT 0,
            duration REAL DEFAULT 0.0,
            files_modified TEXT DEFAULT '[]',
            errors TEXT DEFAULT '',
            logs TEXT DEFAULT '[]',
            workspace_manifest TEXT DEFAULT '{}',
            user_request TEXT DEFAULT '',
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_jobs_workspace ON agent_jobs(workspace);
        CREATE INDEX IF NOT EXISTS idx_agent_jobs_status ON agent_jobs(status);

        CREATE TABLE IF NOT EXISTS agent_tasks (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            title TEXT NOT NULL,
            agent_role TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('queued', 'pending', 'running', 'completed', 'failed', 'waiting', 'cancelled', 'skipped', 'paused', 'interrupted')),
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
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
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

        CREATE TABLE IF NOT EXISTS api_keys (
            provider_id TEXT PRIMARY KEY,
            encrypted_key TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS repo_index_status (
            workspace TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'idle',
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
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace) REFERENCES workspaces(path) ON DELETE CASCADE
        );
        """
    )

    # Run schema migrations
    await _run_migrations(_db)

    await _db.commit()
    return _db


async def checkpoint_wal() -> None:
    """Checkpoint the WAL file to reclaim space."""
    pool = await get_pool()
    if pool._write_lock is None or pool._write_conn is None:
        return
    async with pool._write_lock:
        await pool._write_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")


async def close_db() -> None:
    """Close all database pool connections."""
    global _db, _pool, _db_lock
    _db_lock = None
    if _pool is not None:
        try:
            async with asyncio.timeout(3.0):
                await _pool.close()
        except Exception as exc:
            logger.warning("Error closing database connection pool: %s", exc)
        finally:
            _pool = None
            _db = None
    elif _db is not None:
        try:
            try:
                async with asyncio.timeout(0.5):
                    await _db.rollback()
            except Exception:
                pass
            async with asyncio.timeout(1.5):
                await _db.close()
        except Exception as exc:
            logger.warning("Error closing database connection: %s", exc)
        finally:
            _db = None
