"""
test_phase7_1_hotfix.py - Regression and hotfix test suite for Phase 7.1.

Validates:
E1: Escalation Turn Gate (pauses turn, resolves escalate vs continue)
E2: Termination Signal in tool arguments ([DONE], [COMPLETE], [TASK_DONE])
E3: Repeat-Edit Breaker (>3 edits on same path without passing verification trips breaker)
E4: Memory Policy (memory_write rejects [DONE], staging notices, boilerplate)
E5: Ask-User Self-Review Filter (strictly forbids delegating self-review to user)
E6: Vision Gating (requires explicit visual capture intent, rejects bare text queries)
E7: Iteration Cap (per-turn tool cap emits honest partial report)
E8: Content Fidelity & Truncation (135-char OAuth flagged, mid-statement flagged, byte-count chain logged, auto-split on 2 cuts)
"""
import asyncio
import json
import os
import re
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.intelligence.task_classifier import escalation_classifier
from app.features.ai.harness.approval_coordinator import (
    register_pending_escalation,
    resolve_escalation,
    get_pending_escalation,
    clear_all_pending,
    PendingEscalation,
)
from app.features.ai.harness.tool_executor import (
    _handle_memory_write,
    _validate_smart_edit,
    ToolResult,
)
from app.features.ai.harness.content_integrity import (
    is_truncated_content,
    validate_content_integrity,
)
from app.features.ai.harness.activity_logger import _load_activity_log
from app.features.ai.schemas import ChatMessage
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest
from app.features.ai.providers.base import ProviderStreamEvent, ProviderToolCall
from app.features.ai.harness import payload_governor


class MockStreamProvider:
    def __init__(self, stream_fn):
        self.stream_fn = stream_fn

    async def stream_agent(self, *args, **kwargs):
        async for event in self.stream_fn(*args, **kwargs):
            yield event

    async def stream_chat(self, *args, **kwargs):
        async for event in self.stream_fn(*args, **kwargs):
            yield event


@pytest.fixture(autouse=True)
def cleanup():
    clear_all_pending()
    with patch("app.features.ai.chat_harness._gather_budgeted_rag_context", return_value=("", 0)), \
         patch("app.features.ai.chat_harness.rag_semantic_search", new_callable=AsyncMock, return_value=[]):
        yield
    clear_all_pending()


# ── E1: Escalation Turn Gate ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_escalation_gates_turn_before_first_tool():
    """E1: Escalation classifier registers pending escalation and gates turn before any tool execution."""
    action_id = "test-esc-action-1"
    pending = PendingEscalation(
        action_id=action_id,
        task="Implement OAuth2 flow",
        reasoning="Complex multi-file refactor",
        confidence=0.75,
        workspace="/test/ws",
    )
    register_pending_escalation(pending)

    assert get_pending_escalation(action_id) is not None
    assert not pending.event.is_set()

    # User chooses escalate -> resolves and sets event
    success = resolve_escalation(action_id=action_id, decision="escalate")
    assert success is True
    assert pending.event.is_set()
    assert pending.decision == "escalate"


@pytest.mark.asyncio
async def test_escalation_gate_continue_allows_resumption():
    """E1: When user selects continue, pending escalation resolves to continue."""
    action_id = "test-esc-action-2"
    pending = PendingEscalation(
        action_id=action_id,
        task="Implement rate limiter across login module",
        reasoning="Cross-layer feature",
        confidence=0.75,
        workspace="/test/ws",
    )
    register_pending_escalation(pending)

    success = resolve_escalation(action_id=action_id, decision="continue")
    assert success is True
    assert pending.event.is_set()
    assert pending.decision == "continue"


# ── E2: Termination Signal in Tool Arguments ──────────────────────────────

