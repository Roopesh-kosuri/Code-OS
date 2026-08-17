"""
Unit and regression tests for the Lightweight Chat Agent Harness (chat_harness.py).
Covers adaptive effort routing, budgeted RAG, DAG re-planning, RONY.md project memory,
security allowlist, exact-match mismatch diagnostics, and historical bug class regressions.
"""
import asyncio
import json
import pytest
from pathlib import Path

from app.features.ai.chat_harness import (
    _is_command_safe,
    _parse_plan,
    _parse_plan_dag,
    _replan_on_failure,
    _classify_task_effort,
    _load_project_memory,
    _handle_memory_write,
    _gather_budgeted_rag_context,
    _validate_smart_edit,
    _find_mismatch_context,
    _handle_append_file,
    _has_escalate_marker,
    _response_is_done,
    _declares_tool_intent,
    _is_response_truncated,
    _clean_response_text,
    _parse_tool_calls_extended,
    _has_tool_calls_extended,
    _compact_conversation_history,
    approve_action,
    reject_action,
    respond_to_user_question,
    _pending_approvals,
    _pending_user_responses,
    PendingApproval,
    PendingUserResponse,
    _sse_event,
    _sse_status,
    _sse_tier_routing,
    _sse_ask_user,
    _sse_memory_updated,
    _sse_plan,
    _sse_proposal,
    _sse_done,
    _build_system_prompt,
    DAGPlanStep,
    SAFE_COMMAND_ALLOWLIST,
    SAFE_COMMAND_PREFIXES,
    HARNESS_TOOLS,
    ChatMessage,
    ToolCall,
)
from app.features.ai.schemas import FileChange


# ── 1. Adaptive Effort Routing Regression Tests ──────────────────────────────

def test_regression_adaptive_tier_routing():
    """Verify tier routing: Tier 0 (Fast Answer), Tier 1 (Quick Task), Tier 2 (Deep Task)."""
    # Tier 0: Pure questions, explanations, conceptual lookups
    t0_q1, l0_1 = _classify_task_effort("what does is_source_file in inventory_generator.py do?")
    assert t0_q1 == 0
    assert "Fast Answer" in l0_1

    t0_q2, l0_2 = _classify_task_effort("explain how the rate limiter works in backend/app/core/rate_limiter.py")
    assert t0_q2 == 0

    t0_q3, l0_3 = _classify_task_effort("where is the database connection string defined?")
    assert t0_q3 == 0

    # Tier 1: Single file edits, quick commands, surgical changes
    t1_q1, l1_1 = _classify_task_effort("add '.yaml' to SOURCE_EXTENSIONS in inventory_generator.py")
    assert t1_q1 == 1
    assert "Quick Task" in l1_1

    t1_q2, l1_2 = _classify_task_effort("fix the typo in line 42 of src/App.tsx")
    assert t1_q2 == 1

    t1_q3, l1_3 = _classify_task_effort("run pytest on tests/test_auth.py")
    assert t1_q3 == 1

    # Tier 2: Multi-file, generations, full site builds, refactors
    t2_q1, l2_1 = _classify_task_effort("build a complete modern single-page portfolio site with CSS parallax")
    assert t2_q1 == 2
    assert "Deep think" in l2_1

    t2_q2, l2_2 = _classify_task_effort("refactor the entire authentication system across all files")
    assert t2_q2 == 2

    t2_q3, l2_3 = _classify_task_effort("generate a full HTML site with 1000+ lines")
    assert t2_q3 == 2

    # Agent mode toggle manual override: forces at least Tier 1
    t_agent, l_agent = _classify_task_effort("what is Python?", is_agent_mode=True)
    assert t_agent >= 1


# ── 2. Project Memory (RONY.md) Regression Tests ─────────────────────────────

