import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.rate_limiter import rate_limiter, SimpleRateLimiter
from app.features.ai.providers.anthropic import AnthropicProvider
from app.features.ai.providers.ollama import OllamaProvider
from app.features.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.features.ai.catalog import get_model_metadata, PROVIDER_CATALOG
from app.features.ai.schemas import ChatMessage
from fastapi import HTTPException


class TestPrompt7ProviderAndRateLimiting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        rate_limiter.reset()

    def tearDown(self):
        rate_limiter.reset()

    async def test_anthropic_provider_headers_and_streaming(self):
        """Verify AnthropicProvider sends correct headers (x-api-key, anthropic-version) and parses SSE content_block_delta."""
        provider = AnthropicProvider(api_key="test-key-123")
        self.assertEqual(provider.headers["x-api-key"], "test-key-123")
        self.assertEqual(provider.headers["anthropic-version"], "2023-06-01")

        sse_lines = [
            'event: message_start\n',
            'data: {"type": "message_start", "message": {"id": "msg_123"}}\n',
            'event: content_block_delta\n',
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}}\n',
            'event: content_block_delta\n',
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "World!"}}\n',
        ]

        async def fake_aiter_lines():
            for line in sse_lines:
                yield line

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = fake_aiter_lines

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_stream_ctx

        with patch("httpx.AsyncClient", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_client), __aexit__=AsyncMock())):
            tokens = []
            async for token in provider.stream_chat(
                model="claude-3-5-sonnet-latest",
                messages=[ChatMessage(role="user", content="Hi")],
                temperature=0.7,
            ):
                tokens.append(token)

            self.assertEqual("".join(tokens), "Hello World!")

    async def test_ollama_stream_resilience_to_malformed_lines(self):
        """Verify Ollama provider skips malformed non-JSON lines without crashing the stream."""
        provider = OllamaProvider(base_url="http://127.0.0.1:11434")

        lines = [
            '{"message": {"content": "First "}}',
            'MALFORMED_NON_JSON_LINE_CORRUPTED',
            '{"message": {"content": "Second"}}',
        ]

        async def fake_aiter_lines():
            for line in lines:
                yield line

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = fake_aiter_lines

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_stream_ctx

        with patch("httpx.AsyncClient", return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_client), __aexit__=AsyncMock())):
            tokens = []
            async for token in provider.stream_chat(
                model="llama3",
                messages=[ChatMessage(role="user", content="Hi")],
                temperature=0.2,
            ):
                tokens.append(token)

            self.assertEqual("".join(tokens), "First Second")

    def test_rate_limiting_thresholds(self):
        """Rate limiter is now tracking-only — allows requests even past the limit, never raises HTTP 429."""
        limiter = SimpleRateLimiter()

        # 5 requests per 10 seconds limit — all succeed
        for i in range(5):
            result = limiter.check("test_route", max_requests=5, window_seconds=10.0)
            self.assertTrue(result["allowed"])

        # 6th request: still allowed (non-blocking), remaining stays at 0
        result = limiter.check("test_route", max_requests=5, window_seconds=10.0)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(result["limit"], 5)

    def test_provider_catalog_metadata(self):
        """Verify metadata catalog retrieves model capabilities and pricing."""
        gpt4o = get_model_metadata("openai", "gpt-4o")
        self.assertIsNotNone(gpt4o)
        self.assertEqual(gpt4o.context_window, 128000)

        claude = get_model_metadata("anthropic", "claude-3-5-sonnet-latest")
        self.assertIsNotNone(claude)
        self.assertEqual(claude.context_window, 200000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
