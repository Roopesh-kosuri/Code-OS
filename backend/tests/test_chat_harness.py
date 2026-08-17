"""
Unit tests for the Lightweight Chat Agent Harness (chat_harness.py).
"""
import pytest
import asyncio
from pathlib import Path

from app.features.ai.chat_harness import (
    _is_command_safe,
    _parse_plan,
    _has_escalate_marker,
    _response_is_done,
    _parse_tool_calls_extended,
    _has_tool_calls_extended,
    _execute_command,
    _handle_smart_edit_file,
    _compact_conversation_history,
    approve_action,
    reject_action,
    _pending_approvals,
    PendingApproval,
    _sse_event,
    _sse_status,
    _sse_plan,
    _sse_proposal,
    _sse_done,
    _build_system_prompt,
    SAFE_COMMAND_ALLOWLIST,
    SAFE_COMMAND_PREFIXES,
    HARNESS_TOOLS,
    ChatMessage,
    ToolCall,
)


def test_command_allowlist_strictness():
    """Verify strict allowlist enforcement — only safe read-only commands allowed."""
    # Safe commands
    assert _is_command_safe("ls") is True
    assert _is_command_safe("dir") is True
    assert _is_command_safe("git status") is True
    assert _is_command_safe("git log -n 5") is True
    assert _is_command_safe("git diff HEAD~1") is True
    assert _is_command_safe("cat package.json") is True
    assert _is_command_safe("grep -rn 'foo' src/") is True
    assert _is_command_safe("python --version") is True
    assert _is_command_safe("pip list") is True
    assert _is_command_safe("node --version") is True
    assert _is_command_safe("npm list") is True

    # Dangerous commands — MUST return False
    assert _is_command_safe("rm -rf /") is False
    assert _is_command_safe("rm file.txt") is False
    assert _is_command_safe("del file.txt") is False
    assert _is_command_safe("npm install lodash") is False
    assert _is_command_safe("pip install requests") is False
    assert _is_command_safe("npm run build") is False
    assert _is_command_safe("curl https://example.com") is False
    assert _is_command_safe("wget https://example.com") is False
    assert _is_command_safe("git push origin main") is False
    assert _is_command_safe("git commit -m 'evil'") is False
    assert _is_command_safe("chmod 777 script.sh") is False
    assert _is_command_safe("python evil.py") is False

    # Compound injection commands — MUST return False
    assert _is_command_safe("ls && rm -rf /") is False
    assert _is_command_safe("git status; del file.txt") is False
    assert _is_command_safe("cat file | rm") is False
    assert _is_command_safe("echo test > file.txt") is False
    assert _is_command_safe("echo test >> file.txt") is False
    assert _is_command_safe("`rm -rf /`") is False
    assert _is_command_safe("$(rm -rf /)") is False


def test_parse_plan():
    """Verify [PLAN] block extraction and formatting."""
    response_with_plan = """
I understand the task. Here is the plan:

[PLAN]
1. Read the auth middleware in src/auth.ts
2. Add rate limiting logic with redis
3. Update unit tests in tests/test_auth.ts
4. Run tests to verify
[/PLAN]

Now executing step 1:
[TOOL_CALL: read_file]
{"path": "src/auth.ts"}
[/TOOL_CALL]
"""
    plan = _parse_plan(response_with_plan)
    assert plan is not None
    assert len(plan) == 4
    assert plan[0] == "Read the auth middleware in src/auth.ts"
    assert plan[1] == "Add rate limiting logic with redis"
    assert plan[2] == "Update unit tests in tests/test_auth.ts"
    assert plan[3] == "Run tests to verify"

    # No plan
    assert _parse_plan("Just a quick fix.\n[DONE]") is None


def test_escalation_marker_detection():
    """Verify [ESCALATE] marker detection."""
    assert _has_escalate_marker("This is too complex. [ESCALATE]") is True
    assert _has_escalate_marker("Everything looks good. [DONE]") is False


def test_response_is_done():
    """Verify [DONE] marker detection."""
    assert _response_is_done("I have finished all tasks.\n[DONE]") is True
    assert _response_is_done("Still working on it...") is False


