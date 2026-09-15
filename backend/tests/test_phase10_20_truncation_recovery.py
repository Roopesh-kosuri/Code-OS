import pytest
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.harness.compaction_manager import (
    _is_response_truncated,
    PATCH_STYLE_RETRY_DIRECTIVE,
    format_truncation_exhausted_error,
)
from app.features.ai.harness.patch_applicator import apply_atomic_patch_sequence
from app.features.ai.harness.size_guard import (
    check_rewrite_size_guard,
    is_whole_file_rewrite_intent,
    LARGE_REWRITE_LINE_THRESHOLD,
)
from app.features.ai.agents.agent_tools import execute_tool_calls, ToolCall
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest
from app.features.ai.schemas import FileChange


def test_truncated_tool_call_detected():
    """Deliverable 1: Truncation detector covering all 4 truncation forms:
    1. Provider finish_reason == 'length' / 'max_tokens'
    2. Incomplete tool-call JSON (unbalanced braces/quotes, unterminated strings)
    3. Unbalanced proposal markers ([PROPOSAL: without closing >>>>)
    4. edit_file payload where UPDATED ends mid-line or mid-block.
    """
    # 1. finish_reason == 'length'
    assert _is_response_truncated("Thinking...", finish_reason="length") is True
    assert _is_response_truncated("Thinking...", finish_reason="max_tokens") is True
    assert _is_response_truncated("Thinking...", finish_reason="stop") is False

    # 2. Incomplete tool-call JSON
    # 2a. Unclosed [TOOL_CALL: ...] tag
    unclosed_tag = "I will edit the file:\n[TOOL_CALL: edit_file]\n{\"path\": \"main.py\""
    assert _is_response_truncated(unclosed_tag) is True

    # 2b. Unbalanced braces inside tool call
    unbalanced_braces = '[TOOL_CALL: edit_file]\n{"path": "main.py", "original": "", "updated": "def login():\n[/TOOL_CALL]'
    assert _is_response_truncated(unbalanced_braces) is True

    # 2c. Unbalanced double quotes / unterminated string
    unterminated_str = '[TOOL_CALL: edit_file]\n{"path": "main.py", "original": "pass", "updated": "def login(): print(\\"cut\n[/TOOL_CALL]'
    assert _is_response_truncated(unterminated_str) is True

    # 2d. Incomplete markdown codeblock tool call
    broken_codeblock = "```tool_call\n{\"name\": \"edit_file\", \"arguments\": {\"path\": \"main.py\", \"updated\": \"cut off\n```"
    assert _is_response_truncated(broken_codeblock) is True

    # 3. Unbalanced proposal markers
    unclosed_proposal = "[PROPOSAL: main.py]\n<<<< ORIGINAL\ndef foo():\n    pass\n====\ndef foo():\n    return 42\n"
    assert _is_response_truncated(unclosed_proposal) is True

    well_closed_proposal = "[PROPOSAL: main.py]\n<<<< ORIGINAL\ndef foo():\n    pass\n====\ndef foo():\n    return 42\n>>>>"
    assert _is_response_truncated(well_closed_proposal) is False

    # 4. edit_file payload where UPDATED ends mid-line / mid-block
    truncated_updated = '[TOOL_CALL: edit_file]\n{"path": "main.py", "original": "", "updated": "def login():\\n    return "}\n[/TOOL_CALL]'
    assert _is_response_truncated(truncated_updated) is True

    # Negative control: complete, well-formed tool call
    complete_call = '[TOOL_CALL: edit_file]\n{"path": "main.py", "original": "x = 1\\n", "updated": "x = 2\\n"}\n[/TOOL_CALL]'
    assert _is_response_truncated(complete_call) is False

    # Negative control: complete conversational prose
    assert _is_response_truncated("Here is the completed code. [DONE]") is False


