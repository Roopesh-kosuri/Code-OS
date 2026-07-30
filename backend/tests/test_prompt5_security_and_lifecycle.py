import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import encrypt_secret, decrypt_secret, reset_fernet_cache, _get_fernet
from app.features.workspaces.file_watcher import watcher
from app.features.git.service import is_dangerous_file, commit


class TestPrompt5SecurityAndLifecycle(unittest.TestCase):
    def setUp(self):
        reset_fernet_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = str(Path(self.tmp.name).resolve())

    def tearDown(self):
        reset_fernet_cache()
        watcher.stop()
        self.tmp.cleanup()

    def test_fernet_roundtrip_and_caching(self):
        """Verify encryption round-trip and that Fernet is cached after first load."""
        secret = "my_super_secret_api_key_12345"
        encrypted = encrypt_secret(secret)
        self.assertNotEqual(secret, encrypted)

        decrypted = decrypt_secret(encrypted)
        self.assertEqual(secret, decrypted)

        # Call encrypt 100 times — verify Fernet instance is identical (cached in memory)
        instance1 = _get_fernet()
        for _ in range(100):
            encrypt_secret("test_val")
        instance2 = _get_fernet()

        self.assertIs(instance1, instance2, "Fernet instance must be cached in memory across calls")

    def test_file_watcher_stop_lifecycle(self):
        """Verify file watcher starts and stops cleanly without leaving zombie threads."""
        path = Path(self.workspace) / "watch_test"
        path.mkdir(exist_ok=True)

        watcher.watch(path)
        status_before = watcher.status()
        self.assertTrue(status_before["running"])
        self.assertIn(str(path), status_before["watched"])

        watcher.stop()
        status_after = watcher.status()
        self.assertFalse(status_after["running"])
        self.assertEqual(status_after["watched"], [])

    def test_git_dangerous_file_detection(self):
        """Verify secret file pattern detection."""
        dangerous_paths = [
            ".env",
            ".env.local",
            ".env.production",
            "server.key",
            "cert.pem",
            "secret_config.json",
            "aws_credentials",
            "id_rsa",
            "id_ed25519",
            "subfolder/secret_keys.txt",
        ]
        for p in dangerous_paths:
            self.assertTrue(is_dangerous_file(p), f"Path should be marked dangerous: {p}")

        safe_paths = [
            "src/index.ts",
            "main.py",
            "README.md",
            "package.json",
            "components/Button.tsx",
        ]
        for p in safe_paths:
            self.assertFalse(is_dangerous_file(p), f"Path should be marked safe: {p}")

    @patch("app.features.git.service.repo_for")
    def test_git_commit_does_not_stage_untracked_env(self, mock_repo_for):
        """Verify commit() stages git add -u (tracked modifications only), avoiding untracked .env files."""
        mock_repo = MagicMock()
        mock_repo.head.is_valid.return_value = False
        mock_commit_obj = MagicMock()
        mock_commit_obj.hexsha = "abc123456789"
        mock_repo.index.commit.return_value = mock_commit_obj
        mock_repo_for.return_value = mock_repo

        sha = commit(self.workspace, "Initial commit")
        self.assertEqual(sha, "abc123456789")

        # Verify git.add was called with u=True, NOT A=True
        mock_repo.git.add.assert_called_once_with(u=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