def test_tool_calls_parsing_extended():
    """Verify extended tool calls parsing (including semantic_search and run_command)."""
    response = """
Let's find the files and inspect the directory:
[TOOL_CALL: semantic_search]
{"query": "authentication token validation"}
[/TOOL_CALL]

[TOOL_CALL: run_command]
{"command": "git status"}
[/TOOL_CALL]

[TOOL_CALL: read_file]
{"path": "src/auth.py", "start_line": 1, "limit": 100}
[/TOOL_CALL]
"""
    assert _has_tool_calls_extended(response) is True
    calls = _parse_tool_calls_extended(response)
    assert len(calls) == 3
    assert calls[0].name == "semantic_search"
    assert calls[0].arguments["query"] == "authentication token validation"
    assert calls[1].name == "run_command"
    assert calls[1].arguments["command"] == "git status"
    assert calls[2].name == "read_file"
    assert calls[2].arguments["path"] == "src/auth.py"


def test_smart_edit_file_pre_validation(tmp_path):
    """Verify edit_file verifies original content before staging."""
    ws = str(tmp_path)
    test_file = tmp_path / "calc.py"
    test_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    staged = []
    # 1. Successful exact edit
    res_ok = _handle_smart_edit_file(
        ws,
        {"path": "calc.py", "original": "return a + b", "updated": "return int(a) + int(b)"},
        staged,
    )
    assert res_ok.success is True
    assert len(staged) == 1
    assert staged[0].path == "calc.py"

    # 2. Rejection of hallucinated original text
    staged_fail = []
    res_fail = _handle_smart_edit_file(
        ws,
        {"path": "calc.py", "original": "def non_existent_fn(): pass", "updated": "def new_fn(): pass"},
        staged_fail,
    )
    assert res_fail.success is False
    assert len(staged_fail) == 0
    assert "was not found verbatim" in res_fail.error

    # 3. New file creation (original is empty)
    staged_new = []
    res_new = _handle_smart_edit_file(
        ws,
        {"path": "new_mod.py", "original": "", "updated": "def hello(): return 1\n"},
        staged_new,
    )
    assert res_new.success is True
    assert len(staged_new) == 1


def test_compact_conversation_history():
    """Verify older tool results are compacted to save tokens."""
    messages = [
        ChatMessage(role="system", content="System instructions"),
        ChatMessage(role="user", content="Initial user request"),
        ChatMessage(role="assistant", content="Calling read_file [TOOL_CALL: read_file]..."),
        ChatMessage(role="user", content="Tool results:\n\n[TOOL_RESULT: read_file]\n" + ("line\n" * 500) + "[/TOOL_RESULT]"),
        ChatMessage(role="assistant", content="Calling edit_file..."),
        ChatMessage(role="user", content="Tool results:\n\n[TOOL_RESULT: edit_file]\nStaged change[/TOOL_RESULT]"),
        ChatMessage(role="assistant", content="Final answer"),
    ]
    # Compact with keep_recent_turns=1
    compacted = _compact_conversation_history(messages, keep_recent_turns=1)
    assert len(compacted) == len(messages)
    # The older tool result (index 3) should be compacted
    assert "compacted to save context tokens" in compacted[3].content
    assert len(compacted[3].content) < 200


@pytest.mark.asyncio
async def test_interactive_approval_flow():
    """Verify async approve_action and reject_action mechanisms."""
    action_id = "test-act-123"
    pending = PendingApproval(
        action_id=action_id,
        action_type="command",
        detail="npm install axios",
        reason="Not allowlisted",
    )
    _pending_approvals[action_id] = pending

    # Approve
    res = await approve_action(action_id)
    assert res is True
    assert pending.approved is True
    assert pending.event.is_set()

    # Reject
    pending2 = PendingApproval(
        action_id="test-act-456",
        action_type="command",
        detail="del main.py",
        reason="Not allowlisted",
    )
    _pending_approvals["test-act-456"] = pending2
    res2 = await reject_action("test-act-456")
    assert res2 is True
    assert pending2.approved is False
    assert pending2.event.is_set()

    # Non-existent action
    assert await approve_action("unknown-id") is False