@pytest.mark.asyncio
async def test_recovery_retries_patch_style_and_succeeds(tmp_path):
    """Deliverable 2: Truncated on Turn 1 -> receives injected patch-style directive -> succeeds on Turn 2."""
    workspace = str(tmp_path)
    main_file = tmp_path / "main.py"
    main_file.write_text("def index():\n    return 'home'\n", encoding="utf-8")

    turn_count = 0
    received_user_prompts: list[str] = []
    mock_provider = MagicMock()

    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        messages = args[1] if len(args) > 1 else kwargs.get("messages", [])
        for m in messages:
            if getattr(m, "role", "") == "user":
                received_user_prompts.append(getattr(m, "content", ""))

        if turn_count == 1:
            # Turn 1: Truncated mid-response
            yield "I will implement the login system:\n[TOOL_CALL: edit_file]\n{\"path\": \"main.py\", \"original\": \"\", \"updated\": \"def login():\n[TRUNCATED: length]"
        else:
            # Turn 2: Follows patch-style directive with small surgical edit
            yield (
                "Here is the patch-style edit:\n"
                "[TOOL_CALL: edit_file]\n"
                "{\"path\": \"main.py\", \"original\": \"def index():\\n    return 'home'\\n\", \"updated\": \"def index():\\n    return 'home'\\n\\ndef login():\\n    return 'logged in'\\n\"}\n"
                "[/TOOL_CALL]\n"
                "Done! [DONE]"
            )

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="meta/llama-3.2-11b",
        workspace=workspace,
        messages=[{"role": "user", "content": "edit main.py by writing a code of login system inside it"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.create_proposal", AsyncMock(return_value=MagicMock(id="prop-phase10-20"))), \
         patch("app.features.ai.service.apply_proposal", AsyncMock()):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)
            if "approval_request" in event:
                match = re.search(r'"action_id":\s*"([^"]+)"', event)
                if match:
                    from app.features.ai.chat_harness import approve_action
                    await approve_action(match.group(1))

        # 1. Verify injected directive was sent to model on retry
        assert any(
            "Your previous output exceeded the model output limit. Do NOT rewrite whole files." in prompt
            for prompt in received_user_prompts
        ), "Expected patch-style directive in injected retry prompt"

        # 2. Verify status indicated patch-style retry
        status_events = [e for e in events if "event: status" in e]
        assert any("patch-style edits" in s for s in status_events)

        # 3. Verify turn completed with success
        done_events = [e for e in events if "event: done" in e]
        assert any('"success": true' in d or '"success":true' in d for d in done_events)


def test_patch_sequence_applies_atomically_with_rollback(tmp_path):
    """Deliverable 3: Multiple sequential edit_file calls apply as ONE atomic unit.
    If any patch fails (e.g. syntax error in Patch 2), ALL touched files roll back
    to the pre-turn checkpoint.
    """
    workspace = str(tmp_path)
    server_file = tmp_path / "server.py"
    initial_content = "def get_status():\n    return 'down'\n\ndef get_port():\n    return 3000\n"
    server_file.write_text(initial_content, encoding="utf-8")

    staged: list[FileChange] = []
    patches = [
        # Patch 1: Valid edit
        {
            "path": "server.py",
            "original": "def get_status():\n    return 'down'\n",
            "updated": "def get_status():\n    return 'up'\n",
        },
        # Patch 2: Syntax error (missing closing paren and colon)
        {
            "path": "server.py",
            "original": "def get_port():\n    return 3000\n",
            "updated": "def get_port(:\n    return 8080\n",
        },
    ]

    ok, reason, restored = apply_atomic_patch_sequence(workspace, patches, turn_number=1, staged_changes=staged)
    assert ok is False
    assert "syntax error" in reason.lower()
    assert "rolled back" in reason.lower()

    # Verify server.py was restored byte-for-byte to initial content
    assert server_file.read_text(encoding="utf-8") == initial_content


def test_patch_original_mismatch_after_earlier_patch_rejected(tmp_path):
    """Deliverable 3 & E3.2: Re-read on-disk bytes between patches.
    If Patch 2's original mismatches disk (e.g. hallucinated lines), Patch 2 is rejected,
    Patch 1 is rolled back, and disk is restored.
    """
    workspace = str(tmp_path)
    math_file = tmp_path / "math_ops.py"
    initial_content = "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n"
    math_file.write_text(initial_content, encoding="utf-8")

    staged: list[FileChange] = []
    patches = [
        # Patch 1: Valid edit
        {
            "path": "math_ops.py",
            "original": "def add(a, b):\n    return a + b\n",
            "updated": "def add(a, b):\n    # log add\n    return a + b\n",
        },
        # Patch 2: original does not exist in file
        {
            "path": "math_ops.py",
            "original": "def multiply(a, b):\n    return a * b\n",
            "updated": "def multiply(a, b):\n    return a * b * 2\n",
        },
    ]

    ok, reason, restored = apply_atomic_patch_sequence(workspace, patches, turn_number=1, staged_changes=staged)
    assert ok is False
    assert "original_mismatches_disk" in reason or "does not match" in reason
    assert "rolled back" in reason.lower()

    # Disk must be restored completely to initial state
    assert math_file.read_text(encoding="utf-8") == initial_content


@pytest.mark.asyncio
async def test_final_failure_message_honest_and_actionable(tmp_path):
    """Deliverable 2 & Repro: Max 2 retries. If still truncated after 2 retries,
    emit honest, actionable error:
    "This change is too large for <model>'s single-response output window. Options: retry with incremental patch edits / switch to a larger model / run as Deep Task."
    NEVER show "chunking required" or blame prompt size.
    """
    workspace = str(tmp_path)
    model_name = "meta/llama-3.2-11b"

    # Always truncated provider stream
    mock_provider = MagicMock()
    async def mock_truncated_stream(*args, **kwargs):
        yield "Generating code...\n[TOOL_CALL: edit_file]\n{\"path\": \"app.py\", \"updated\": \"def login():\n[TRUNCATED: length]"

    mock_provider.stream_chat = mock_truncated_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model=model_name,
        workspace=workspace,
        messages=[{"role": "user", "content": "write a login system inside main.py"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)

        full_output = "".join(events)

        # 1. Verify expected honest actionable message
        expected_error = format_truncation_exhausted_error(model_name)
        assert expected_error in full_output, f"Expected honest error '{expected_error}' in output, got: {full_output}"

        # 2. Never show "chunking required"
        assert "chunking required" not in full_output.lower()

        # 3. Done event reports failure honestly
        done_events = [e for e in events if "event: done" in e]
        assert any('"success": false' in d or '"success":false' in d for d in done_events)


def test_large_rewrite_forces_patch_mode(caplog):
    """Deliverable 4: If single edit_file UPDATED payload exceeds ~60 lines,
    harness proactively forces patch-style mode, logs 'large_rewrite_forced_patch',
    and auto-suggests tier upgrade for Quick Task.
    """
    import logging
    caplog.set_level(logging.INFO)

    # 1. Generate a 75-line payload (>60 lines)
    large_payload = "\n".join(f"line_{i} = {i}" for i in range(75))
    path = "large_module.py"
    query = "edit main.py by writing a code of login system inside it"

    exceeded, reason, suggestion = check_rewrite_size_guard(
        path=path,
        updated=large_payload,
        tier=1,
        query=query,
    )

    # Assert guard tripped
    assert exceeded is True
    assert reason is not None
    assert f"Large rewrite detected (75 lines > {LARGE_REWRITE_LINE_THRESHOLD})" in reason
    assert "patch-style mode" in reason

    # Assert logged "large_rewrite_forced_patch"
    assert any("large_rewrite_forced_patch" in record.message for record in caplog.records)

    # Assert tier upgrade suggestion
    assert suggestion is not None
    assert suggestion["suggested_tier"] == 2
    assert suggestion["message"] == "This looks like a multi-part change — run as Deep Task?"

    # Verify query intent helper directly
    assert is_whole_file_rewrite_intent("edit main.py by writing a code of login system inside it", tier=1) is True
    assert is_whole_file_rewrite_intent("fix typo in line 5", tier=1) is False