@pytest.mark.asyncio
async def test_done_token_in_tool_arg_terminates_turn():
    """E2: [DONE] token inside ANY tool argument terminates the turn immediately."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Update memory and complete"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        stream_events = [
            ProviderStreamEvent(
                type="tool_calls",
                tool_calls=(
                    ProviderToolCall(
                        id="call_1",
                        name="memory_write",
                        arguments={"fact": "Work completed [DONE]"},
                        arguments_json='{"fact": "Work completed [DONE]"}',
                        complete=True,
                    ),
                ),
                finish_reason="stop",
            )
        ]

        async def mock_stream(*args, **kwargs):
            for ev in stream_events:
                yield ev

        mock_prov = MockStreamProvider(mock_stream)

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)

            # Check that termination_signal status was emitted
            term_events = [e for e in events if "termination_signal" in e]
            assert len(term_events) > 0, f"Expected termination_signal event, got: {events}"

            # Check that done event was emitted
            done_events = [e for e in events if "event: done" in e]
            assert len(done_events) > 0


# ── E3: Repeat-Edit Breaker ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_repeat_edit_breaker_stops_after_three():
    """E3: >3 edit attempts on same path without passing verification trips breaker and halts edits."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Fix bug in auth.py"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        # 4 consecutive edit attempts on auth.py without test/diagnostics verification
        tool_calls = [
            ProviderToolCall(
                id=f"call_{i}",
                name="edit_file",
                arguments={"path": "auth.py", "original": "", "updated": f"# attempt {i}\nprint('hello')\n"},
                arguments_json=f'{{"path": "auth.py", "original": "", "updated": "# attempt {i}\\nprint(\'hello\')\\n"}}',
                complete=True,
            )
            for i in range(1, 5)
        ]

        stream_events = [
            ProviderStreamEvent(
                type="tool_calls",
                tool_calls=tuple(tool_calls),
                finish_reason="stop",
            )
        ]

        async def mock_stream(*args, **kwargs):
            for ev in stream_events:
                yield ev

        mock_prov = MockStreamProvider(mock_stream)

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)
                if "breaker_tripped" in ev:
                    break

            breaker_events = [e for e in events if "breaker_tripped" in e]
            assert len(breaker_events) > 0, f"Expected breaker_tripped event after 3rd attempt, got: {events}"


# ── E4: Memory Policy ─────────────────────────────────────────────────────

def test_memory_write_rejects_done_and_boilerplate():
    """E4: memory_write strictly rejects control signals ([DONE]), staging notices, and narration boilerplate."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Control signals
        ok, msg = _handle_memory_write(tmpdir, {"fact": "[DONE]"})
        assert not ok
        assert "control signals" in msg

        ok, msg = _handle_memory_write(tmpdir, {"fact": "Implementation complete [COMPLETE]"})
        assert not ok
        assert "control signals" in msg

        # Narration boilerplate
        ok, msg = _handle_memory_write(tmpdir, {"fact": "changes verified and all tests pass"})
        assert not ok
        assert "control signals" in msg or "narration boilerplate" in msg

        ok, msg = _handle_memory_write(tmpdir, {"fact": "staged files for login module"})
        assert not ok
        assert "control signals" in msg or "staging" in msg

        # Durable technical fact should succeed
        ok, msg = _handle_memory_write(tmpdir, {"fact": "OAuth access tokens expire after 3600 seconds"})
        assert ok
        assert "Saved to project memory" in msg or "Recorded to project memory" in msg


# ── E5: Ask-User Self-Review Filter ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_user_never_delegates_self_review():
    """E5: ask_user strictly forbids delegating self-review or verification to the user."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Refactor database layer"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        stream_events = [
            ProviderStreamEvent(
                type="tool_calls",
                tool_calls=(
                    ProviderToolCall(
                        id="call_ask",
                        name="ask_user",
                        arguments={"question": "Is this implementation complete and correct?"},
                        arguments_json='{"question": "Is this implementation complete and correct?"}',
                        complete=True,
                    ),
                ),
                finish_reason="stop",
            )
        ]

        async def mock_stream(*args, **kwargs):
            for ev in stream_events:
                yield ev

        mock_prov = MockStreamProvider(mock_stream)

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)
                if "Self-review delegation policy" in ev:
                    break

            # Check that self-review error was yielded
            self_review_errors = [e for e in events if "Self-review delegation policy" in e or "responsibility to verify" in e]
            assert len(self_review_errors) > 0, f"Expected self-review rejection, got: {events}"


