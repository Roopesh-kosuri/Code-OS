"""
test_rony_agent_tool_execution.py - Unit and regression tests for Rony Agent tool-execution loop.

Validates:
1. Standard OpenAI tool_calls format parsing
2. OpenAI Harmony channel-token format parsing
3. Plain text described tool call parsing (Java, Python, TS, etc.)
4. Full OpenAI tool schemas matrix sent in provider requests
5. StreamReasoningFilter stripping reasoning from chat bubble tokens
6. Quick-task iteration budget >= 10
7. Self-repair retry loop for intended tool calls
8. End-to-end single-file Java calculator creation in ONE turn with zero continue prompts
9. End-to-end multi-step autonomous execution loop with zero continue prompts
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.harness.plan_parser import (
    _parse_tool_calls_extended,
    _has_tool_calls_extended,
    _parse_harmony_format,
    _parse_described_tool_call,
    _extract_heuristic_tool_calls,
)
from app.features.ai.harness.tool_executor import (
    OPENAI_HARNESS_TOOLS,
    MAX_QUICK_TASK_ITERATIONS,
    HARNESS_TOOLS,
)
from app.features.ai.harness.sse_streamer import StreamReasoningFilter
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest, _pending_approvals, approve_action


def test_parse_standard_openai_tool_call():
    """Verify standard [TOOL_CALL: name] and codeblock tool call parsing."""
    raw_tag_call = (
        '[TOOL_CALL: edit_file]\n'
        '{"path": "src/Calculator.java", "original": "", "updated": "public class Calculator {}"}\n'
        '[/TOOL_CALL]'
    )
    calls = _parse_tool_calls_extended(raw_tag_call)
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "src/Calculator.java"
    assert calls[0].arguments["updated"] == "public class Calculator {}"

    raw_json_block = (
        '```json\n'
        '{\n'
        '  "tool": "run_command",\n'
        '  "arguments": {"command": "javac Calculator.java && java Calculator"}\n'
        '}\n'
        '```'
    )
    calls_json = _parse_tool_calls_extended(raw_json_block)
    assert len(calls_json) == 1
    assert calls_json[0].name == "run_command"
    assert calls_json[0].arguments["command"] == "javac Calculator.java && java Calculator"


def test_parse_harmony_format():
    """Verify OpenAI Harmony channel tokens e.g. <|start|>to=functions.edit_file or commentary to=functions.edit_file."""
    harmony_sample_1 = (
        '<|start|>thought\n'
        'We need to create Calculator.java\n'
        '<|end|>\n'
        '<|start|>to=functions.edit_file\n'
        '{"path": "Calculator.java", "original": "", "updated": "public class Calculator { public static void main(String[] args) {} }"}\n'
        '<|end|>'
    )
    assert _has_tool_calls_extended(harmony_sample_1) is True
    calls = _parse_tool_calls_extended(harmony_sample_1)
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "Calculator.java"
    assert "public class Calculator" in calls[0].arguments["updated"]

    harmony_sample_2 = (
        'commentary to=functions.run_command\n'
        '{"command": "pytest tests/test_calc.py"}'
    )
    calls_2 = _parse_harmony_format(harmony_sample_2)
    assert len(calls_2) == 1
    assert calls_2[0].name == "run_command"
    assert calls_2[0].arguments["command"] == "pytest tests/test_calc.py"


def test_parse_described_tool_call():
    """Verify plain text descriptions of tool calls in Java and other languages."""
    java_narration = (
        'I will create the Calculator.java file with the calculator implementation:\n\n'
        '```java\n'
        'import java.util.Scanner;\n\n'
        'public class Calculator {\n'
        '    public static void main(String[] args) {\n'
        '        System.out.println("Java Calculator");\n'
        '    }\n'
        '}\n'
        '```'
    )
    assert _has_tool_calls_extended(java_narration, "create an file and write an code for calculator in java") is True
    calls = _parse_tool_calls_extended(java_narration, "create an file and write an code for calculator in java")
    assert len(calls) >= 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "Calculator.java"
    assert "public class Calculator" in calls[0].arguments["updated"]

    # Also verify heuristic tool extraction includes Java
    heuristic = _extract_heuristic_tool_calls(java_narration, "create an file and write an code for calculator in java")
    assert len(heuristic) == 1
    assert heuristic[0].name == "edit_file"
    assert heuristic[0].arguments["path"] == "Calculator.java"


def test_tool_schemas_in_request():
    """Verify full tool schema matrix is included in OPENAI_HARNESS_TOOLS for provider requests."""
    tool_names = {t["function"]["name"] for t in OPENAI_HARNESS_TOOLS}
    expected_tools = {
        "edit_file",
        "append_file",
        "read_file",
        "list_directory",
        "search_code",
        "run_command",
        "run_test",
        "list_tests",
        "run_single_test",
        "take_screenshot",
        "ask_user",
        "memory_write",
        "find_references",
        "go_to_definition",
        "git_diff",
    }
    for tool_name in expected_tools:
        assert tool_name in tool_names, f"Tool '{tool_name}' missing from OPENAI_HARNESS_TOOLS"

    for tool in OPENAI_HARNESS_TOOLS:
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert fn["parameters"].get("type") == "object"


def test_reasoning_stripped_from_response():
    """Verify StreamReasoningFilter strips reasoning from token events and routes to thinking events."""
    filter_instance = StreamReasoningFilter()
    token_stream = [
        "<|start|>",
        "thought\nAnalyzing Java requirements and creating Calculator.java\n<|end|>\n",
        "I have created ",
        "Calculator.java successfully."
    ]

    emitted_tokens = []
    emitted_thinking = []

    for token in token_stream:
        for ev_type, ev_content in filter_instance.feed(token):
            if ev_type == "token":
                emitted_tokens.append(ev_content)
            elif ev_type == "thinking":
                emitted_thinking.append(ev_content)

    for ev_type, ev_content in filter_instance.flush():
        if ev_type == "token":
            emitted_tokens.append(ev_content)
        elif ev_type == "thinking":
            emitted_thinking.append(ev_content)

    joined_tokens = "".join(emitted_tokens)
    assert "<|start|>thought" not in joined_tokens
    assert "<|end|>" not in joined_tokens
    assert "Analyzing Java requirements" not in joined_tokens
    assert "I have created Calculator.java successfully." in joined_tokens

    joined_thinking = " ".join(emitted_thinking)
    assert "Analyzing Java requirements" in joined_thinking


def test_quick_task_budget_sufficient():
    """Verify quick task iteration budget is at least 10 for complete create+verify loops."""
    assert MAX_QUICK_TASK_ITERATIONS >= 10, f"MAX_QUICK_TASK_ITERATIONS ({MAX_QUICK_TASK_ITERATIONS}) must be >= 10"


def test_self_repair_retry():
    """Verify described tool call without block is detectable and parser recognizes the file action."""
    narration_with_embedded_json = (
        'We need to emit edit_file call for Calculator.java.\n'
        '{"path": "Calculator.java", "original": "", "updated": "public class Calculator {}"}'
    )
    calls = _parse_described_tool_call(narration_with_embedded_json, "create calculator in java")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "Calculator.java"
    assert calls[0].arguments["updated"] == "public class Calculator {}"


@pytest.mark.asyncio
async def test_e2e_single_file_calculator_java_turn(tmp_path):
    """End-to-end verification: single-file task completes autonomously without continue prompts."""
    ws = str(tmp_path)

    turn1_chunks = [
        "[TOOL_CALL: edit_file]\n",
        '{"path": "Calculator.java", "original": "", "updated": "public class Calculator { public int add(int a, int b) { return a + b; } }"}\n',
        "[/TOOL_CALL]"
    ]
    turn2_chunks = [
        "Calculator.java has been generated.\n[DONE]"
    ]

    async def mock_stream_turn1(*args, **kwargs):
        for c in turn1_chunks:
            yield c

    async def mock_stream_turn2(*args, **kwargs):
        for c in turn2_chunks:
            yield c

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream_turn1(), mock_stream_turn2()])

    async def auto_approver():
        for _ in range(100):
            await asyncio.sleep(0.05)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    await approve_action(act_id)

    req = ChatAgentRequest(
        provider="groq",
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "create an file and write an code for calculator in java"}],
        workspace=ws,
        is_agent_mode=True,
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        with patch("app.features.settings.service.get_api_key", AsyncMock(return_value="mock_key")):
            with patch("app.features.settings.service.list_settings", AsyncMock(return_value={})):
                approver_task = asyncio.create_task(auto_approver())
                events = []
                async for ev in run_chat_agent(req):
                    events.append(ev)
                await approver_task

                # Check proposal was emitted
                proposal_events = [e for e in events if "event: proposal" in e]
                assert len(proposal_events) >= 1
                assert any("Calculator.java" in pe for pe in proposal_events)

                # Check done event
                done_events = [e for e in events if "event: done" in e]
                assert len(done_events) >= 1
                assert '"success": true' in done_events[-1] or '"success":true' in done_events[-1].replace(" ", "")


@pytest.mark.asyncio
async def test_e2e_multi_step_autonomous_loop(tmp_path):
    """End-to-end verification: multi-step project creation runs autonomously with zero continue prompts."""
    ws = str(tmp_path)

    turn1_chunks = [
        "[PLAN]\n1. Create main.py\n2. Create test_main.py\n[/PLAN]\n\n",
        "[TOOL_CALL: edit_file]\n",
        '{"path": "main.py", "original": "", "updated": "def add(a, b): return a + b"}\n',
        "[/TOOL_CALL]",
    ]
    turn2_chunks = [
        "[TOOL_CALL: edit_file]\n",
        '{"path": "test_main.py", "original": "", "updated": "from main import add\ndef test_add(): assert add(2, 3) == 5"}\n',
        "[/TOOL_CALL]",
    ]
    turn3_chunks = [
        "All files created and verified successfully.\n[DONE]",
    ]

    async def mock_stream_turn1(*args, **kwargs):
        for c in turn1_chunks:
            yield c

    async def mock_stream_turn2(*args, **kwargs):
        for c in turn2_chunks:
            yield c

    async def mock_stream_turn3(*args, **kwargs):
        for c in turn3_chunks:
            yield c

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream_turn1(), mock_stream_turn2(), mock_stream_turn3()])

    async def auto_approver():
        for _ in range(100):
            await asyncio.sleep(0.05)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    await approve_action(act_id)

    req = ChatAgentRequest(
        provider="groq",
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "create a Python project with main.py, utils.py, and tests"}],
        workspace=ws,
        is_agent_mode=True,
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        with patch("app.features.settings.service.get_api_key", AsyncMock(return_value="mock_key")):
            with patch("app.features.settings.service.list_settings", AsyncMock(return_value={})):
                approver_task = asyncio.create_task(auto_approver())
                events = []
                async for ev in run_chat_agent(req):
                    events.append(ev)
                await approver_task

                proposal_events = [e for e in events if "event: proposal" in e]
                assert len(proposal_events) >= 1

                done_events = [e for e in events if "event: done" in e]
                assert len(done_events) >= 1
                assert '"success": true' in done_events[-1] or '"success":true' in done_events[-1].replace(" ", "")
