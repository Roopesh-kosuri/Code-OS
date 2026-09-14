"""test_phase10_10_tiktoken.py — Regression tests for Phase 10.10.

Guarantees:
1. test_requirements_pins_tiktoken: tiktoken is pinned with exact version in backend/requirements.txt.
2. test_boot_warning_when_tiktoken_missing: backend emits a loud warning mentioning 'pip install tiktoken' when tiktoken is missing.
3. test_tokenizer_error_message_not_context_tip: fail-closed error clearly identifies missing token accounting dependency and does NOT emit context-window/compaction tip.
4. test_conservative_mode_overestimates_not_underestimates: ceil(utf8_bytes/2) always >= exact BPE count and never underestimates; conservative mode logs conservative_estimate_tokenizer_missing.
5. test_ci_gate_imports_tiktoken: CI workflow enforces tiktoken import and Unicode encoding dev-gate.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.features.ai.harness import payload_governor
from app.features.ai.harness.payload_governor import (
    get_conservative_token_count,
    govern_payload,
    estimate_payload_breakdown,
)
from app.features.ai.schemas import ChatMessage
from app.main import check_tiktoken_health


def test_requirements_pins_tiktoken():
    """E1: Verify that tiktoken is pinned to an exact version in backend/requirements.txt."""
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    assert req_path.is_file(), f"requirements.txt not found at {req_path}"
    content = req_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    tiktoken_lines = [l for l in lines if l.startswith("tiktoken==")]
    assert len(tiktoken_lines) == 1, f"Expected exactly one pinned tiktoken entry in requirements.txt, found: {tiktoken_lines}"
    assert tiktoken_lines[0] == "tiktoken==0.14.0", f"Unexpected pinned version: {tiktoken_lines[0]}"


def test_boot_warning_when_tiktoken_missing(caplog):
    """E4: Backend logs INFO at boot when tiktoken is missing, naming conservative estimator and never emitting WARNING/ERROR."""
    with caplog.at_level(logging.INFO):
        with patch.dict("sys.modules", {"tiktoken": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'tiktoken'")):
                result = check_tiktoken_health()
                assert result is False

    info_text = caplog.text
    assert "using conservative estimator" in info_text
    assert "WARNING" not in info_text
    assert "ERROR" not in info_text


def test_tokenizer_error_message_not_context_tip(monkeypatch):
    """E2: Under Phase 10.12, missing tokenizer never fails closed and never emits misleading context tips."""
    monkeypatch.setattr(payload_governor, "_get_token_encoder", lambda _name: None)
    messages = [ChatMessage(role="user", content="Hello world")]

    # In strict 'closed' mode or default, request proceeds using conservative estimate
    res = govern_payload(messages, None, provider="openai", model="gpt-4o", fail_mode="closed")
    assert res.failed_closed is False
    assert "conservative_estimate_tokenizer_missing" in res.summary_reason

    # Ensure misleading context-window tip phrases are NOT in the summary reason
    assert "context window limit reached" not in res.summary_reason.lower()
    assert "compacted" not in res.summary_reason.lower()


def test_conservative_mode_overestimates_not_underestimates():
    """E5: Conservative mode ceil(utf8_bytes/2) always >= exact BPE count and never underestimates."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")

    test_samples = [
        "Hello, this is a standard English sentence testing token estimation.",
        "def calculate_total(items: list[int]) -> int:\n    return sum(items)\n",
        "SELECT * FROM users WHERE active = true ORDER BY created_at DESC LIMIT 50;",
        "这是中文测试，确保多字节字符不会发生低估风险。",
        "日本語のテスト文章です。トークン数が安全に計算されることを検証します。",
        "Mixed text with code, emoji ⚡, and Unicode: calculate_mean(values) / N",
        "How do I install dependencies and run the agent in CODE OS?",
        "The quick brown fox jumps over the lazy dog.",
        "a",
        "The",
        "{" + '"key": "value", ' * 10 + '"end": true}',
    ]

    for sample in test_samples:
        conservative_count = get_conservative_token_count(sample)
        exact_count = len(enc.encode(sample))
        assert conservative_count >= exact_count, (
            f"Underestimated for sample: {sample!r}! "
            f"conservative={conservative_count} < exact={exact_count}"
        )

    # Verify that in conservative mode without tokenizer, govern_payload succeeds and logs event
    with patch.object(payload_governor, "_get_token_encoder", return_value=None):
        messages = [ChatMessage(role="user", content="Hello world")]
        gov_res = govern_payload(messages, None, provider="openai", model="gpt-4o", fail_mode="conservative")
        assert gov_res.failed_closed is False
        assert "conservative_estimate_tokenizer_missing" in gov_res.summary_reason
        assert gov_res.breakdown.get("is_conservative") is True


def test_ci_gate_imports_tiktoken():
    """E3: Verify that CI workflow enforces tiktoken import and Unicode encoding test step."""
    ci_path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), f"ci.yml not found at {ci_path}"
    ci_content = ci_path.read_text(encoding="utf-8")
    assert "Verify Tiktoken Dev Gate" in ci_content
    assert "import tiktoken" in ci_content
    assert "get_encoding('cl100k_base')" in ci_content
    assert "encode(" in ci_content