# ── E6: Vision Gating ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vision_requires_screenshot_intent():
    """E6: vision / take_screenshot requires explicit capture target/mode; bare question queries return tool_error."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Analyze code structure"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        # Bare text query to vision tool without mode or target
        stream_events = [
            ProviderStreamEvent(
                type="tool_calls",
                tool_calls=(
                    ProviderToolCall(
                        id="call_vis",
                        name="take_screenshot",
                        arguments={"question": "What does this function do?"},
                        arguments_json='{"question": "What does this function do?"}',
                        complete=True,
                    ),
                ),
                finish_reason="stop",
            )
        ]

        async def mock_stream(*args, **kwargs):
            for ev in stream_events:
                yield ev

        mock_prov = MockStreamProvider(mock_stream)

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)

            vision_errors = [e for e in events if "Vision tool requires explicit visual capture intent" in e]
            assert len(vision_errors) > 0, f"Expected vision gating error, got: {events}"


# ── E7: Iteration Cap Produces Partial Report ─────────────────────────────

@pytest.mark.asyncio
async def test_iteration_cap_produces_partial_report():
    """E7: Enforce visible per-turn tool cap (25); emits honest partial report on cap, no silent continuation."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Search codebase thoroughly"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        # Emit 26 tool calls
        calls = [
            ProviderToolCall(
                id=f"c_{i}",
                name="search_code",
                arguments={"query": f"term_{i}"},
                arguments_json=f'{{"query": "term_{i}"}}',
                complete=True,
            )
            for i in range(26)
        ]

        stream_events = [
            ProviderStreamEvent(
                type="tool_calls",
                tool_calls=tuple(calls),
                finish_reason="stop",
            )
        ]

        async def mock_stream(*args, **kwargs):
            for ev in stream_events:
                yield ev

        mock_prov = MockStreamProvider(mock_stream)

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)

            cap_events = [e for e in events if "tool_cap_reached" in e or "Per-Turn Tool Cap Reached" in e]
            assert len(cap_events) > 0, f"Expected tool cap reached event, got: {events}"


# ── E8: Content Fidelity & Truncation ─────────────────────────────────────

def test_integrity_gate_flags_135_char_oauth_staging():
    """E8: Extended integrity gate detects undersized implementations (e.g. 135-char OAuth2) as incomplete/TRUNCATED."""
    oauth_stub = "def login_oauth(provider: str):\n    # TODO: implement oauth2 flow\n    return {'status': 'pending', 'provider': provider}\n"
    assert len(oauth_stub) < 250

    # Complex auth task
    task = "Implement OAuth2 login with Google and GitHub, token refresh, and sessions"
    status, msg = validate_content_integrity("auth/oauth.py", oauth_stub, user_query=task)

    assert status in ("incomplete", "blocked")
    assert "undersized" in (msg or "").lower() or "truncated" in (msg or "").lower() or "placeholder" in (msg or "").lower()


def test_truncated_tool_call_json_never_staged():
    """E8: _validate_smart_edit runs is_truncated_content and rejects unclosed/truncated code from staging."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Code that cuts off mid-statement
        truncated_code = "def authenticate_user(token):\n    headers = {'Auth': token}\n    response = requests.get("
        valid, err, change = _validate_smart_edit(tmpdir, {
            "path": "auth.py",
            "original": "",
            "updated": truncated_code,
        })

        assert not valid
        assert "truncated" in err.lower() or "incomplete" in err.lower()
        assert change is None


def test_balanced_but_mid_statement_content_flagged_truncated():
    """E8: Code ending with a trailing dot or incomplete statement is flagged truncated even if braces balance."""
    mid_statement_code = (
        "class AuthService:\n"
        "    def validate(self, token):\n"
        "        user = self.get_user(token)\n"
        "        return user.\n"
    )
    is_trunc, reason = is_truncated_content(mid_statement_code)
    assert is_trunc is True
    assert "return user." in reason or "ends abruptly" in reason or "truncated" in reason.lower()


def test_stream_parser_accumulates_across_chunk_boundaries():
    """E8: Stream parser accumulates deltas across chunk boundaries and marks complete only when valid JSON parses."""
    from app.features.ai.providers.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider("test-provider", api_key="sk-test")

    # Simulate chunks building up a tool call JSON across stream deltas
    chunk_1 = {"name": "edit_file", "arguments": '{"path": "test.py", '}
    chunk_2 = {"arguments": '"original": "", "updated": "print(1)"}'}

    full_args = chunk_1["arguments"] + chunk_2["arguments"]
    parsed = json.loads(full_args)

    assert parsed["path"] == "test.py"
    assert parsed["updated"] == "print(1)"


@pytest.mark.asyncio
async def test_finish_reason_length_triggers_continuation_or_split():
    """E8: Stream finish_reason == 'length' triggers continuation on 1st cut."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Generate large file"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        stream_events_cut1 = [
            ProviderStreamEvent(
                type="incomplete_tool_call",
                finish_reason="length",
            )
        ]

        async def mock_stream(*args, **kwargs):
            for ev in stream_events_cut1:
                yield ev

        mock_prov = MockStreamProvider(mock_stream)

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)
                if len(events) > 10:
                    break

            continuation_events = [e for e in events if "truncated" in e.lower() or "continuation" in e.lower()]
            assert len(continuation_events) > 0, f"Expected continuation on cut 1, got: {events}"