def test_sse_event_formatting():
    """Verify SSE serialization."""
    event = _sse_status("thinking", "Analyzing codebase...")
    assert event.startswith("event: status\n")
    assert '"type": "thinking"' in event
    assert '"message": "Analyzing codebase..."' in event
    assert event.endswith("\n\n")

    plan_event = _sse_plan(["Step 1", "Step 2"], 0)
    assert plan_event.startswith("event: plan\n")
    assert '"steps": ["Step 1", "Step 2"]' in plan_event

    done_event = _sse_done(True, "All done")
    assert done_event.startswith("event: done\n")
    assert '"success": true' in done_event


def test_declares_tool_intent():
    """Verify detection of responses declaring tool intent without tool blocks."""
    from app.features.ai.chat_harness import _declares_tool_intent
    assert _declares_tool_intent("We need to run tests. Use run_test tool.") is True
    assert _declares_tool_intent("Let's run pytest on tests/test_generation.py") is True
    assert _declares_tool_intent("I will run git status to check modified files") is True
    assert _declares_tool_intent("Python is a popular programming language.") is False


def test_system_prompt_builder():
    """Verify system prompt construction with context and semantic search."""
    context = {
        "git_status": {"branch": "main", "dirty": True, "unstaged": ["file1.py"]},
        "active_file": {"name": "main.py", "content": "print('hello')"},
        "dependencies": [{"name": "fastapi", "version": "0.100.0"}],
        "readme": "# My Project",
    }
    semantic_results = [
        {"relative_path": "src/auth.py", "score": 0.85, "language": "python"}
    ]
    prompt = _build_system_prompt("/workspace/test", context, semantic_results)
    
    assert "You are Rony Agent" in prompt
    assert "/workspace/test" in prompt
    assert "Git branch: main" in prompt
    assert "src/auth.py" in prompt
    assert "score: 0.850" in prompt
    assert "fastapi@0.100.0" in prompt


@pytest.mark.asyncio
async def test_tool_sandbox_execution(tmp_path):
    """Test tool execution with sandboxed temporary directory."""
    from app.features.ai.agents.agent_tools import _handle_read_file, _handle_list_directory
    ws = str(tmp_path)
    test_file = tmp_path / "hello.py"
    test_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    res_read = _handle_read_file(ws, {"path": "hello.py"})
    assert res_read.success is True
    assert "def hello():" in res_read.output

    res_list = _handle_list_directory(ws, {"path": "."})
    assert res_list.success is True
    assert "hello.py" in res_list.output

    res_cmd = _execute_command(ws, "echo test")
    assert res_cmd.success is True


def test_generate_diff_summary():
    """Verify unified diff preview generated for inline approval card."""
    from app.features.ai.chat_harness import _generate_diff_summary
    from app.features.ai.schemas import FileChange

    # 1. Modified file
    change_mod = FileChange(
        path="src/config.py",
        original="TIMEOUT = 30\nDEBUG = False\n",
        updated="TIMEOUT = 60\nDEBUG = True\n",
    )
    diff_mod = _generate_diff_summary(change_mod)
    assert "--- a/src/config.py" in diff_mod
    assert "+++ b/src/config.py" in diff_mod
    assert "-TIMEOUT = 30" in diff_mod
    assert "+TIMEOUT = 60" in diff_mod

    # 2. New file
    change_new = FileChange(
        path="src/new.py",
        original="",
        updated="def test(): pass\n",
    )
    diff_new = _generate_diff_summary(change_new)
    assert "+++ b/src/new.py" in diff_new
    assert "+def test(): pass" in diff_new


def test_edit_approval_sse_event():
    """Verify approval_request SSE payload includes proposal details."""
    from app.features.ai.chat_harness import _sse_approval_request

    event = _sse_approval_request(
        action_id="act-edit-1",
        action_type="edit",
        detail="src/config.py",
        reason="Rony Agent wants to modify src/config.py",
        proposal_id="prop-abc-123",
        path="src/config.py",
        diff_summary="+ TIMEOUT = 60",
    )
    assert "event: approval_request" in event
    assert '"action_type": "edit"' in event
    assert '"proposal_id": "prop-abc-123"' in event
    assert '"path": "src/config.py"' in event
    assert '"diff_summary": "+ TIMEOUT = 60"' in event
