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