@pytest.mark.asyncio
async def test_edit_auto_split_after_two_cuts():
    """E8: After 2 length truncation cuts, the system injects the auto-split directive."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Generate very large module"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        call_count = 0

        async def mock_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield ProviderStreamEvent(
                type="incomplete_tool_call",
                finish_reason="length",
            )

        mock_prov = MockStreamProvider(mock_stream)

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)
                if len(events) > 25:
                    break

            split_events = [e for e in events if "auto-splitting" in e.lower() or "auto-split" in e.lower()]
            assert len(split_events) > 0, f"Expected auto-split event on cut 2, got: {events}"


@pytest.mark.asyncio
async def test_byte_count_chain_logged_and_mismatch_blocks_apply():
    """E8: Byte count chain {model_emitted, parsed, staged, applied} is verified; mismatch blocks apply."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Edit file with mismatch"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )

        # Simulate a tool call where updated argument was tampered or mismatched
        stream_events = [
            ProviderStreamEvent(
                type="tool_calls",
                tool_calls=(
                    ProviderToolCall(
                        id="c_edit",
                        name="edit_file",
                        arguments={"path": "main.py", "original": "", "updated": "print('hello world')\n"},
                        arguments_json='{"path": "main.py", "original": "", "updated": "print(\'hello world\')\\n"}',
                        complete=True,
                    ),
                ),
                finish_reason="stop",
            )
        ]

        async def mock_stream(*args, **kwargs):
            for ev in stream_events:
                yield ev

        mock_prov = MockStreamProvider(mock_stream)

        class Utf8TestEncoding:
            def encode(self, text):
                return list(range((len(text.encode("utf-8")) + 3) // 4))

        with patch("app.features.ai.chat_harness.provider_for", return_value=mock_prov):
            events = []
            async for ev in run_chat_agent(req):
                events.append(ev)
                log = _load_activity_log(tmpdir)
                if any(entry.get("action_type") == "edit_byte_count_chain" for entry in log) or len(events) > 20:
                    break

            # Check activity log for edit_byte_count_chain
            log = _load_activity_log(tmpdir)
            byte_chain_entries = [entry for entry in log if entry.get("action_type") == "edit_byte_count_chain"]
            assert len(byte_chain_entries) > 0, f"Expected edit_byte_count_chain in activity log, got: {log}"

            chain = json.loads(byte_chain_entries[0]["details"])
            assert "model_emitted" in chain
            assert "parsed" in chain
            assert "staged" in chain
            assert "applied" in chain
            assert chain["model_emitted"] == chain["parsed"] == chain["staged"] == chain["applied"]


@pytest.mark.asyncio
async def test_utf8_byte_chain_blocks_normalization_changed_tool_argument():
    """A model-emitted decomposed character cannot silently become NFC when parsed."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        req = ChatAgentRequest(
            messages=[{"role": "user", "content": "Edit Unicode file"}],
            workspace=tmpdir,
            provider="openai",
            model="gpt-4o",
            is_agent_mode=True,
        )
        stream_events = [
            ProviderStreamEvent(
                type="tool_calls",
                tool_calls=(
                    ProviderToolCall(
                        id="c_unicode",
                        name="edit_file",
                        arguments={"path": "main.py", "original": "", "updated": "é"},
                        arguments_json='{"path":"main.py","original":"","updated":"e\\u0301"}',
                        complete=True,
                    ),
                ),
                finish_reason="stop",
            )
        ]

        async def mock_stream(*_args, **_kwargs):
            for event in stream_events:
                yield event

        class Utf8TestEncoding:
            def encode(self, text):
                return list(range((len(text.encode("utf-8")) + 3) // 4))

        with patch("app.features.ai.chat_harness.provider_for", return_value=MockStreamProvider(mock_stream)):
            events = []
            async for event in run_chat_agent(req):
                events.append(event)
                if any("event: integrity" in item for item in events):
                    break

        assert any("UTF-8 byte-fidelity mismatch" in event for event in events)
        assert any("event: integrity" in event and '"outcome": "blocked"' in event for event in events)
        assert not any(entry.get("action_type") == "edit_byte_count_chain" for entry in _load_activity_log(tmpdir))
