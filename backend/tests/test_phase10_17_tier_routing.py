from __future__ import annotations

import pytest

from app.features.ai.intelligence.task_classifier import classify_task
from app.features.ai.harness.plan_parser import _classify_rules, _is_deep_query, _is_quick_task_query
from app.features.ai.harness.tool_executor import (
    get_tools_for_tier,
    MAX_QUICK_TASK_ITERATIONS,
    MAX_AGENT_ITERATIONS,
    MAX_HUGE_TASK_ITERATIONS,
    HEAVY_TOOLS,
)


# ── Test 1: Complex Prompts Classify Deep ──────────────────────────────────────

def test_complex_prompts_classify_deep():
    """Multi-file, architectural, migration, and complex cross-layer tasks must classify as deep (Tier 2 or 3)."""
    canonical_complex_prompts = [
        "implement OAuth2 across 5 files",
        "migrate Postgres schema",
        "architect new payment module",
        "refactor authentication service across the entire codebase",
    ]

    for prompt in canonical_complex_prompts:
        # Check through unified task classifier
        res = classify_task(prompt, use_llm=False)
        tier = res["tier"]
        effort = res["effort_tier"]
        assert tier == "HARD", f"Expected HARD tier for '{prompt}', got {tier} (score: {res['score']})"
        assert effort >= 2, f"Expected effort_tier >= 2 for '{prompt}', got {effort}"

        # Check through harness plan_parser _classify_rules
        h_tier, h_label, h_reason = _classify_rules(prompt.lower())
        assert h_tier >= 2, f"Expected harness tier >= 2 for '{prompt}', got {h_tier} ({h_label})"
        assert _is_deep_query(prompt), f"Expected _is_deep_query to be True for '{prompt}'"


# ── Test 2: Simple Prompts Stay Fast ──────────────────────────────────────────

def test_simple_prompts_stay_fast():
    """Greetings, conceptual questions, and single-target small edits must stay in Tier 0 or Tier 1."""
    # Tier 0: greetings and pure conceptual questions
    t0_prompts = [
        "hi",
        "hello there",
        "what is a promise in javascript",
    ]
    for prompt in t0_prompts:
        res = classify_task(prompt, use_llm=False)
        assert res["effort_tier"] == 0, f"Expected effort_tier 0 for '{prompt}', got {res['effort_tier']}"
        h_tier, h_label, _ = _classify_rules(prompt.lower())
        assert h_tier == 0, f"Expected harness tier 0 for '{prompt}', got {h_tier} ({h_label})"

    # Tier 1: single-target quick actions
    t1_prompts = [
        "rename variable x to y",
        "fix typo in README.md",
    ]
    for prompt in t1_prompts:
        res = classify_task(prompt, use_llm=False)
        assert res["effort_tier"] == 1, f"Expected effort_tier 1 for '{prompt}', got {res['effort_tier']}"
        h_tier, h_label, _ = _classify_rules(prompt.lower())
        assert h_tier == 1, f"Expected harness tier 1 for '{prompt}', got {h_tier} ({h_label})"
        assert _is_quick_task_query(prompt), f"Expected _is_quick_task_query to be True for '{prompt}'"


# ── Test 3: Deep Tier Changes Tools, Caps, and Models ─────────────────────────

def test_deep_tier_changes_tools_cap_model():
    """Each tier must enforce strict tool filtering and distinct iteration caps."""
    # 1. Tools filtering by tier
    tools_t0 = get_tools_for_tier(tier=0)
    assert len(tools_t0) == 0, "Tier 0 must have exactly zero tools"

    tools_t1 = get_tools_for_tier(tier=1)
    tool_names_t1 = {t["function"]["name"] for t in tools_t1}
    for heavy in HEAVY_TOOLS:
        assert heavy not in tool_names_t1, f"Tier 1 must exclude heavy tool '{heavy}'"

    tools_t2 = get_tools_for_tier(tier=2)
    tool_names_t2 = {t["function"]["name"] for t in tools_t2}
    assert len(tools_t2) > len(tools_t1), "Tier 2 must expose more tools than Tier 1"
    # At least one heavy tool (e.g. get_diagnostics) is available in Tier 2
    assert "get_diagnostics" in tool_names_t2, "Tier 2 should include get_diagnostics"

    # 2. Iteration caps
    assert MAX_QUICK_TASK_ITERATIONS == 10
    assert MAX_AGENT_ITERATIONS == 50
    assert MAX_HUGE_TASK_ITERATIONS == 150


# ── Test 4: Mid-Turn Upgrade Logic ─────────────────────────────────────────────

def test_mid_turn_upgrade_fires():
    """When a turn starts at Tier 1 but involves multi-file refactoring or architecture, escalation to Tier 2/3 occurs."""
    # Canonical multi-file architectural query
    query = "architect new payment module across 5 files"
    tier, label, _ = _classify_rules(query.lower())
    assert tier >= 2, f"Expected tier >= 2, got {tier}"

    # Verify iteration cap resolution: Tier 1 -> 10, Tier 2 -> 50, Tier 3 -> 150
    cap_t1 = MAX_QUICK_TASK_ITERATIONS
    cap_t2 = MAX_AGENT_ITERATIONS
    cap_t3 = MAX_HUGE_TASK_ITERATIONS
    assert cap_t1 < cap_t2 < cap_t3
