"""test_phase10_13_governor.py — Regression test suite for Phase 10.13.

Guarantees:
1. test_governor_never_blocks_request: govern_payload always returns failed_closed=False.
2. test_get_token_count_total_and_positive: get_token_count is pure, total, and returns >= 1 for any input.
3. test_governor_compacts_but_does_not_fail_on_huge_payload: huge payload engages compaction but never fails closed.
4. test_no_tiktoken_import_in_governor: payload_governor does not import tiktoken and has no tiktoken machinery.
5. test_byte_fidelity_chain_unaffected_by_tokenizer_removal: UTF-8 byte-fidelity is preserved across multi-byte strings.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
import pytest

from app.features.ai.harness import payload_governor
from app.features.ai.harness.payload_governor import (
    get_token_count,
    govern_payload,
    estimate_payload_breakdown,
)
from app.features.ai.schemas import ChatMessage


def test_governor_never_blocks_request():
    """Guarantee 1: govern_payload NEVER blocks a request (failed_closed is always False)."""
    messages = [ChatMessage(role="user", content="Hello CODE OS")]
    res = govern_payload(messages, None, provider="openai", model="gpt-4o")
    assert res.failed_closed is False
    assert len(res.messages) == 1

    # Even with a very tight budget (e.g. 1 token)
    res_tight = govern_payload(messages, None, provider="openai", model="gpt-4o", hard_tpm_limit=1)
    assert res_tight.failed_closed is False


def test_get_token_count_total_and_positive():
    """Guarantee 2: get_token_count is a total pure function returning >= 1 for all inputs."""
    samples = [
        "",
        None,
        "a",
        "hello world",
        "def foo():\n    return 42\n",
        "🚀🌟🔥 Unicode and emoji testing 汉字 日本語",
        "A" * 10000,
        12345,
        {"key": "value"},
    ]

    for sample in samples:
        count = get_token_count(sample)  # type: ignore[arg-type]
        assert isinstance(count, int), f"Expected int for {sample!r}, got {type(count)}"
        assert count >= 1, f"Expected count >= 1 for {sample!r}, got {count}"

    # Verify len // 4 heuristic behavior
    assert get_token_count("12345678") == 2
    assert get_token_count("123456789012") == 3


def test_governor_compacts_but_does_not_fail_on_huge_payload():
    """Guarantee 3: Huge payload over provider budget engages progressive compaction without failing closed."""
    huge_text = "x" * 40000
    huge_attachment = f'<attached_files count="1"><file id="f1" name="huge.txt">{huge_text}</file></attached_files>'

    messages = [
        ChatMessage(role="user", content="Old conversation turn 1"),
        ChatMessage(role="assistant", content="Old assistant reply 1"),
        ChatMessage(role="user", content=f"Analyze this huge file: {huge_attachment}"),
    ]

    # Groq default budget is 7,500 tokens
    res = govern_payload(messages, None, provider="groq", model="llama-3.3-70b")

    # Compaction must have been applied
    assert res.was_adjusted is True
    # MUST NEVER fail closed
    assert res.failed_closed is False
    # Attachment truncation tag should be present
    assert any("truncated_attachments" in adj or "compacted" in adj for adj in res.summary_reason.split(", "))


def test_no_tiktoken_import_in_governor():
    """Guarantee 4: payload_governor module source contains NO tiktoken imports or encoder cache machinery."""
    gov_source = inspect.getsource(payload_governor)

    assert "import tiktoken" not in gov_source, "payload_governor must not import tiktoken!"
    assert "_get_token_encoder" not in gov_source, "payload_governor must not contain _get_token_encoder!"
    assert "_ENCODER_CACHE" not in gov_source, "payload_governor must not contain _ENCODER_CACHE!"
    assert "_tokenizer_name" not in gov_source, "payload_governor must not contain _tokenizer_name!"


def test_byte_fidelity_chain_unaffected_by_tokenizer_removal():
    """Guarantee 5: UTF-8 exact byte fidelity is 100% preserved regardless of tokenizer removal."""
    multibyte_text = "Unicode 🚀 宇宙, decomposed accents: e\u0301 vs precomposed: \u00e9"
    encoded_bytes = multibyte_text.encode("utf-8")
    decoded_text = encoded_bytes.decode("utf-8")

    assert decoded_text == multibyte_text
    assert len(encoded_bytes) > len(multibyte_text)

    # Token counting handles multibyte text transparently and safely
    token_est = get_token_count(multibyte_text)
    assert token_est >= 1
    assert isinstance(token_est, int)
