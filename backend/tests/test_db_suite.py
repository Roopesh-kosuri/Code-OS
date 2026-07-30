import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings
from app.db.database import get_db, init_db, close_db


class TestDatabaseSuite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await close_db()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_db.sqlite3"
        await init_db(self.db_path)


    async def asyncTearDown(self):
        await close_db()
        self.tmp_dir.cleanup()

    async def test_wal_mode_and_pragmas_enabled(self):
        """Verify journal_mode is WAL and foreign_keys is ON."""
        db = await get_db()
        async with db.execute("PRAGMA journal_mode;") as cursor:
            row = await cursor.fetchone()
            self.assertEqual(row[0].lower(), "wal")

        async with db.execute("PRAGMA foreign_keys;") as cursor:
            row = await cursor.fetchone()
            self.assertEqual(row[0], 1)

    async def test_foreign_key_cascade_deletion(self):
        """Verify deleting a workspace cascades and deletes its chat threads and messages."""
        db = await get_db()
        await db.execute(
            "INSERT INTO workspaces (path, name, last_opened_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            ("/test/ws1", "WS1"),
        )
        await db.execute(
            "INSERT INTO chat_threads (id, workspace, title) VALUES (?, ?, ?)",
            ("t1", "/test/ws1", "Thread 1"),
        )
        await db.execute(
            "INSERT INTO chat_messages (thread_id, role, content) VALUES (?, ?, ?)",
            ("t1", "user", "Hello"),
        )
        await db.commit()

        # Delete workspace
        await db.execute("DELETE FROM workspaces WHERE path = ?", ("/test/ws1",))
        await db.commit()

        # Verify threads and messages deleted via cascade
        async with db.execute("SELECT COUNT(*) FROM chat_threads WHERE workspace = ?", ("/test/ws1",)) as cursor:
            row = await cursor.fetchone()
            self.assertEqual(row[0], 0)

        async with db.execute("SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?", ("t1",)) as cursor:
            row = await cursor.fetchone()
            self.assertEqual(row[0], 0)

    async def test_50_concurrent_writes_no_db_locked_error(self):
        """Verify 50 concurrent async tasks writing to database without database locked error."""
        db = await get_db()

        async def write_op(i: int):
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"key_{i}", f"val_{i}"),
            )
            await db.commit()

        tasks = [write_op(i) for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                self.fail(f"Concurrent write failed with exception: {res}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
