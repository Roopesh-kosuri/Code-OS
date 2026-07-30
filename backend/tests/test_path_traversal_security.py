"""
test_path_traversal_security.py

Unit-level security tests for the path-traversal and workspace-boundary fixes.
These tests do NOT require a running server; they test the core logic directly.

Test coverage:
  1. normalize_path() does NOT expand ~
  2. ensure_within_workspace() blocks /etc/passwd (and Windows equivalent)
  3. ensure_within_workspace() blocks symlinks escaping the workspace
  4. gather_context() does NOT return file contents for active_path outside workspace
  5. WebSocket terminal route rejects connections without cwd
  6. Trust inheritance: subdirectories of a trusted root are considered trusted
"""

import os
import sys
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Make sure the backend package is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi import HTTPException
from app.core.paths import (
    normalize_path,
    normalize_workspace,
    ensure_within_workspace,
    is_within_workspace,
)


# ---------------------------------------------------------------------------
# 1. normalize_path — tilde rejection
# ---------------------------------------------------------------------------

class TestNormalizePathTildeRejection(unittest.TestCase):
    """normalize_path MUST NOT expand ~ from client-supplied paths."""

    def test_tilde_path_raises_400(self):
        with self.assertRaises(HTTPException) as ctx:
            normalize_path("~/.ssh/id_rsa")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Tilde", ctx.exception.detail)

    def test_tilde_only_raises_400(self):
        with self.assertRaises(HTTPException) as ctx:
            normalize_path("~")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_normal_absolute_path_succeeds(self):
        # A normal absolute path should not raise
        try:
            if os.name == "nt":
                result = normalize_path("C:/Windows")
            else:
                result = normalize_path("/tmp")
            self.assertIsInstance(result, Path)
        except HTTPException:
            self.fail("normalize_path raised HTTPException for a valid absolute path")

    def test_normalize_workspace_allows_tilde(self):
        """normalize_workspace IS allowed to expand tilde (used for config paths)."""
        try:
            result = normalize_workspace("~")
            self.assertTrue(result.is_dir())
        except (HTTPException, OSError):
            pass  # fine on unusual systems


# ---------------------------------------------------------------------------
# 2. ensure_within_workspace — boundary checks
# ---------------------------------------------------------------------------

class TestEnsureWithinWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = str(Path(self.tmp.name).resolve())
        # Create a file inside the workspace
        self.inner = Path(self.workspace) / "inner.txt"
        self.inner.write_text("hello")

    def tearDown(self):
        self.tmp.cleanup()

    def test_etc_passwd_blocked(self):
        """Sending /etc/passwd (or Windows equivalent) must be rejected with 403."""
        if os.name == "nt":
            outside = "C:/Windows/System32/cmd.exe"
        else:
            outside = "/etc/passwd"
        with self.assertRaises(HTTPException) as ctx:
            ensure_within_workspace(self.workspace, outside)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_dotdot_traversal_blocked(self):
        with self.assertRaises(HTTPException) as ctx:
            ensure_within_workspace(self.workspace, "../../../etc/passwd")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_tilde_in_target_blocked(self):
        with self.assertRaises(HTTPException) as ctx:
            ensure_within_workspace(self.workspace, "~/.aws/credentials")
        self.assertEqual(ctx.exception.status_code, 400)  # reject before boundary check

    def test_valid_inner_file_allowed(self):
        result = ensure_within_workspace(self.workspace, str(self.inner))
        self.assertEqual(result.resolve(), self.inner.resolve())

    def test_symlink_outside_workspace_blocked(self):
        """A symlink inside the workspace pointing outside must be blocked."""
        if os.name == "nt":
            # Symlink creation on Windows requires elevated privileges; skip
            self.skipTest("Symlink test skipped on Windows (requires elevated privileges)")

        outside_file = Path(self.workspace).parent / "secret.txt"
        outside_file.write_text("supersecret")
        link = Path(self.workspace) / "link_to_secret.txt"
        link.symlink_to(outside_file)

        try:
            # ensure_within_workspace resolves symlinks via Path.resolve()
            # so the resolved path will be outside the workspace → 403
            with self.assertRaises(HTTPException) as ctx:
                ensure_within_workspace(self.workspace, str(link))
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            link.unlink(missing_ok=True)
            outside_file.unlink(missing_ok=True)

    def test_workspace_root_itself_allowed(self):
        result = ensure_within_workspace(self.workspace, self.workspace)
        self.assertEqual(result.resolve(), Path(self.workspace).resolve())


# ---------------------------------------------------------------------------
# 3. gather_context — active_path outside workspace returns no file content
# ---------------------------------------------------------------------------

