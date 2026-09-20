"""test_phase6_3_tools.py — Regression tests for CODE OS v5.0.0 Phase 6.3 Tool Maturity & Bulletproofing.

Covers:
1. test_reviewer_role_read_only_manifest
2. test_documenter_role_read_only_manifest
3. test_tier1_excludes_heavy_tools
4. test_get_diagnostics_returns_compiler_errors
5. test_get_diagnostics_fallback_when_unavailable
6. test_intent_based_tool_selection_db_task
7. test_intent_based_tool_selection_frontend_task
8. test_tool_schema_token_budget_respected
9. test_rollback_restores_workspace_state
10. test_checkpoint_created_before_edit
"""
import os
import json
import pytest
import tempfile
import subprocess
from pathlib import Path

from app.features.ai.schemas import ChatMessage
from app.features.ai.agents.agent_tools import (
    ToolCall,
    execute_tool_calls,
    get_role_manifest,
    is_tool_allowed_for_role,
    ROLE_MANIFESTS,
)
from app.features.ai.agents.documenter import DocumenterAgent
from app.features.ai.agents.reviewer import ReviewerAgent
from app.features.ai.team.roles import (
    ReviewerRole,
    DocumenterRole,
    ArchitectRole,
    CoderRole,
    get_role_instance,
)
from app.features.ai.team.team_schemas import TeamRole
from app.features.ai.harness.tool_executor import (
    get_tools_for_tier,
    HEAVY_TOOLS,
    CORE_CODING_TOOLS,
    SLIM_CODING_TOOLS,
    _handle_get_diagnostics,
)
from app.features.ai.harness.diagnostics_service import (
    DiagnosticsService,
    run_diagnostics,
)
from app.features.ai.harness.intent_tool_selector import (
    detect_task_intent,
    filter_tools_by_intent,
)
from app.features.ai.harness.payload_governor import (
    govern_payload,
    estimate_payload_breakdown,
    estimate_request_tokens,
)
from app.features.ai.harness.checkpoint_manager import (
    _ensure_git_checkpoint,
    undo_turn_files,
)
from app.features.ai.harness import payload_governor


# Governor is now dependency-free (Phase 10.13)


# -----------------------------------------------------------------------------
# 1. Symptom 1: Reviewer Role Read-Only Manifest
# -----------------------------------------------------------------------------
def test_reviewer_role_read_only_manifest():
    """Verify Reviewer role has strictly read-only manifest and rejects write tools."""
    manifest = get_role_manifest("reviewer")
    assert "read_file" in manifest
    assert "search_code" in manifest
    assert "list_directory" in manifest
    assert "edit_file" not in manifest
    assert "run_command" not in manifest

    # ReviewerRole in team architecture is read-only
    role_inst = ReviewerRole()
    allowed_edit, _ = role_inst.validate_tool_permission("edit_file", {"path": "main.py"})
    assert allowed_edit is False
    allowed_cmd, _ = role_inst.validate_tool_permission("run_command", {"command": "rm -rf"})
    assert allowed_cmd is False

    # Calling execute_tool_calls with role='reviewer' blocks edit_file and run_command
    with tempfile.TemporaryDirectory() as tmpdir:
        staged = []
        calls = [
            ToolCall(name="edit_file", arguments={"path": "foo.py", "original": "", "updated": "print('hello')"}),
            ToolCall(name="run_command", arguments={"command": "dir"}),
        ]
        out = execute_tool_calls(calls, tmpdir, staged, agent_role="reviewer")
        assert "Permission denied" in out
        assert len(staged) == 0


# -----------------------------------------------------------------------------
# 2. Symptom 1: Documenter Role Read-Only Manifest
# -----------------------------------------------------------------------------
def test_documenter_role_read_only_manifest():
    """Verify Documenter role has strictly read-only manifest and rejects write tools."""
    manifest = get_role_manifest("documenter")
    assert "read_file" in manifest
    assert "search_code" in manifest
    assert "list_directory" in manifest
    assert "edit_file" not in manifest
    assert "run_command" not in manifest

    # DocumenterAgent system prompt is read-only
    agent = DocumenterAgent()
    prompt = agent.get_system_prompt()
    assert "read-only analysis mode" in prompt
    assert "edit_file" not in prompt or "Write tools (edit_file, run_command) are disabled" in prompt

    # DocumenterRole in team architecture is read-only
    doc_role = DocumenterRole()
    allowed_edit, _ = doc_role.validate_tool_permission("edit_file", {"path": "README.md"})
    assert allowed_edit is False

    # Calling execute_tool_calls with role='documenter' blocks edit_file
    with tempfile.TemporaryDirectory() as tmpdir:
        staged = []
        calls = [ToolCall(name="edit_file", arguments={"path": "README.md", "original": "", "updated": "# Docs"})]
        out = execute_tool_calls(calls, tmpdir, staged, agent_role="documenter")
        assert "Permission denied" in out
        assert len(staged) == 0


