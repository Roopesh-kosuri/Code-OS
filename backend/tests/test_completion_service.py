"""
Unit tests for the Inline Code Completion Service (completion_service.py).
Tests context budget capping, output cleaning/trimming, and silent failover.
"""
import pytest
from app.features.ai.completion_service import (
    _cap_context,
    _clean_completion_text,
    generate_inline_completion,
    CompletionRequest,
    MAX_PREFIX_CHARS,
    MAX_PREFIX_LINES,
    MAX_SUFFIX_CHARS,
    MAX_SUFFIX_LINES,
)


def test_cap_context_small():
    """Small prefix and suffix pass through unchanged."""
    p = "def add(a, b):\n"
    s = "\n    return a + b"
    cp, cs = _cap_context(p, s)
    assert cp == p
    assert cs == s


def test_cap_context_lines_and_chars():
    """Large prefix/suffix are capped to line count and character budget."""
    # 200 lines prefix
    large_prefix = "\n".join([f"line_{i} = {i}" for i in range(200)])
    # 100 lines suffix
    large_suffix = "\n".join([f"suffix_{i} = {i}" for i in range(100)])

    cp, cs = _cap_context(large_prefix, large_suffix)

    assert len(cp.split("\n")) <= MAX_PREFIX_LINES
    assert len(cp) <= MAX_PREFIX_CHARS
    assert len(cs.split("\n")) <= MAX_SUFFIX_LINES
    assert len(cs) <= MAX_SUFFIX_CHARS


def test_clean_completion_text_markdown_fences():
    """Markdown code fences are stripped from raw completion output."""
    raw = "```python\n    return a + b\n```"
    cleaned = _clean_completion_text(raw, "")
    assert "```" not in cleaned
    assert "return a + b" in cleaned


def test_clean_completion_text_fim_tokens():
    """Special FIM marker tokens are stripped."""
    raw = "<|cursor_completion|>    x = 10\n    y = 20<|end_of_text|>"
    cleaned = _clean_completion_text(raw, "")
    assert "<|" not in cleaned
    assert "x = 10" in cleaned


def test_clean_completion_text_suffix_overlap_trim():
    """Trailing duplicate line overlapping with suffix start is trimmed."""
    raw = "    total = a + b\n    return total"
    suffix = "    return total\n"
    cleaned = _clean_completion_text(raw, suffix)
    assert cleaned.strip() == "total = a + b"


@pytest.mark.asyncio
async def test_generate_inline_completion_empty_context():
    """Empty prefix and suffix return empty completion with 0 latency."""
    req = CompletionRequest(prefix="", suffix="")
    res = await generate_inline_completion(req)
    assert res.completion == ""
    assert res.latency_ms == 0.0


@pytest.mark.asyncio
async def test_generate_inline_completion_silent_failover():
    """Even if provider is unavailable or fails, returns empty completion without raising."""
    req = CompletionRequest(
        prefix="def hello():\n",
        suffix="",
        language="python",
    )
    # Must not throw
    res = await generate_inline_completion(req)
    assert isinstance(res.completion, str)
    assert isinstance(res.latency_ms, float)

# ===================================================================
# FIX 4: P0-4 -- asyncio import: verify asyncio is present and completion works
# ===================================================================

@pytest.mark.asyncio
async def test_completion_asyncio_import_present():
    """asyncio must be importable from completion_service — guards NameError regression."""
    import app.features.ai.completion_service as svc
    import asyncio as _asyncio
    # If asyncio is importable from the module, this test passes.
    # The module must have imported asyncio (otherwise wait_for silently returns empty).
    assert hasattr(svc, "asyncio"), (
        "asyncio is NOT imported in completion_service.py! "
        "asyncio.wait_for will NameError and completion silently returns empty string."
    )


@pytest.mark.asyncio
async def test_completion_returns_non_empty_on_mocked_provider():
    """generate_inline_completion must return non-empty string when provider yields tokens."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.features.ai.completion_service import generate_inline_completion, CompletionRequest

    # Mock provider instance
    mock_provider = MagicMock()

    async def _fake_stream_chat(**kwargs):
        for chunk in ["def ", "hello", "():"]:
            yield chunk

    mock_provider.stream_chat = _fake_stream_chat

    req = CompletionRequest(
        file_path="test.py",
        prefix="# write a function\n",
        suffix="\n    pass",
        language="python",
    )

    # Patch _resolve_fast_completion_provider to return our mock directly
    with patch(
        "app.features.ai.completion_service._resolve_fast_completion_provider",
        new=AsyncMock(return_value=(mock_provider, "test-model"))
    ):
        res = await generate_inline_completion(req)

    assert isinstance(res.completion, str)
    assert len(res.completion) > 0, (
        f"Completion was empty. asyncio import may be missing. Got: {res!r}"
    )


@pytest.mark.asyncio
async def test_completion_returns_non_empty():
    """Alias matching Phase 4 specification for completion service."""
    await test_completion_returns_non_empty_on_mocked_provider()
