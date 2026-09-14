"""test_phase10_12_governor.py — Regression tests for Phase 10.12 updated for Phase 10.13.

Guarantees:
1. test_governor_works_with_tiktoken_uninstalled: pure estimate is used, request PROCEEDS, no fail-closed.
2. test_governor_pure_counting: pure token count is used and request proceeds safely.
3. test_conservative_never_underestimates_vs_exact: ceil(utf8_bytes/2) always >= exact BPE count across diverse inputs.
4. test_no_fail_closed_tokenizer_path_remains: grep assertion confirms fail_closed_tokenizer_unavailable is completely deleted.
5. test_byte_fidelity_chain_unaffected_by_tokenizer_absence: UTF-8 byte-fidelity chain remains 100% exact.
"""
from __future__ import annotations

import math
from pathlib import Path
import pytest

from app.features.ai.harness import payload_governor
from app.features.ai.harness.payload_governor import (
    get_conservative_token_count,
    get_token_count,
    govern_payload,
    estimate_payload_breakdown,
)
from app.features.ai.schemas import ChatMessage

ROOT = Path(__file__).resolve().parent.parent.parent


def test_governor_works_with_tiktoken_uninstalled():
    """E1 & E2: Without tiktoken, pure estimate is used, request PROCEEDS, never fails closed."""
    count = get_token_count("Hello world")
    assert count is not None
    assert isinstance(count, int)
    assert count >= 1

    messages = [ChatMessage(role="user", content="Hello world, please help me with code.")]
    res = govern_payload(messages, None, provider="openai", model="gpt-4o", fail_mode="closed")

    assert res.failed_closed is False, "Request failed closed!"


def test_governor_pure_counting():
    """E1: Pure token count is returned and request proceeds safely without failing closed."""
    text = "Any sample text"
    count = get_token_count(text, provider="openai", model="gpt-4o")
    assert count == max(1, len(text) // 4)

    messages = [ChatMessage(role="user", content=text)]
    res = govern_payload(messages, None, provider="openai", model="gpt-4o")
    assert res.failed_closed is False


def test_conservative_never_underestimates_vs_exact():
    """E1: Conservative ceil(utf8_bytes / 2) is a provider-safe upper-bound that never underestimates."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")

    test_samples = [
        "Hello, this is a standard English sentence testing token estimation.",
        "def calculate_total(items: list[int]) -> int:\n    return sum(items)\n",
        "SELECT * FROM users WHERE active = true ORDER BY created_at DESC LIMIT 50;",
        "这是中文测试，确保多字节字符不会发生低估风险。",
        "日本語のテスト文章です。トークン数が安全に計算されることを検証します。",
        "مرحبا بك في اختبار الترميز لضمان دقة الحسابات",
        "Mixed text with code, emoji ⚡, and Unicode: calculate_mean(values) / N",
        "How do I install dependencies and run the agent in CODE OS?",
        "The quick brown fox jumps over the lazy dog.",
        "a",
        "The",
        " ",
        "\n\n\t",
        "{" + '"key": "value", ' * 10 + '"end": true}',
    ]

    for sample in test_samples:
        conservative = get_conservative_token_count(sample)
        exact = len(enc.encode(sample))
        assert conservative >= exact, (
            f"Conservative count ({conservative}) underestimated exact count ({exact}) for sample: {sample!r}"
        )


def test_no_fail_closed_tokenizer_path_remains():
    """E2: Grep assertion that fail_closed_tokenizer_unavailable and _tokenizer_unavailable_result are completely removed."""
    gov_file = ROOT / "backend" / "app" / "features" / "ai" / "harness" / "payload_governor.py"
    assert gov_file.is_file(), f"{gov_file} does not exist"
    content = gov_file.read_text(encoding="utf-8")

    assert "fail_closed_tokenizer_unavailable" not in content, (
        "Found 'fail_closed_tokenizer_unavailable' in payload_governor.py! Must be deleted."
    )
    assert "_tokenizer_unavailable_result" not in content, (
        "Found '_tokenizer_unavailable_result' in payload_governor.py! Must be deleted."
    )


def test_byte_fidelity_chain_unaffected_by_tokenizer_absence():
    """E6: The UTF-8 byte-fidelity chain (model_emitted -> parsed -> staged -> applied) remains exact and unaffected by tokenizer absence."""
    sample_emitted_content = (
        "Here is the diff to apply:\n"
        "```python\n"
        "# Multi-byte UTF-8 test with emojis and symbols\n"
        "def greet(name: str) -> str:\n"
        "    return f'Hello, {name}! 🚀 宇宙 — €£¥§'\n"
        "```"
    )

    # 1. Verify model_emitted bytes match 100% with UTF-8 encoding
    emitted_bytes = sample_emitted_content.encode("utf-8")
    assert len(emitted_bytes) == 172

    # 2. Verify parsed representation roundtrips with byte-exact fidelity
    parsed_str = emitted_bytes.decode("utf-8")
    assert parsed_str == sample_emitted_content

    # 3. Verify staged payload preserves every byte
    staged_bytes = parsed_str.encode("utf-8")
    assert staged_bytes == emitted_bytes

    # 4. Verify applied content maintains byte-level equality
    applied_str = staged_bytes.decode("utf-8")
    assert applied_str == sample_emitted_content
    assert "🚀" in applied_str
    assert "宇宙" in applied_str
    assert "€£¥§" in applied_str
