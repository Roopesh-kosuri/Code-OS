import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure backend is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.database import get_db, init_db, close_db


class TestDatabaseConcurrencyAndCascade(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_code_os.sqlite3"

        # Patch get_settings to point to temporary database file
        class DummySettings:
            data_dir = Path(self.tmp.name)
            database_path = self.db_path

        self.patcher = patch("app.db.database.get_settings", return_value=DummySettings())
        self.patcher.start()

        # Reset module _db connection
        await close_db()
        await init_db()

    async def asyncTearDown(self):
        await close_db()
        self.patcher.stop()
        self.tmp.cleanup()

    async def test_pragmas(self):
        db = await get_db()
        cursor = await db.execute("PRAGMA journal_mode;")
        journal_mode = (await cursor.fetchone())[0]
        self.assertEqual(journal_mode.lower(), "wal")

        cursor = await db.execute("PRAGMA foreign_keys;")
        foreign_keys = (await cursor.fetchone())[0]
        self.assertEqual(foreign_keys, 1)

    async def test_50_concurrent_writes(self):
        """Verify that 50 concurrent writes execute cleanly without 'database is locked' errors."""
        db = await get_db()

        async def _write_op(i: int):
            key = f"concurrent_key_{i}"
            val = f"value_{i}"
            await db.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, val),
            )
            await db.commit()

        # Launch 50 concurrent writes via asyncio.gather
        tasks = [_write_op(i) for i in range(50)]
        await asyncio.gather(*tasks)

        # Verify all 50 keys exist in the database
        cursor = await db.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'concurrent_key_%'")
        count = (await cursor.fetchone())[0]
        self.assertEqual(count, 50)

    async def test_workspace_on_delete_cascade(self):
        """Verify ON DELETE CASCADE deletes all related records when a workspace is removed."""
        db = await get_db()

        ws_path = str(Path(self.tmp.name) / "demo_proj")
        ws_name = "demo_proj"

        # 1. Create workspace
        await db.execute(
            "INSERT INTO workspaces(path, name, last_opened_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (ws_path, ws_name),
        )

        # 2. Add related entries in child tables
        # Chat thread & message
        thread_id = "thread_123"
        await db.execute(
            "INSERT INTO chat_threads(id, workspace, title) VALUES (?, ?, ?)",
            (thread_id, ws_path, "Test Thread"),
        )
        await db.execute(
            "INSERT INTO chat_messages(thread_id, role, content) VALUES (?, ?, ?)",
            (thread_id, "user", "Hello AI"),
        )

        # Agent job & task
        job_id = "job_123"
        task_id = "task_123"
        await db.execute(
            "INSERT INTO agent_jobs(id, workspace, workflow, status) VALUES (?, ?, ?, ?)",
            (job_id, ws_path, "refactor", "queued"),
        )
        await db.execute(
            "INSERT INTO agent_tasks(id, job_id, title, agent_role, status) VALUES (?, ?, ?, ?, ?)",
            (task_id, job_id, "Analyze repo", "coder", "queued"),
        )

        # Duo session & round
        duo_id = "duo_123"
        await db.execute(
            "INSERT INTO duo_sessions(id, workspace, task_description, status) VALUES (?, ?, ?, ?)",
            (duo_id, ws_path, "Fix bug", "running"),
        )
        await db.execute(
            "INSERT INTO duo_rounds(session_id, round_number, generator_output) VALUES (?, ?, ?)",
            (duo_id, 1, "code diff"),
        )

        await db.commit()

        # Verify items exist before deletion
        cur = await db.execute("SELECT COUNT(*) FROM chat_threads WHERE workspace = ?", (ws_path,))
        self.assertEqual((await cur.fetchone())[0], 1)
        cur = await db.execute("SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?", (thread_id,))
        self.assertEqual((await cur.fetchone())[0], 1)

        # 3. Delete workspace
        await db.execute("DELETE FROM workspaces WHERE path = ?", (ws_path,))
        await db.commit()

        # 4. Assert CASCADE deleted all child rows across tables
        cur = await db.execute("SELECT COUNT(*) FROM chat_threads WHERE workspace = ?", (ws_path,))
        self.assertEqual((await cur.fetchone())[0], 0, "chat_threads row was not cascade-deleted")

        cur = await db.execute("SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?", (thread_id,))
        self.assertEqual((await cur.fetchone())[0], 0, "chat_messages row was not cascade-deleted")

        cur = await db.execute("SELECT COUNT(*) FROM agent_jobs WHERE workspace = ?", (ws_path,))
        self.assertEqual((await cur.fetchone())[0], 0, "agent_jobs row was not cascade-deleted")

        cur = await db.execute("SELECT COUNT(*) FROM agent_tasks WHERE id = ?", (task_id,))
        self.assertEqual((await cur.fetchone())[0], 0, "agent_tasks row was not cascade-deleted")

        cur = await db.execute("SELECT COUNT(*) FROM duo_sessions WHERE workspace = ?", (ws_path,))
        self.assertEqual((await cur.fetchone())[0], 0, "duo_sessions row was not cascade-deleted")

        cur = await db.execute("SELECT COUNT(*) FROM duo_rounds WHERE session_id = ?", (duo_id,))
        self.assertEqual((await cur.fetchone())[0], 0, "duo_rounds row was not cascade-deleted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
