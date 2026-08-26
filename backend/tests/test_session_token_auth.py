"""
test_session_token_auth.py

Tests for the backend session-token authentication middleware.

Coverage:
  1. /health is accessible without a token (unauthenticated allowlist).
  2. Any other endpoint returns 401 when no Authorization header is present.
  3. Any other endpoint returns 401 when an invalid token is supplied.
  4. Any other endpoint returns 200/expected when the correct token is supplied.
  5. The token file is created with mode 0o600 (on POSIX).
  6. The environment allowlist does NOT include secret-looking variables.
"""

import asyncio
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

# Ensure backend is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import secrets as _secrets


class TestGenerateAndStoreToken(unittest.TestCase):
    """Token generation, file storage, and stdout emission."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _settings(self):
        s = MagicMock()
        s.data_dir = self.data_dir
        return s

    def test_token_is_written_to_file(self):
        import importlib
        import app.core.auth as auth_mod

        with patch("app.core.auth.get_token", side_effect=RuntimeError):
            pass  # just ensure importable

        with patch("app.core.auth._token_file_path", return_value=self.data_dir / "session_token"), \
             patch("builtins.print"):
            # Reset module-level token
            auth_mod._SESSION_TOKEN = None
            token = auth_mod.generate_and_store_token()

        token_file = self.data_dir / "session_token"
        self.assertTrue(token_file.exists())
        stored = token_file.read_text().strip()
        self.assertEqual(stored, token)
        self.assertEqual(len(token), 64)  # 32 bytes → 64 hex chars

    def test_token_file_mode_is_600(self):
        """On POSIX the token file must be mode 0600 (owner only)."""
        if os.name == "nt":
            self.skipTest("POSIX file mode test not applicable on Windows")

        import app.core.auth as auth_mod

        with patch("app.core.auth._token_file_path", return_value=self.data_dir / "session_token"), \
             patch("builtins.print"):
            auth_mod._SESSION_TOKEN = None
            auth_mod.generate_and_store_token()

        token_file = self.data_dir / "session_token"
        file_stat = token_file.stat()
        mode = stat.S_IMODE(file_stat.st_mode)
        self.assertEqual(mode, 0o600, f"Expected 0o600, got {oct(mode)}")

    def test_token_stdout_line(self):
        """The token line printed to stdout must be parseable."""
        import app.core.auth as auth_mod

        printed_lines = []
        with patch("app.core.auth._token_file_path", return_value=self.data_dir / "session_token"), \
             patch("builtins.print", side_effect=lambda *a, **kw: printed_lines.append(str(a[0]))):
            auth_mod._SESSION_TOKEN = None
            token = auth_mod.generate_and_store_token()

        self.assertTrue(any(line.startswith("CODE_OS_SESSION_TOKEN=") for line in printed_lines))
        matching = next(l for l in printed_lines if l.startswith("CODE_OS_SESSION_TOKEN="))
        emitted = matching.removeprefix("CODE_OS_SESSION_TOKEN=")
        self.assertEqual(emitted, token)


class TestAuthMiddleware(unittest.IsolatedAsyncioTestCase):
    """require_token middleware logic."""

    async def asyncSetUp(self):
        import app.core.auth as auth_mod
        # Plant a known token
        self._known_token = "a" * 64
        auth_mod._SESSION_TOKEN = self._known_token

    def _make_request(self, path="/api/files/read", method="GET", auth_header: str | None = None):
        from unittest.mock import MagicMock
        req = MagicMock()
        req.url.path = path
        req.method = method
        req.headers = {}
        if auth_header is not None:
            req.headers["Authorization"] = auth_header
        req.headers.get = lambda key, default="": req.headers.get(key, default) if isinstance(req.headers, dict) else default
        # Use a plain dict for headers.get
        headers_dict: dict[str, str] = {}
        if auth_header is not None:
            headers_dict["Authorization"] = auth_header
        headers_dict["upgrade"] = ""
        req.headers = MagicMock()
        req.headers.get = lambda key, default="": headers_dict.get(key, default)
        return req

    async def test_health_endpoint_passes_without_token(self):
        from app.core.auth import require_token
        from fastapi import Request

        req = MagicMock(spec=Request)
        req.url.path = "/health"
        req.headers = MagicMock()
        req.headers.get = lambda key, default="": ""

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        result = await require_token(req, call_next)
        call_next.assert_awaited_once()

    async def test_api_endpoint_without_token_raises_401(self):
        from app.core.auth import require_token
        from fastapi import Request

        req = MagicMock(spec=Request)
        req.url.path = "/api/files/read"
        req.headers = MagicMock()
        req.headers.get = lambda key, default="": ""

        call_next = AsyncMock()
        res = await require_token(req, call_next)
        self.assertEqual(res.status_code, 401)
        call_next.assert_not_awaited()

    async def test_api_endpoint_with_wrong_token_raises_401(self):
        from app.core.auth import require_token
        from fastapi import Request

        req = MagicMock(spec=Request)
        req.url.path = "/api/files/write"
        req.headers = MagicMock()
        req.headers.get = lambda key, default="": "Bearer " + "b" * 64 if key == "Authorization" else ""

        call_next = AsyncMock()
        res = await require_token(req, call_next)
        self.assertEqual(res.status_code, 401)
        call_next.assert_not_awaited()

    async def test_api_endpoint_with_correct_token_passes(self):
        from app.core.auth import require_token
        from fastapi import Request

        req = MagicMock(spec=Request)
        req.url.path = "/api/files/read"
        req.headers = MagicMock()
        req.headers.get = lambda key, default="": f"Bearer {'a' * 64}" if key == "Authorization" else ""

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        result = await require_token(req, call_next)
        call_next.assert_awaited_once()
        self.assertEqual(result.status_code, 200)

    async def test_websocket_upgrade_is_exempt(self):
        """WebSocket upgrades are NOT blanket-exempted from auth; middleware returns 401 (per FIX 2)."""
        from app.core.auth import require_token
        from fastapi import Request

        req = MagicMock(spec=Request)
        req.url.path = "/api/terminal/ws"
        req.headers = MagicMock()

        def _get(key, default=""):
            return "websocket" if key.lower() == "upgrade" else default

        req.headers.get = _get

        call_next = AsyncMock(return_value=MagicMock(status_code=101))
        result = await require_token(req, call_next)
        # After FIX 2: WS upgrades are NOT exempt from middleware; they get 401.
        self.assertEqual(result.status_code, 401)


class TestTerminalEnvAllowlist(unittest.TestCase):
    """_build_safe_environment must NOT include any secret variables."""

    def test_known_secret_vars_are_excluded(self):
        secret_vars = {
            "OPENAI_API_KEY": "sk-secret",
            "AWS_SECRET_ACCESS_KEY": "abc123",
            "GITHUB_TOKEN": "ghp_abc",
            "DATABASE_URL": "postgres://user:pw@host/db",
            "STRIPE_SECRET_KEY": "sk_live_abc",
            "ANTHROPIC_API_KEY": "ant-abc",
            "NPM_TOKEN": "npm-abc",
        }
        with patch.dict(os.environ, secret_vars):
            from app.features.terminal.service import _build_safe_environment
            safe = _build_safe_environment()
        for key in secret_vars:
            self.assertNotIn(key, safe, f"Secret variable {key!r} leaked into safe environment")

    def test_ssh_auth_sock_is_included(self):
        """SSH_AUTH_SOCK is operational (not a secret) and must pass through."""
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": "/tmp/ssh-agent.sock"}):
            from importlib import reload
            from app.features.terminal import service as svc
            safe = svc._build_safe_environment()
        self.assertIn("SSH_AUTH_SOCK", safe)
        self.assertEqual(safe["SSH_AUTH_SOCK"], "/tmp/ssh-agent.sock")

    def test_path_is_included(self):
        """PATH must always be present so commands are resolvable."""
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            from app.features.terminal.service import _build_safe_environment
            safe = _build_safe_environment()
        self.assertIn("PATH", safe)

    def test_term_is_always_set(self):
        """TERM=xterm-256color must always be injected regardless of host env."""
        env_without_term = {k: v for k, v in os.environ.items() if k != "TERM"}
        with patch.dict(os.environ, env_without_term, clear=True):
            from app.features.terminal.service import _build_safe_environment
            safe = _build_safe_environment()
        self.assertEqual(safe["TERM"], "xterm-256color")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ═══════════════════════════════════════════════════════
