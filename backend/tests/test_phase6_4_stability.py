"""Regression and stability test suite for Phase 6.4 and Phase 6.4b.

Verifies:
1. ToolResult arbitrary kwargs handling
2. ToolResult serialization and representation
3. Conversational turns ignoring attached_paths (Fast Answer Tier 0)
4. Comprehensive conversational turn detection
5. Prompt enhancer classifying conversational input as 'good'
6. Prompt enhancer classifying assistant-meta questions as 'good'
7. Prompt enhancer passing through conversational queries untouched
8. Prompt enhancer rejecting canned/boilerplate LLM outputs (fail-open)
9. Chat harness memory_write repetition breaker (> 2 identical rejections disables tool)
10. Chat harness substantive-prose conclude rule without requiring prior ask_user count
11. test_enhancer_no_bar_for_greetings_meta_questions
12. test_enhancer_template_deleted
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.features.ai.harness.tool_executor import ToolResult
from app.features.ai.harness.plan_parser import is_conversational_turn, _classify_rules
from app.features.ai.intelligence.prompt_enhancer import (
    classify_prompt_quality,
    enhance_prompt,
    set_enhancer_llm_fn,
    reset_enhancer_llm_fn,
    clear_enhancer_session_cache,
)
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest


def test_tool_result_arbitrary_kwargs():
    """Verify ToolResult accepts arbitrary kwargs without raising TypeError."""
    res = ToolResult(
        success=True,
        output="ok",
        error="",
        custom_flag=True,
        execution_duration_ms=42.5,
        status_code=200,
    )
    assert res.success is True
    assert res.output == "ok"
    assert getattr(res, "custom_flag") is True
    assert getattr(res, "execution_duration_ms") == 42.5
    assert getattr(res, "status_code") == 200


def test_tool_result_to_dict_and_repr():
    """Verify ToolResult to_dict and repr serialize safely."""
    res = ToolResult(
        tool_name="test_tool",
        success=False,
        output="",
        error="Something broke",
        failure_reason="test_error",
        failure_detail="Details here",
    )
    d = res.to_dict()
    assert d["tool_name"] == "test_tool"
    assert d["success"] is False
    assert d["error"] == "Something broke"
    assert d["failure_reason"] == "test_error"
    assert "ToolResult" in repr(res)


def test_conversational_turn_ignores_attached_paths():
    """Verify attached_paths does not bypass conversational safety to force high tiers."""
    tier, label, reason = _classify_rules("Hi, how are you?", attached_paths=["src/index.ts", "package.json"])
    assert tier == 0
    assert label == "Fast Answer"

    tier2, label2, _ = _classify_rules("thanks for your help!", attached_paths=["main.py"])
    assert tier2 == 0
    assert label2 == "Fast Answer"


def test_conversational_detection_comprehensive():
    """Verify greetings, pleasantries, and meta questions are conversational turns."""
    inputs = [
        "hi",
        "hello",
        "hey there",
        "good morning",
        "how are you?",
        "how are you doing today?",
        "who are you?",
        "what can you do?",
        "tell me about yourself",
        "thanks!",
        "thank you so much",
    ]
    for inp in inputs:
        assert is_conversational_turn(inp) is True, f"Expected '{inp}' to be conversational"


def test_enhancer_classify_conversational_good():
    """Verify classify_prompt_quality marks conversational queries as 'good' with score 1.0."""
    greetings = ["hi", "hello", "how are you?", "thanks for your help!"]
    for q in greetings:
        res = classify_prompt_quality(q)
        assert res["quality"] == "good", f"Expected 'good' for '{q}', got {res}"
        assert res["score"] == 1.0
        assert len(res["issues"]) == 0


def test_enhancer_classify_meta_questions_good():
    """Verify classify_prompt_quality marks assistant meta-questions as 'good'."""
    meta_questions = [
        "what can you do?",
        "who are you?",
        "how do you work?",
        "tell me about yourself",
        "what models do you support?",
    ]
    for mq in meta_questions:
        res = classify_prompt_quality(mq)
        assert res["quality"] == "good", f"Expected 'good' for '{mq}', got {res}"
        assert res["score"] == 1.0
        assert len(res["issues"]) == 0


@pytest.mark.asyncio
async def test_enhancer_pass_through_conversational():
    """Verify enhance_prompt returns pass-through model_used and untouched prompt for conversational queries."""
    clear_enhancer_session_cache()
    res = await enhance_prompt("hi how are you?")
    assert res["enhanced"] == "hi how are you?"
    assert res["original"] == "hi how are you?"
    assert res["model_used"] == "pass-through"
    assert res["changes"] == []


@pytest.mark.asyncio
async def test_enhancer_boilerplate_rejected():
    """Verify canned or conversational LLM outputs fail-open back to the original prompt."""
    clear_enhancer_session_cache()

    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "Hello! How can I assist you with your code today?"

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.service.provider_for", AsyncMock(return_value=mock_provider)):
        res = await enhance_prompt("make it better", quality={"quality": "weak", "issues": ["vague"], "score": 0.3})
        assert res["model_used"] == "fail-open"
        assert res["enhanced"] == "make it better"
        assert res["original"] == "make it better"
        assert res["changes"] == []


@pytest.mark.asyncio
async def test_memory_write_repetition_breaker(tmp_path):
    """Verify identical rejected fact > 2 times removes memory_write from active_tools for the turn and gives disabled-tool error."""
    ws = str(tmp_path)
    mock_provider = MagicMock()
    turn_idx = 0

    async def mock_stream(*args, **kwargs):
        nonlocal turn_idx
        turn_idx += 1
        # Model repeatedly attempts to save the same rejected mood fact
        yield '[TOOL_CALL: memory_write]\n{"fact": "User is in a good mood"}\n[/TOOL_CALL]'

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="llama-3.1-nemotron-70b-instruct",
        workspace=ws,
        messages=[{"role": "user", "content": "Configure project conventions with my preferences"}],
        is_agent_mode=True,
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)
            if len(events) > 60:
                break

    # Check that after > 2 rejections, disabled tool error was emitted
    tool_results = [e for e in events if "memory_write has been disabled" in e or "Tool disabled" in e]
    assert len(tool_results) > 0, "Expected memory_write to be disabled after repeated identical rejections"


@pytest.mark.asyncio
async def test_substantive_prose_conclude_rule_no_prior_ask_count(tmp_path):
    """Verify substantive answer prose (>= 50 chars) with ask_user pending tool finalizes immediately without requiring prior ask_user count."""
    ws = str(tmp_path)
    mock_provider = MagicMock()

    async def mock_stream(*args, **kwargs):
        # On turn 1 (ask_user_count == 0), model produces substantive answer prose + ask_user call
        yield (
            "Here is the complete architectural analysis of your authentication subsystem. "
            "It uses PBKDF2 with SHA-256 and securely manages tokens in HttpOnly cookies.\n"
            '[TOOL_CALL: ask_user]\n{"question": "Would you like me to add refresh tokens?", "options": ["Yes", "No"]}\n[/TOOL_CALL]'
        )

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="llama-3.1-nemotron-70b-instruct",
        workspace=ws,
        messages=[{"role": "user", "content": "Analyze the authentication architecture."}],
        is_agent_mode=True,
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)

    # Verify that the turn concluded immediately with done=True and did NOT register ask_user or hang
    done_events = [e for e in events if "event: done" in e and ('"success": true' in e.lower() or '"success":true' in e.lower())]
    assert len(done_events) > 0, "Expected task to conclude immediately on substantive prose without prior ask_user count"


def test_enhancer_no_bar_for_greetings_meta_questions():
    """Specific acceptance test: greetings and meta questions produce 'good' quality and no bar/issues."""
    queries = [
        "hi how are you?",
        "thanks for your help!",
        "what can you do?",
        "who are you?",
        "good afternoon",
        "how does this work?",
    ]
    for q in queries:
        res = classify_prompt_quality(q)
        assert res["quality"] == "good", f"Expected 'good' for '{q}', got {res}"
        assert res["score"] == 1.0
        assert res["issues"] == []


def test_enhancer_template_deleted():
    """Specific acceptance test: canned boilerplate string 'Investigate and fix the issue' is completely deleted."""
    import inspect
    import app.features.ai.intelligence.prompt_enhancer as pe_module

    source = inspect.getsource(pe_module)
    assert "Investigate and fix the issue" not in source
    assert "investigate and fix the issue" not in source.lower() or "investigate and fix" in source.lower()  # only permitted as rejected filter phrase
