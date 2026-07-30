import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.rate_limiter import SimpleRateLimiter
from app.features.ai.providers.anthropic import AnthropicProvider
from app.features.ai.providers.ollama import OllamaProvider
from app.features.ai.schemas import ChatMessage
from fastapi import HTTPException


class TestProviderSuite(unittest.IsolatedAsyncioTestCase):
    async def test_anthropic_headers_and_stream(self):
        provider = AnthropicProvider(api_key="test-key")
        self.assertEqual(provider.headers["x-api-key"], "test-key")

        lines = [
            'data: {"type": "content_block_delta", "delta": {"text": "hello"}}\n',
            'data: {"type": "content_block_delta", "delta": {"text": " world"}}\n',
        ]

        async def fake_lines():
            for l in lines:
                yield l

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = fake_lines

        mock_ctx = MagicMock(__aenter__=AsyncMock(return_value=mock_resp), __aexit__=AsyncMock())
        mock_client = MagicMock(stream=MagicMock(return_value=mock_ctx))

        with patch("httpx.AsyncClient", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_client), __aexit__=AsyncMock())):
            tokens = []
            async for token in provider.stream_chat("claude-3-5-sonnet-latest", [ChatMessage(role="user", content="hi")], 0.2):
                tokens.append(token)
            self.assertEqual("".join(tokens), "hello world")

    async def test_ollama_stream_skips_malformed_lines(self):
        provider = OllamaProvider(base_url="http://127.0.0.1:11434")

        lines = [
            '{"message": {"content": "ok"}}',
            'INVALID_JSON_CORRUPT',
            '{"message": {"content": " done"}}',
        ]

        async def fake_lines():
            for l in lines:
                yield l

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = fake_lines

        mock_ctx = MagicMock(__aenter__=AsyncMock(return_value=mock_resp), __aexit__=AsyncMock())
        mock_client = MagicMock(stream=MagicMock(return_value=mock_ctx))

        with patch("httpx.AsyncClient", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_client), __aexit__=AsyncMock())):
            tokens = []
            async for token in provider.stream_chat("llama3", [ChatMessage(role="user", content="hi")], 0.2):
                tokens.append(token)
            self.assertEqual("".join(tokens), "ok done")

    def test_rate_limiter_throws_429(self):
        limiter = SimpleRateLimiter()
        for _ in range(3):
            limiter.check("key", 3, 60.0)

        with self.assertRaises(HTTPException) as ctx:
            limiter.check("key", 3, 60.0)
        self.assertEqual(ctx.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main(verbosity=2)