def test_regression_project_memory_rony_md(tmp_path):
    """Verify loading and writing persistent project conventions to RONY.md."""
    ws = str(tmp_path)

    # 1. Loading when empty
    assert _load_project_memory(ws) == ""

    # 2. Writing a convention
    success, msg = _handle_memory_write(ws, {"fact": "This workspace strictly uses Python 3.11 stdlib."})
    assert success is True
    assert "Saved to project memory" in msg

    # 3. Reading back
    memory_content = _load_project_memory(ws)
    assert "This workspace strictly uses Python 3.11 stdlib." in memory_content

    # 4. Appending a second rule without duplicating
    _handle_memory_write(ws, {"fact": "Always run pytest after modifying test files."})
    memory_content_2 = _load_project_memory(ws)
    assert "This workspace strictly uses Python 3.11 stdlib." in memory_content_2
    assert "Always run pytest after modifying test files." in memory_content_2


# ── 3. Dependency-Aware DAG Plan & Re-Planning Regression Tests ──────────────

def test_regression_dag_replan_on_failure():
    """Verify dependency-aware DAG planning, step dependency parsing, and failure re-planning."""
    dag_response = """
[PLAN]
1. Read existing config in src/config.py
2. Run baseline tests with pytest (depends on 1)
3. Modify settings to add redis caching (depends on 2)
4. Verify all tests pass (depends on 3)
[/PLAN]
"""
    steps = _parse_plan_dag(dag_response)
    assert steps is not None
    assert len(steps) == 4
    assert steps[0].id == "step_1"
    assert steps[1].depends_on == ["step_1"]
    assert steps[2].depends_on == ["step_2"]
    assert steps[3].depends_on == ["step_3"]

    # Simulate step 2 failing
    steps[0].status = "done"
    steps[1].status = "running"
    replanned = _replan_on_failure(steps, 1, "Pytest failed with exit code 1")

    # Step 1 should be failed, dependent steps (step 3, step 4) should be blocked, and fix step inserted
    assert replanned[1].status == "failed"
    fix_step = replanned[2]
    assert fix_step.status == "running"
    assert "Repair failure" in fix_step.title
    # step 3 (which depended on step 2) is now blocked
    step_3_after = next(s for s in replanned if s.id == "step_3")
    assert step_3_after.status == "blocked"


# ── 4. Symbol-Aware Budgeted RAG Regression Tests ────────────────────────────

@pytest.mark.asyncio
async def test_regression_rag_symbol_budgeted_snippets(tmp_path):
    """Verify symbol search and snippet windowing under fixed token budget."""
    ws = str(tmp_path)
    code_file = tmp_path / "inventory_generator.py"
    code_file.write_text(
        "SOURCE_EXTENSIONS = ['.py', '.ts', '.js']\n\n"
        "def is_source_file(path: str) -> bool:\n"
        "    return any(path.endswith(ext) for ext in SOURCE_EXTENSIONS)\n",
        encoding="utf-8",
    )

    matches, rag_summary = await _gather_budgeted_rag_context(
        workspace=ws,
        query="what does is_source_file and SOURCE_EXTENSIONS do?",
        token_budget=1200,
    )
    assert "is_source_file" in rag_summary or "SOURCE_EXTENSIONS" in rag_summary


# ── 5. Security Allowlist & Path Containment Regression Tests ────────────────

def test_regression_security_allowlist_fail_closed(tmp_path):
    """Verify strict fail-closed command allowlist, path containment, and compound rejection."""
    ws = str(tmp_path)
    inside_file = tmp_path / "app.py"
    inside_file.write_text("print(1)", encoding="utf-8")

    # Safe read-only commands
    assert _is_command_safe("ls", ws) is True
    assert _is_command_safe("git status", ws) is True
    assert _is_command_safe("cat app.py", ws) is True
    assert _is_command_safe("type app.py", ws) is True

    # Dangerous / modifying commands -> False
    assert _is_command_safe("rm -rf /", ws) is False
    assert _is_command_safe("del app.py", ws) is False
    assert _is_command_safe("npm install", ws) is False
    assert _is_command_safe("curl https://evil.com", ws) is False

    # Compound operators -> False
    assert _is_command_safe("cat app.py && rm -rf /", ws) is False
    assert _is_command_safe("ls; del app.py", ws) is False
    assert _is_command_safe("echo evil > app.py", ws) is False
    assert _is_command_safe("`del app.py`", ws) is False
    assert _is_command_safe("$(del app.py)", ws) is False


