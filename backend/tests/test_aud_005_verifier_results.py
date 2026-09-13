"""AUD-005 regressions for verifier result truthfulness and edit breaker resets."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from app.features.ai.chat_harness import ChatAgentRequest, run_chat_agent
from app.features.ai.agents.agent_tools import _handle_run_test
from app.features.ai.harness.payload_governor import GovernanceResult
from app.features.ai.harness.tool_executor import _handle_run_single_test
from app.features.ai.providers.base import ProviderStreamEvent, ProviderToolCall


class _SingleTurnToolProvider:
    """Yield a fixed tool batch once, then finish the chat turn."""

    def __init__(self, tool_calls: tuple[ProviderToolCall, ...]):
        self._tool_calls = tool_calls
        self._sent = False

    async def stream_agent(self, *_args, **_kwargs):
        if not self._sent:
            self._sent = True
            yield ProviderStreamEvent(type="tool_calls", tool_calls=self._tool_calls, finish_reason="stop")
        else:
            yield ProviderStreamEvent(type="text", content="[DONE]", finish_reason="stop")

    async def stream_chat(self, *args, **kwargs):
        async for event in self.stream_agent(*args, **kwargs):
            yield event


def _edit_call(call_id: str, attempt: int) -> ProviderToolCall:
    updated = f"# attempt {attempt}\n"
    return ProviderToolCall(
        id=call_id,
        name="edit_file",
        arguments={"path": "auth.py", "original": "", "updated": updated},
        arguments_json=json.dumps({"path": "auth.py", "original": "", "updated": updated}),
        complete=True,
    )


def _single_test_call(node_id: str) -> ProviderToolCall:
    return ProviderToolCall(
        id="verify",
        name="run_single_test",
        arguments={"node_id": node_id},
        arguments_json=json.dumps({"node_id": node_id}),
        complete=True,
    )


@pytest.mark.asyncio
async def test_run_single_test_returns_failed_tool_result_for_assertion_failure(tmp_path):
    (tmp_path / "test_failure.py").write_text(
        "def test_fails():\n    assert False\n",
        encoding="utf-8",
    )

    result = _handle_run_single_test(str(tmp_path), {"node_id": "test_failure.py::test_fails"})

    assert result.success is False
    assert "FAILED" in result.output
    assert "exit code" in result.error


def test_run_test_rejects_failure_markers_even_with_zero_exit(tmp_path):
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["pytest"],
            returncode=0,
            stdout="================ 1 failed in 0.01s ================",
            stderr="",
        ),
    ):
        result = _handle_run_test(str(tmp_path), {"command": "pytest"})

    assert result.success is False
    assert "output reported failures" in result.error


async def _run_breaker_sequence(tmp_path, test_source: str, test_node: str):
    (tmp_path / "test_verifier.py").write_text(test_source, encoding="utf-8")
    calls = (
        _edit_call("edit-1", 1),
        _single_test_call(test_node),
        _edit_call("edit-2", 2),
        _edit_call("edit-3", 3),
        _edit_call("edit-4", 4),
    )
    request = ChatAgentRequest(
        messages=[{"role": "user", "content": "Fix auth.py"}],
        workspace=str(tmp_path),
        provider="openai",
        model="gpt-4o",
        is_agent_mode=True,
    )
    provider = _SingleTurnToolProvider(calls)
    events: list[str] = []
    def allow_governance(messages, tools, **_kwargs):
        return GovernanceResult(messages, tools, False, "")

    with patch("app.features.ai.chat_harness.provider_for", return_value=provider), \
         patch("app.features.ai.chat_harness._gather_budgeted_rag_context", new=AsyncMock(return_value=([], ""))), \
         patch("app.features.ai.chat_harness.govern_payload", side_effect=allow_governance):
        async for event in run_chat_agent(request):
            events.append(event)
            if "breaker_tripped" in event or sum("tool_result" in item for item in events) >= len(calls):
                break
    return events


@pytest.mark.asyncio
async def test_failed_verification_does_not_reset_repeat_edit_breaker(tmp_path):
    events = await _run_breaker_sequence(
        tmp_path,
        "def test_fails():\n    assert False\n",
        "test_verifier.py::test_fails",
    )

    assert any("breaker_tripped" in event for event in events)


@pytest.mark.asyncio
async def test_passing_verification_resets_repeat_edit_breaker(tmp_path):
    events = await _run_breaker_sequence(
        tmp_path,
        "def test_passes():\n    assert True\n",
        "test_verifier.py::test_passes",
    )

    assert not any("breaker_tripped" in event for event in events)
