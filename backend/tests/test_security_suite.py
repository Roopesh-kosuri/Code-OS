import os
import sys
import unittest
from pathlib import Path

import httpx
from httpx import ASGITransport

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.core import auth
from app.features.terminal.service import _sanitize_env


class TestSecuritySuite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.known_token = auth.get_token()
        except Exception:
            self.known_token = auth.generate_and_store_token()
        auth._SESSION_TOKEN = self.known_token
        self.headers = {"Authorization": f"Bearer {self.known_token}"}
        self.transport = ASGITransport(app=app, raise_app_exceptions=False)



    def test_env_sanitizer_strips_aws_secret_and_keeps_path_ssh(self):
        """Verify env sanitizer removes secrets like AWS_SECRET_ACCESS_KEY but preserves PATH and SSH_AGENT_PID."""
        raw_env = {
            "PATH": "/usr/bin:/bin",
            "SSH_AGENT_PID": "1234",
            "AWS_SECRET_ACCESS_KEY": "supersecretkey123",
            "API_SECRET_TOKEN": "mysecrettoken",
            "TERM": "xterm-256color",
        }
        sanitized = _sanitize_env(raw_env)
        self.assertIn("PATH", sanitized)
        self.assertIn("SSH_AGENT_PID", sanitized)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", sanitized)
        self.assertNotIn("API_SECRET_TOKEN", sanitized)

    async def test_auth_token_enforcement(self):
        """Verify 401 on missing or wrong token, and success on exempt endpoint."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            # 1. Without token -> 401
            res = await client.post("/api/ai/chat/stream", json={"model": "llama3", "messages": []})
            self.assertEqual(res.status_code, 401)

            # 2. With wrong token -> 401
            res = await client.post(
                "/api/ai/chat/stream",
                json={"model": "llama3", "messages": []},
                headers={"Authorization": "Bearer invalid_wrong_token_999"},
            )
            self.assertEqual(res.status_code, 401)

            # 3. Health endpoint exempt -> 200
            res = await client.get("/health")
            self.assertEqual(res.status_code, 200)

    async def test_tilde_path_rejected(self):
        """Verify tilde paths (~) are rejected with HTTP 400."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test", headers=self.headers) as client:
            res = await client.post(
                "/api/ai/context",
                json={"workspace": "~/my-project", "active_path": "~/my-project/main.py"},
            )
            self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