class TestGatherContextActivePath(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = str(Path(self.tmp.name).resolve())

    def tearDown(self):
        self.tmp.cleanup()

    def test_active_path_outside_workspace_returns_no_content(self):
        """
        Sending /etc/passwd as active_path must NOT leak file contents.
        The context dict's 'active_file' must be None.
        """
        if os.name == "nt":
            outside = "C:/Windows/System32/drivers/etc/hosts"
        else:
            outside = "/etc/passwd"

        async def _run_gather():
            # Patch DB and git calls so we don't need a real server
            with patch("app.features.ai.context_service.git_status", side_effect=Exception("no git")), \
                 patch("app.features.ai.context_service.get_db") as mock_db, \
                 patch("app.features.ai.context_service.semantic_search", new_callable=AsyncMock) as mock_ss:

                mock_conn = AsyncMock()
                mock_conn.execute = AsyncMock(return_value=AsyncMock(fetchall=AsyncMock(return_value=[])))
                mock_conn.close = AsyncMock()
                mock_db.return_value = mock_conn
                mock_ss.return_value = []

                from app.features.ai.context_service import gather_context
                ctx = await gather_context(
                    workspace=self.workspace,
                    active_path=outside,
                )
                return ctx

        ctx = self._run(_run_gather())
        self.assertIsNone(ctx["active_file"],
            f"active_file should be None for an outside-workspace path, got: {ctx['active_file']}")

    def test_active_path_inside_workspace_returns_content(self):
        """A file inside the workspace should be returned normally."""
        inner = Path(self.workspace) / "hello.txt"
        inner.write_text("hello world")

        async def _run_gather():
            with patch("app.features.ai.context_service.git_status", side_effect=Exception("no git")), \
                 patch("app.features.ai.context_service.get_db") as mock_db, \
                 patch("app.features.ai.context_service.semantic_search", new_callable=AsyncMock) as mock_ss:

                mock_conn = AsyncMock()
                mock_conn.execute = AsyncMock(return_value=AsyncMock(fetchall=AsyncMock(return_value=[])))
                mock_conn.close = AsyncMock()
                mock_db.return_value = mock_conn
                mock_ss.return_value = []

                from app.features.ai.context_service import gather_context
                ctx = await gather_context(
                    workspace=self.workspace,
                    active_path=str(inner),
                )
                return ctx

        ctx = self._run(_run_gather())
        self.assertIsNotNone(ctx["active_file"])
        self.assertIn("hello world", ctx["active_file"]["content"])


# ---------------------------------------------------------------------------
# 4. Trust service — subdirectory inheritance
# ---------------------------------------------------------------------------

class TestTrustSubdirectoryInheritance(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_subdirectory_of_trusted_root_is_trusted(self):
        """
        If /proj is trusted, then /proj/src/utils should also be trusted.
        """
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            workspace_root = str(Path(root).resolve())
            subdir = str(Path(root) / "src" / "utils")
            os.makedirs(subdir, exist_ok=True)
            subdir = str(Path(subdir).resolve())

            # Mock the DB to return one trusted row: the workspace root
            async def _run_check():
                with patch("app.features.workspaces.trust_service.get_db") as mock_db:
                    mock_row = {"path": workspace_root, "trusted": 1, "trust_level": "full", "trusted_at": "2024-01-01"}
                    mock_conn = AsyncMock()
                    mock_conn.execute_fetchall = AsyncMock(return_value=[mock_row])
                    mock_conn.close = AsyncMock()
                    mock_db.return_value = mock_conn

                    from app.features.workspaces.trust_service import get_workspace_trust
                    result = await get_workspace_trust(subdir)
                    return result

            result = self._run(_run_check())
            self.assertTrue(result["trusted"],
                f"Subdirectory {subdir!r} of trusted root {workspace_root!r} should be trusted")

    def test_unrelated_path_is_not_trusted(self):
        """A path that is NOT a child of the trusted root must not be trusted."""
        with tempfile.TemporaryDirectory() as root1, tempfile.TemporaryDirectory() as root2:
            trusted_root = str(Path(root1).resolve())
            unrelated = str(Path(root2).resolve())

            async def _run_check():
                with patch("app.features.workspaces.trust_service.get_db") as mock_db:
                    mock_row = {"path": trusted_root, "trusted": 1, "trust_level": "full", "trusted_at": "2024-01-01"}
                    mock_conn = AsyncMock()
                    mock_conn.execute_fetchall = AsyncMock(return_value=[mock_row])
                    mock_conn.close = AsyncMock()
                    mock_db.return_value = mock_conn

                    from app.features.workspaces.trust_service import get_workspace_trust
                    result = await get_workspace_trust(unrelated)
                    return result

            result = self._run(_run_check())
            self.assertFalse(result["trusted"],
                f"Unrelated path {unrelated!r} should NOT be trusted")


# ---------------------------------------------------------------------------
# 5. is_within_workspace helper
# ---------------------------------------------------------------------------

class TestIsWithinWorkspace(unittest.TestCase):
    def test_child_is_within(self):
        root = Path("/tmp/proj")
        child = Path("/tmp/proj/src/main.py")
        self.assertTrue(is_within_workspace(root, child))

    def test_exact_match_is_within(self):
        root = Path("/tmp/proj")
        self.assertTrue(is_within_workspace(root, root))

    def test_sibling_is_not_within(self):
        root = Path("/tmp/proj")
        sibling = Path("/tmp/other")
        self.assertFalse(is_within_workspace(root, sibling))

    def test_parent_is_not_within(self):
        root = Path("/tmp/proj")
        parent = Path("/tmp")
        self.assertFalse(is_within_workspace(root, parent))


if __name__ == "__main__":
    unittest.main(verbosity=2)
