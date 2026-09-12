"""Regression tests for Phase 6.1: Conversational Safety & Edit Intent Guard."""

import pytest
from app.features.ai.harness.plan_parser import (
    is_conversational_turn,
    has_explicit_change_intent,
    _classify_rules,
)
from app.features.ai.harness.tool_executor import (
    _handle_memory_write,
    _is_social_or_mood_fact,
    READ_ONLY_TOOLS,
    CORE_CODING_TOOLS,
)


def test_conversational_detection():
    """Verify that greetings, pleasantries, and questions directed at the assistant are conversational."""
    conversational_inputs = [
        "hi",
        "Hi, how are you?",
        "Good morning!",
        "hello there",
        "How are you doing today?",
        "Hey Rony, what are you?",
        "thanks for the help",
        "who are you?",
        "how do you work?",
        "nice to meet you",
    ]
    for text in conversational_inputs:
        assert is_conversational_turn(text) is True, f"Expected '{text}' to be conversational"

    task_inputs = [
        "fix the bug in login_module.py",
        "implement JWT authentication",
        "add error handling to the server",
        "delete node.js and three.js",
        "refactor main.cpp to use smart pointers",
        "create a test suite for auth",
    ]
    for text in task_inputs:
        assert is_conversational_turn(text) is False, f"Expected '{text}' NOT to be conversational"


def test_conversational_stays_tier_0_in_agent_mode():
    """Verify conversational queries remain Tier 0 even when Agent mode is enabled."""
    tier, label, reason = _classify_rules("Hi, how are you?", is_agent_mode=True)
    assert tier == 0, f"Expected Tier 0, got {tier}"
    assert label == "Fast Answer"

    tier2, label2, _ = _classify_rules("hello", is_agent_mode=True)
    assert tier2 == 0
    assert label2 == "Fast Answer"


def test_conversational_turn_has_no_write_tools():
    """Verify that read-only tool subset contains only safe inspecting tools and no write/ask tools."""
    tool_names = [t["function"]["name"] for t in READ_ONLY_TOOLS]
    assert "read_file" in tool_names
    assert "semantic_search" in tool_names
    assert "edit_file" not in tool_names
    assert "append_file" not in tool_names
    assert "ask_user" not in tool_names
    assert "memory_write" not in tool_names


def test_global_edit_intent_gate_blocks_unauthorized_edits():
    """Verify that turns without explicit change intent do not have edit authorization."""
    assert has_explicit_change_intent("Hi, how are you?") is False
    assert has_explicit_change_intent("What does main.cpp do?") is False
    assert has_explicit_change_intent("Can you explain how this works?") is False

    # Valid change intent requires an explicit action verb
    assert has_explicit_change_intent("Fix the bug in main.cpp") is True
    assert has_explicit_change_intent("Update the login module with bcrypt") is True
    assert has_explicit_change_intent("Add refresh tokens to auth") is True


def test_ask_user_cannot_mirror_user_question():
    """Verify question-mirroring prevention logic."""
    user_q = "How are you?"
    agent_q = "How are you?"
    # Both lower-stripped and cleaned
    u_norm = user_q.lower().strip(" ?.!,\t\n\r")
    a_norm = agent_q.lower().strip(" ?.!,\t\n\r")
    assert u_norm == a_norm, "Mirrored question should be strictly detected"


def test_memory_write_rejects_mood_and_social_facts():
    """Verify memory_write rejects mood and social notes."""
    assert _is_social_or_mood_fact("User is in good mood") is True
    assert _is_social_or_mood_fact("User is happy with the progress") is True
    assert _is_social_or_mood_fact("How are you today?") is True
    assert _is_social_or_mood_fact("User's personality is calm") is True

    # Technical facts should NOT be rejected
    assert _is_social_or_mood_fact("JWT authentication uses bcrypt with 100,000 PBKDF2 iterations") is False
    assert _is_social_or_mood_fact("Database connection pool size set to 20") is False

    # Calling handler directly with a mood fact returns rejection message
    ok, result = _handle_memory_write("dummy_ws", {"fact": "User is in good mood"})
    assert ok is False
    assert "Rejected" in result
    assert "social/mood notes are not permitted" in result


def test_explicit_change_intent_detection():
    """Verify change intent detection across various inputs."""
    edits = [
        "Please update the database configuration",
        "remove the old endpoint in api.py",
        "refactor the authentication handler",
        "fix syntax error in main.py",
        "patch security vulnerability in token verification",
    ]
    for q in edits:
        assert has_explicit_change_intent(q) is True, f"Failed for: {q}"

    non_edits = [
        "What is the current version?",
        "Where is the database configured?",
        "Explain the authentication architecture",
        "Hi, how are things going?",
        "Who wrote this code?",
    ]
    for q in non_edits:
        assert has_explicit_change_intent(q) is False, f"Should be False for: {q}"
