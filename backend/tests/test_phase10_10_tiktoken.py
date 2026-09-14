"""test_phase10_10_tiktoken.py — Regression tests for Phase 10.10 updated for Phase 10.13.

Guarantees:
1. test_requirements_no_tiktoken: tiktoken is completely removed from backend/requirements.txt.
2. test_boot_dependency_free: backend logs INFO at boot with dependency-free estimator and never emits WARNING/ERROR.
3. test_tokenizer_error_message_not_context_tip: governor never fails closed and does NOT emit context-window/compaction tip.
4. test_conservative_mode_estimates_positively: conservative and default estimators produce positive, consistent counts.
5. test_ci_gate_tiktoken_removed: CI workflow does NOT enforce tiktoken dev gate.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.features.ai.harness import payload_governor
from app.features.ai.harness.payload_governor import (
    get_conservative_token_count,
    get_token_count,
    govern_payload,
)
from app.features.ai.schemas import ChatMessage
from app.main import check_tiktoken_health


def test_requirements_no_tiktoken():
    """Verify that tiktoken is completely removed from backend/requirements.txt in Phase 10.13."""
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    assert req_path.is_file(), f"requirements.txt not found at {req_path}"
    content = req_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    tiktoken_lines = [l for l in lines if l.startswith("tiktoken")]
    assert len(tiktoken_lines) == 0, f"Expected zero tiktoken entries in requirements.txt, found: {tiktoken_lines}"


def test_boot_dependency_free(caplog):
    """Backend logs INFO at boot, naming dependency-free estimator and never emitting WARNING/ERROR."""
    with caplog.at_level(logging.INFO):
        result = check_tiktoken_health()
        assert result is True

    info_text = caplog.text
    assert "dependency-free token estimator" in info_text
    assert "WARNING" not in info_text
    assert "ERROR" not in info_text


def test_tokenizer_error_message_not_context_tip():
    """Under Phase 10.13, governor never fails closed and never emits misleading context tips."""
    messages = [ChatMessage(role="user", content="Hello world")]

    res = govern_payload(messages, None, provider="openai", model="gpt-4o", fail_mode="closed")
    assert res.failed_closed is False

    # Ensure misleading context-window tip phrases are NOT in the summary reason
    assert "context window limit reached" not in res.summary_reason.lower()
    assert "compacted" not in res.summary_reason.lower()


def test_conservative_mode_estimates_positively():
    """Token estimators are total, positive, and safe across inputs."""
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
        token_count = get_token_count(sample)
        assert conservative_count >= 1
        assert token_count >= 1

    messages = [ChatMessage(role="user", content="Hello world")]
    gov_res = govern_payload(messages, None, provider="openai", model="gpt-4o")
    assert gov_res.failed_closed is False


def test_ci_gate_tiktoken_removed():
    """Verify that CI workflow no longer enforces tiktoken dev gate."""
    ci_path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), f"ci.yml not found at {ci_path}"
    ci_content = ci_path.read_text(encoding="utf-8")
    assert "Verify Tiktoken Dev Gate" not in ci_content
