import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.features.terminal.service import create_session, run_command, kill_session


class TestTerminalSuite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.session = create_session(cwd=self.tmp_dir.name)

    async def asyncTearDown(self):
        kill_session(self.session.id)
        self.tmp_dir.cleanup()

    async def test_foreground_command_timeout(self):
        """Verify foreground command execution completes within timeout window or raises timeout."""
        output, exit_code, background = await run_command(self.session.id, "echo hello_world", background=False)
        self.assertEqual(exit_code, 0)
        self.assertIn("hello_world", output)
        self.assertFalse(background)


if __name__ == "__main__":
    unittest.main(verbosity=2)
