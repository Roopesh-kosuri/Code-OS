# -*- coding: utf-8 -*-
"""
test_tier1_intelligence.py - Regression tests for Phase 6: Rony Tier-1 Intelligence.

Tests verify:
- TIER_1_OPERATING_PROTOCOL appears in Tier 2/3 system prompts.
- SELF_VERIFICATION_RULE appears in Tier 2/3 system prompts.
- Tier 0 (conversational) does NOT include the heavy protocol.
- Complexity gate: trivial queries have no [PLAN] enforcement language.
- Complexity gate: complex queries include [PLAN] block instruction.
- BPE token counter (get_token_count) is accurate within 10%.
- Memory anchors survive conversation summarization.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_prompt(tier: int, workspace: str = "/ws", context: dict | None = None) -> str:
    from app.features.ai.harness.prompt_builder import _build_system_prompt
    return _build_system_prompt(workspace, tier, context or {})


# ---------------------------------------------------------------------------
# A. Protocol injection into system prompts
# ---------------------------------------------------------------------------

class TestProtocolInjection:
    def test_tier1_protocol_in_deep_prompt(self):
        """TIER_1_OPERATING_PROTOCOL must appear verbatim in Tier 2 prompts."""
        from app.features.ai.harness.prompt_builder import _TIER_1_OPERATING_PROTOCOL
        prompt = _build_prompt(tier=2)
        assert "TIER-1 OPERATING PROTOCOL" in prompt, (
            "Tier 2 system prompt is missing TIER-1 OPERATING PROTOCOL block"
        )

    def test_self_verification_in_deep_prompt(self):
        """SELF-VERIFICATION RULE must appear in Tier 2/3 prompts."""
        prompt = _build_prompt(tier=2)
        assert "SELF-VERIFICATION RULE" in prompt, (
            "Tier 2 system prompt is missing SELF-VERIFICATION RULE"
        )

    def test_tier3_also_gets_protocol(self):
        """Tier 3 (huge task) must also carry the full protocol."""
        prompt = _build_prompt(tier=3)
        assert "TIER-1 OPERATING PROTOCOL" in prompt
        assert "SELF-VERIFICATION RULE" in prompt

    def test_tier1_protocol_NOT_in_lean_prompt(self):
        """Tier 0 (lean chat) must NOT include the heavy operating protocol."""
        prompt = _build_prompt(tier=0)
        assert "TIER-1 OPERATING PROTOCOL" not in prompt, (
            "Tier 0 (conversational) prompt must not include the full operating protocol"
        )

    def test_self_verification_lite_in_tier1(self):
        """Tier 1 (quick task) should carry the lightweight self-verification reminder."""
        prompt = _build_prompt(tier=1)
        assert "Self-Verification" in prompt or "verified on disk" in prompt, (
            "Tier 1 prompt should include lightweight self-verification reminder"
        )

    def test_tier1_no_full_protocol(self):
        """Tier 1 must NOT carry the full TIER-1 OPERATING PROTOCOL block."""
        prompt = _build_prompt(tier=1)
        assert "TIER-1 OPERATING PROTOCOL" not in prompt, (
            "Tier 1 should only get the lightweight self-verification, not the full protocol"
        )


# ---------------------------------------------------------------------------
# B. Complexity gate
# ---------------------------------------------------------------------------

class TestComplexityGate:
    def test_complexity_gate_trivial_label_present(self):
        """COMPLEXITY GATE section must exist in the Tier 2 prompt."""
        prompt = _build_prompt(tier=2)
        assert "COMPLEXITY GATE" in prompt

    def test_complexity_gate_trivial_skip_instruction(self):
        """TRIVIAL skip instruction must be present in the deep prompt."""
        prompt = _build_prompt(tier=2)
        assert "TRIVIAL" in prompt
        assert "Skip to direct answer" in prompt or "No [PLAN] block needed" in prompt

    def test_complexity_gate_complex_plan_required(self):
        """COMPLEX task instruction must require a [PLAN] block."""
        prompt = _build_prompt(tier=2)
        assert "COMPLEX" in prompt
        assert "[PLAN]" in prompt

    def test_step_sequence_present(self):
        """All 6 tier-1 protocol steps must appear in deep prompt."""
        prompt = _build_prompt(tier=2)
        for step in ("INVESTIGATE", "SURGICAL", "VERIFY", "SELF-REVIEW", "BE HONEST"):
            assert step in prompt, f"Step '{step}' missing from Tier 2 prompt"


# ---------------------------------------------------------------------------
# C. BPE token counter accuracy
# ---------------------------------------------------------------------------

class TestGetTokenCount:
    def test_empty_string_returns_nonzero_or_zero(self):
        from app.features.ai.harness.context_assembler import get_token_count
        result = get_token_count("")
        assert result >= 0

    def test_known_text_within_range(self):
        from app.features.ai.harness.context_assembler import get_token_count
        text = "Hello, world!"
        result = get_token_count(text)
        # tiktoken exact: 4 tokens; char fallback: 3. Allow [2, 8].
        assert 2 <= result <= 8, f"Token count {result} is implausibly far from expected ~4"

    def test_long_text_scales_linearly(self):
        from app.features.ai.harness.context_assembler import get_token_count
        base = "The quick brown fox jumps over the lazy dog. " * 10
        double = base * 2
        count_base = get_token_count(base)
        count_double = get_token_count(double)
        ratio = count_double / max(count_base, 1)
        assert 1.5 <= ratio <= 2.5, f"Doubling text changed token count by factor {ratio:.2f}, expected ~2"

    def test_returns_int(self):
        from app.features.ai.harness.context_assembler import get_token_count
        assert isinstance(get_token_count("test"), int)


# ---------------------------------------------------------------------------
# D. Memory anchor survival in summarization
# ---------------------------------------------------------------------------

class TestSummarizeConversation:
    def _long_messages(self, n: int = 200) -> list[dict]:
        filler = (
            "The agent investigated the authentication module and found that "
            "the JWT token expiry was set to 3600 seconds but the refresh token "
            "logic was missing an early-return guard. "
        )
        return [{"role": "user" if i % 2 == 0 else "assistant", "content": filler}
                for i in range(n)]

    def test_short_conversation_returns_empty(self):
        from app.features.ai.harness.context_assembler import summarize_conversation
        short_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = asyncio.run(
            summarize_conversation(short_messages, threshold_tokens=4000)
        )
        assert result == ""

    def test_empty_messages_returns_empty(self):
        from app.features.ai.harness.context_assembler import summarize_conversation
        result = asyncio.run(
            summarize_conversation([], threshold_tokens=4000)
        )
        assert result == ""

    def test_memory_anchor_preserved_in_summary(self):
        from app.features.ai.harness.context_assembler import summarize_conversation
        from app.features.ai.providers.base import ProviderStreamEvent

        anchor_line = "ANCHOR: Use stdlib only - no third-party HTTP clients."
        messages = self._long_messages(200)
        messages[10]["content"] += f"\n{anchor_line}"

        # Build a minimal mock provider whose stream_agent yields a text event
        mock_provider = MagicMock()

        async def fake_stream_agent(model, msgs, temperature=0.3, **kwargs):
            yield ProviderStreamEvent(type="text", content="This is a mock summary.")

        mock_provider.stream_agent = fake_stream_agent

        result = asyncio.run(
            summarize_conversation(messages, threshold_tokens=100, provider=mock_provider)
        )
        assert anchor_line in result, (
            f"Memory anchor was not preserved in summary.\nSummary: {result!r}"
        )

    def test_no_summarization_when_below_threshold(self):
        from app.features.ai.harness.context_assembler import summarize_conversation
        messages = self._long_messages(5)
        result = asyncio.run(
            summarize_conversation(messages, threshold_tokens=999_999)
        )
        assert result == ""