# ── 6. Exact-Match Mismatch Diagnostic Regression Tests ──────────────────────

def test_regression_edit_integrity_mismatch_diagnostic(tmp_path):
    """Verify exact-match pre-validation gives informative line-by-line mismatch diagnostic."""
    ws = str(tmp_path)
    target = tmp_path / "module.py"
    target.write_text(
        "def compute(a, b):\n"
        "    result = a + b\n"
        "    return result\n",
        encoding="utf-8",
    )

    # 1. Exact match succeeds
    valid, err, change = _validate_smart_edit(ws, {
        "path": "module.py",
        "original": "    result = a + b\n    return result",
        "updated": "    return a + b",
    })
    assert valid is True
    assert change is not None

    # 2. Divergent original produces detailed mismatch diagnostic
    valid_fail, err_fail, change_fail = _validate_smart_edit(ws, {
        "path": "module.py",
        "original": "    result = a * b\n    return result",
        "updated": "    return a * b",
    })
    assert valid_fail is False
    assert "Mismatch Diagnostic" in err_fail
    assert "Expected snippet line" in err_fail or "was not found verbatim" in err_fail


# ── 7. Truncation & Chunked Recovery Regression Tests ────────────────────────

def test_regression_truncation_chunked_recovery():
    """Verify truncation detection on cut-off tool blocks and unclosed markdown blocks."""
    truncated_tool = "[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"updated\": \"<html>"
    assert _is_response_truncated(truncated_tool) is True

    complete_tool = "[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"updated\": \"<html>\"}\n[/TOOL_CALL]"
    assert _is_response_truncated(complete_tool) is False

    truncated_code = "```html\n<!DOCTYPE html>\n<html>\n" + ("<div>content</div>\n" * 50)
    assert _is_response_truncated(truncated_code) is True


# ── 8. Error Hygiene & Clean Display Text Regression Tests ───────────────────

def test_regression_error_hygiene_no_raw_markers():
    """Verify raw tool blocks, plan blocks, and control markers are stripped from visible prose."""
    raw = (
        "Here is the plan:\n"
        "[PLAN]\n1. Step one\n[/PLAN]\n"
        "Executing now:\n"
        "[TOOL_CALL: read_file]\n{\"path\": \"main.py\"}\n[/TOOL_CALL]\n"
        "Here is the answer to your question: the function returns True.\n"
        "[DONE]"
    )
    cleaned = _clean_response_text(raw)
    assert "[PLAN]" not in cleaned
    assert "[TOOL_CALL:" not in cleaned
    assert "[DONE]" not in cleaned
    assert "the function returns True." in cleaned


# ── 9. Heuristic Hijack Prevention Regression Tests ──────────────────────────

def test_regression_heuristic_hijack_prevention():
    """Verify discussions/mentions of pytest results or [DONE] do not falsely trigger tool intent."""
    assert _declares_tool_intent("The pytest passed with 41 passed tests.") is False
    assert _declares_tool_intent("Test passed with exit code 0.") is False
    assert _declares_tool_intent("The unit tests failed due to assertion error. [DONE]") is False
    assert _declares_tool_intent("We need to run pytest on tests/test_auth.py") is True
    assert _declares_tool_intent("Use the edit_file tool to update main.py") is True


# ── 10. Interactive ask_user Clarification Regression Tests ──────────────────

def test_regression_interactive_ask_user():
    """Verify ask_user registers pending question and handles response."""
    action_id = "test-ask-001"
    pending = PendingUserResponse(
        action_id=action_id,
        question="Which export format do you prefer?",
        options=["JSON", "Markdown", "HTML"],
    )
    _pending_user_responses[action_id] = pending

    assert respond_to_user_question(action_id, "Markdown") is True
    assert pending.selected_option == "Markdown"
    assert pending.event.is_set()