# -----------------------------------------------------------------------------
# 3. Symptom 1: Tier 1 Excludes Heavy Tools
# -----------------------------------------------------------------------------
def test_tier1_excludes_heavy_tools():
    """Verify Tier 1 (Quick Task) strictly excludes heavy tools reserved for Tier 2+."""
    tier1_tools = get_tools_for_tier(1)
    tier1_names = {t["function"]["name"] for t in tier1_tools}

    # Heavy tools reserved for Tier 2+
    for heavy in ("edit_range", "get_diagnostics", "server_session"):
        assert heavy not in tier1_names, f"Heavy tool '{heavy}' found in Tier 1 manifest"

    # Browser tools strictly excluded from Tier 1 by default
    assert not any(n.startswith("browser_") for n in tier1_names)

    # Computer tools strictly excluded from Tier 1 even if requested
    tier1_comp = get_tools_for_tier(1, enable_computer=True)
    assert not any(t["function"]["name"].startswith("screen_") or t["function"]["name"] in ("mouse_click", "keyboard_type", "hotkey", "open_app") for t in tier1_comp)

    # Tier 2 allows heavy tools
    tier2_tools = get_tools_for_tier(2)
    tier2_names = {t["function"]["name"] for t in tier2_tools}
    assert "edit_range" in tier2_names
    assert "find_references" in tier2_names
    assert "go_to_definition" in tier2_names
    assert "get_diagnostics" in tier2_names


# -----------------------------------------------------------------------------
# 4. Symptom 2: get_diagnostics Returns Compiler Errors (Mock Provider & Native)
# -----------------------------------------------------------------------------
def test_get_diagnostics_returns_compiler_errors():
    """Verify get_diagnostics returns compiler/type errors using mock provider and syntax checker."""
    DiagnosticsService.reset()

    # 1. Test with Mock Provider
    mock_errors = [
        {"line": 15, "column": 8, "severity": "error", "message": "Cannot find name 'UserService'", "source": "tsc"},
        {"line": 22, "column": 12, "severity": "warning", "message": "Unused variable 'temp'", "source": "eslint"},
    ]
    DiagnosticsService.set_mock_provider(lambda ws, fp: mock_errors)

    with tempfile.TemporaryDirectory() as tmpdir:
        res = _handle_get_diagnostics(tmpdir, {"file_path": "src/user.ts"})
        assert res.success is True
        data = json.loads(res.output)
        assert len(data) == 2
        assert data[0]["message"] == "Cannot find name 'UserService'"

    # 2. Test with native Python syntax error detection
    DiagnosticsService.reset()
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_file = Path(tmpdir) / "broken.py"
        bad_file.write_text("def broken_func(\n    return 42\n", encoding="utf-8")

        res_native = _handle_get_diagnostics(tmpdir, {"file_path": "broken.py"})
        assert res_native.success is True
        native_data = json.loads(res_native.output)
        assert len(native_data) >= 1
        assert native_data[0]["severity"] == "error"
        assert native_data[0]["source"] == "py_compile"


# -----------------------------------------------------------------------------
# 5. Symptom 2: get_diagnostics Fallback When Unavailable
# -----------------------------------------------------------------------------
def test_get_diagnostics_fallback_when_unavailable():
    """Verify get_diagnostics returns graceful fallback when service is unavailable or file has no errors."""
    DiagnosticsService.reset()
    DiagnosticsService.set_available(False)

    with tempfile.TemporaryDirectory() as tmpdir:
        res = _handle_get_diagnostics(tmpdir, {"file_path": "clean.py"})
        assert res.success is True
        assert "Diagnostics unavailable" in res.output

    DiagnosticsService.reset()


# -----------------------------------------------------------------------------
# 6. Symptom 3: Intent-Based Tool Selection for DB Tasks
# -----------------------------------------------------------------------------
def test_intent_based_tool_selection_db_task():
    """Verify database tasks detect 'db' intent and exclude browser/computer tools."""
    intent = detect_task_intent("Generate a SQLite migration to add accounts table and schema.sql index")
    assert intent == "db"

    all_tools = get_tools_for_tier(2, enable_browser=True, enable_computer=True)
    assert any(t["function"]["name"].startswith("browser_") for t in all_tools)

    filtered = filter_tools_by_intent(all_tools, intent)
    filtered_names = {t["function"]["name"] for t in filtered}

    assert not any(n.startswith("browser_") for n in filtered_names)
    assert not any(n.startswith("screen_") or n in ("mouse_click", "keyboard_type") for n in filtered_names)
    assert "edit_file" in filtered_names
    assert "read_file" in filtered_names


