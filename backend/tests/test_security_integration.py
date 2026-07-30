import os
import tempfile
import unittest
from pathlib import Path

import httpx
from httpx import ASGITransport

from fastapi import HTTPException
from app.main import app
from app.core import auth
from app.core.paths import ensure_within_workspace, normalize_path
from app.features.terminal.service import _sanitize_env

from app.features.workspaces.trust_service import set_workspace_trust, get_workspace_trust



class TestSecurityIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.token = auth.get_token()
        except Exception:
            self.token = auth.generate_and_store_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.transport = ASGITransport(app=app, raise_app_exceptions=False)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.ws_dir = str(Path(self.tmp_dir.name).resolve())
        await set_workspace_trust(self.ws_dir, trusted=True)

    async def asyncTearDown(self):
        self.tmp_dir.cleanup()

    async def test_etc_passwd_reading_blocked(self):
        """Verify reading /etc/passwd outside workspace or via tilde traversal is blocked."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test", headers=self.headers) as client:
            # 1. Tilde workspace traversal -> 400
            res = await client.post(
                "/api/ai/context",
                json={"workspace": "~/etc", "active_path": "/etc/passwd"},
            )
            self.assertEqual(res.status_code, 400)

            # 2. Path outside workspace -> active_file is None
            res = await client.post(
                "/api/ai/context",
                json={"workspace": self.ws_dir, "active_path": "/etc/passwd"},
            )
            self.assertEqual(res.status_code, 200)
            self.assertIsNone(res.json().get("active_file"))


    async def test_ssh_id_rsa_attachment_blocked(self):
        """Verify attached path pointing outside workspace is blocked in context/attachments."""
        ssh_path = str(Path.home() / ".ssh" / "id_rsa")
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test", headers=self.headers) as client:
            res = await client.post(
                "/api/ai/context",
                json={
                    "workspace": self.ws_dir,
                    "active_path": ssh_path,
                },
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            # Active file should NOT be returned because it's outside workspace
            self.assertIsNone(data.get("active_file"))

    async def test_api_without_token_returns_401(self):
        """Verify API calls without Bearer token return HTTP 401."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            res = await client.post("/api/files/write", json={"workspace": self.ws_dir, "path": "a.txt", "content": "x"})
            self.assertEqual(res.status_code, 401)

    async def test_api_with_wrong_token_returns_401(self):
        """Verify API calls with wrong Bearer token return HTTP 401."""
        bad_headers = {"Authorization": "Bearer invalid-wrong-token-999"}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test", headers=bad_headers) as client:
            res = await client.post("/api/files/write", json={"workspace": self.ws_dir, "path": "a.txt", "content": "x"})
            self.assertEqual(res.status_code, 401)

    def test_env_sanitizer_security(self):
        """Verify env sanitizer removes secrets while keeping PATH, SSH_AGENT_PID, and TERM."""
        raw = {
            "PATH": "/usr/bin:/bin",
            "SSH_AGENT_PID": "5678",
            "TERM": "xterm-256color",
            "AWS_SECRET_ACCESS_KEY": "AKIA1234567890",
            "DATABASE_PASSWORD": "supersecretpassword",
            "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx",
        }
        clean = _sanitize_env(raw)
        self.assertIn("PATH", clean)
        self.assertIn("SSH_AGENT_PID", clean)
        self.assertIn("TERM", clean)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", clean)
        self.assertNotIn("DATABASE_PASSWORD", clean)
        self.assertNotIn("GITHUB_TOKEN", clean)

    def test_tilde_traversal_blocked(self):
        """Verify normalize_path raises HTTP 400 on tilde traversal (~)."""
        with self.assertRaises(Exception) as ctx:
            normalize_path("~/secret.txt")
        self.assertIn("400", str(ctx.exception))

    def test_symlink_escape_blocked(self):
        """Verify ensure_within_workspace blocks path traversal escaping workspace root."""
        with self.assertRaises(HTTPException):
            ensure_within_workspace(self.ws_dir, f"{self.ws_dir}/../../etc/passwd")


    async def test_terminal_session_untrusted_cwd_blocked(self):
        """Verify creating terminal session in untrusted workspace returns 403."""
        untrusted_dir = tempfile.mkdtemp()
        try:
            await set_workspace_trust(untrusted_dir, trusted=False)
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test", headers=self.headers) as client:
                res = await client.post(
                    "/api/terminal/sessions",
                    json={"cwd": untrusted_dir, "shell": "powershell"},
                )
                self.assertEqual(res.status_code, 403)
        finally:
            if os.path.exists(untrusted_dir):
                os.rmdir(untrusted_dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
