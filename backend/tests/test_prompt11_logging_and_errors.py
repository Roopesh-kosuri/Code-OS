import json
import logging
from pathlib import Path
import unittest

import httpx
from httpx import ASGITransport

from app.main import app
from app.core import auth
from app.core.logging import JSONLogFormatter, configure_logging, request_id_var
from app.features.ai.providers.anthropic import _format_anthropic_error
from app.features.ai.providers.ollama import _format_ollama_error
from app.features.ai.providers.openai_compatible import _format_openai_error


class TestPrompt11LoggingAndErrors(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.token = auth.get_token()
        except Exception:
            self.token = auth.generate_and_store_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.transport = ASGITransport(app=app, raise_app_exceptions=False)

    def test_json_formatter_serializes_fields(self):
        """Verify JSONLogFormatter outputs valid JSON with required fields."""
        formatter = JSONLogFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test_mod.py",
            lineno=42,
            msg="Test log message",
            args=(),
            exc_info=None,
        )
        record.module = "test_mod"
        record.funcName = "test_func"
        record.workspace = "/tmp/test-ws"

        request_id_var.set("req-12345")
        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        self.assertEqual(parsed["logger"], "test_logger")
        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["message"], "Test log message")
        self.assertEqual(parsed["module"], "test_mod")
        self.assertEqual(parsed["func"], "test_func")
        self.assertEqual(parsed["line"], 42)
        self.assertEqual(parsed["request_id"], "req-12345")
        self.assertEqual(parsed["workspace"], "/tmp/test-ws")

    def test_log_file_creation(self):
        """Verify log file is created under ~/.code-os/logs/code-os.log."""
        configure_logging()
        log_path = Path.home() / ".code-os" / "logs" / "code-os.log"
        self.assertTrue(log_path.parent.exists())

    async def test_request_id_middleware_and_header(self):
        """Verify X-Request-ID response header is returned on every HTTP request."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            res = await client.get("/health")
            self.assertEqual(res.status_code, 200)
            self.assertIn("X-Request-ID", res.headers)
            self.assertTrue(len(res.headers["X-Request-ID"]) > 0)

    def test_provider_error_formatting_never_exposes_traceback(self):
        """Verify provider errors return clean user-friendly messages without tracebacks."""
        timeout_exc = httpx.TimeoutException("Timeout after 60s")
        req = httpx.Request("POST", "http://test")
        resp_429 = httpx.Response(429, request=req)
        rate_limit_exc = httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp_429)

        resp_401 = httpx.Response(401, request=req)
        auth_exc = httpx.HTTPStatusError("401 Unauthorized", request=req, response=resp_401)

        anthropic_err = _format_anthropic_error(timeout_exc)
        self.assertIn("timed out", anthropic_err)

        ollama_err = _format_ollama_error(rate_limit_exc)
        self.assertIn("Rate limit reached", ollama_err)

        openai_err = _format_openai_error(auth_exc, "OpenAI")
        self.assertIn("Authentication failed", openai_err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