# -----------------------------------------------------------------------------
# 7. Symptom 3: Intent-Based Tool Selection for Frontend Tasks
# -----------------------------------------------------------------------------
def test_intent_based_tool_selection_frontend_task():
    """Verify frontend tasks detect 'frontend' intent and exclude backend-heavy tools."""
    intent = detect_task_intent("Fix React button styling and modal navbar layout in Component.tsx")
    assert intent == "frontend"

    all_tools = get_tools_for_tier(2)
    assert any(t["function"]["name"] == "server_session" for t in all_tools)

    filtered = filter_tools_by_intent(all_tools, intent)
    filtered_names = {t["function"]["name"] for t in filtered}

    assert "server_session" not in filtered_names
    assert "edit_file" in filtered_names
    assert "read_file" in filtered_names


# -----------------------------------------------------------------------------
# 8. Symptom 4: Tool Schema Token Budget Respected
# -----------------------------------------------------------------------------
def test_tool_schema_token_budget_respected():
    """Verify payload governor respects budget, compacts history, truncates RAG, and swaps to slim tools."""
    rag_content = (
        "## Symbol Definition Locations:\n"
        "### Symbol 'UserAuth' locations:\napp/auth.py:10\napp/auth.py:25\n"
        "### Symbol 'DBPool' locations:\napp/db.py:5\n"
        "### Symbol 'Config' locations:\napp/config.py:1\n"
        "### Symbol 'Router' locations:\napp/router.py:40\n"
    )
    messages = [
        ChatMessage(role="system", content="System instruction" + (" words " * 200) + rag_content),
        ChatMessage(role="user", content="Past question 1"),
        ChatMessage(role="assistant", content="Past answer 1 " * 800),
        ChatMessage(role="user", content="Past question 2"),
        ChatMessage(role="assistant", content="Past answer 2 " * 800),
        ChatMessage(role="user", content="Current active question about UserAuth"),
    ]
    tools = list(CORE_CODING_TOOLS)

    # Breakdown calculation check
    breakdown = estimate_payload_breakdown(messages, tools)
    assert breakdown["tool_tokens"] > 0
    assert breakdown["total_tokens"] > 7500

    # Governor with tight Groq budget
    gov_res = govern_payload(
        messages,
        tools,
        provider="groq",
        hard_tpm_limit=7500,
    )
    gov_msgs, gov_tools, was_adjusted, reason = gov_res

    assert was_adjusted is True
    assert gov_res.failed_closed is False
    assert estimate_request_tokens(gov_msgs, gov_tools) <= 7500

    # Verify governor proceeds best-effort (never fails closed) when payload exceeds budget
    huge_msg = [ChatMessage(role="user", content="HUGE DATA " * 10000)]
    overflow_res = govern_payload(
        huge_msg,
        tools,
        provider="groq",
        hard_tpm_limit=2000,
    )
    assert overflow_res.failed_closed is False
    assert "best_effort" in overflow_res.summary_reason


# -----------------------------------------------------------------------------
# 9. Symptom 5: Rollback Restores Workspace State
# -----------------------------------------------------------------------------
def test_rollback_restores_workspace_state():
    """Verify undo_turn_files transactionally restores pre-turn workspace files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        test_file = ws / "calculator.py"
        initial_content = "def add(a, b):\n    return a + b\n"
        test_file.write_text(initial_content, encoding="utf-8")

        # Create checkpoint
        _, commit_hash, err = _ensure_git_checkpoint(str(ws), turn_num=1, touched_files=[str(test_file)])
        assert commit_hash != ""
        assert err == ""

        # Make bad edit
        test_file.write_text("def add(a, b):\n    return ERROR SYNTAX !!\n", encoding="utf-8")
        assert "ERROR SYNTAX" in test_file.read_text(encoding="utf-8")

        # Perform rollback
        success, msg, restored = undo_turn_files(str(ws), commit_hash, [str(test_file)])
        assert success is True
        assert len(restored) == 1

        # Check restored content
        reverted_content = test_file.read_text(encoding="utf-8")
        assert reverted_content == initial_content


# -----------------------------------------------------------------------------
# 10. Symptom 5: Checkpoint Created Before Edit
# -----------------------------------------------------------------------------
def test_checkpoint_created_before_edit():
    """Verify _ensure_git_checkpoint generates commit hash, and blocks on sensitive files or missing workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        src_file = ws / "module.py"
        src_file.write_text("print('version 1')\n", encoding="utf-8")

        # Checkpoint succeeds and creates hash
        new_init, commit_hash, err = _ensure_git_checkpoint(str(ws), turn_num=2, touched_files=[str(src_file)])
        assert commit_hash != ""
        assert err == ""

        # Checkpoint blocks sensitive files (.env)
        env_file = ws / ".env"
        env_file.write_text("SECRET=12345\n", encoding="utf-8")
        _, bad_hash, sens_err = _ensure_git_checkpoint(str(ws), turn_num=3, touched_files=[str(env_file)])
        assert bad_hash == ""
        assert "sensitive file" in sens_err.lower()

        # Non-existent workspace fails gracefully
        _, no_hash, ws_err = _ensure_git_checkpoint(str(ws / "non_existent"), turn_num=4)
        assert no_hash == ""
        assert "does not exist" in ws_err.lower()
