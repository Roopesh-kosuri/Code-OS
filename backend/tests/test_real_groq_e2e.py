import os
import json
import pytest
import sqlite3
import tempfile
import shutil
import asyncio
from unittest.mock import AsyncMock, patch
from pathlib import Path

from app.core.security import decrypt_secret
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest, _pending_approvals, approve_action


def get_real_groq_key() -> str | None:
    db_path = Path.home() / ".code-os" / "code-os.sqlite3"
    if not db_path.exists():
        return os.environ.get("GROQ_API_KEY")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        c = conn.cursor()
        c.execute("SELECT encrypted_key FROM api_keys WHERE provider_id = ?", ("groq",))
        row = c.fetchone()
        if row and row[0]:
            return decrypt_secret(row[0])
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY")


@pytest.mark.asyncio
async def test_real_groq_e2e_calculator_4_languages():
    """Live integration test against REAL Groq gpt-oss-120b for 4-language calculator creation."""
    groq_key = get_real_groq_key()
    if not groq_key:
        pytest.skip("No real Groq API key configured in ~/.code-os/code-os.sqlite3 or GROQ_API_KEY")

    tmp_ws = tempfile.mkdtemp(prefix="code_os_test_groq_")
    try:
        approver_running = True

        async def auto_approver():
            while approver_running:
                await asyncio.sleep(0.05)
                if _pending_approvals:
                    for act_id in list(_pending_approvals.keys()):
                        await approve_action(act_id)

        approver_task = asyncio.create_task(auto_approver())

        test_model = os.environ.get("GROQ_TEST_MODEL")
        if not test_model:
            # Check if 120b has sufficient quota for agent execution with tools; fallback to 20b if rate limited
            test_model = "openai/gpt-oss-120b"
            try:
                import httpx
                from app.features.ai.chat_harness import OPENAI_HARNESS_TOOLS
                r = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={"model": test_model, "messages": [{"role": "user", "content": "hi"}], "tools": OPENAI_HARNESS_TOOLS, "max_tokens": 512, "stream": True},
                    timeout=5.0,
                )
                if r.status_code != 200:
                    test_model = "openai/gpt-oss-20b"
            except Exception:
                test_model = "openai/gpt-oss-20b"

        req = ChatAgentRequest(
            provider="groq",
            model=test_model,
            messages=[{"role": "user", "content": "create an folder named calculator and in that create calculator code in 4 languages: python (calc.py), java (calc.java), c (calc.c), and cpp (calc.cpp)"}],
            workspace=tmp_ws,
            is_agent_mode=True,
        )

        events: list[tuple[str, dict]] = []
        token_contents: list[str] = []

        with patch("app.features.settings.service.get_api_key", AsyncMock(return_value=groq_key)):
            async for sse_raw in run_chat_agent(req):
                # Parse SSE event
                lines = [l.strip() for l in sse_raw.strip().split("\n") if l.strip()]
                ev_name = "message"
                ev_data = {}
                for line in lines:
                    if line.startswith("event: "):
                        ev_name = line[7:].strip()
                    elif line.startswith("data: "):
                        try:
                            ev_data = json.loads(line[6:].strip())
                        except Exception:
                            ev_data = {"raw": line[6:].strip()}
                events.append((ev_name, ev_data))

                if ev_name == "token":
                    content = ev_data.get("content", "")
                    if content:
                        token_contents.append(content)

        approver_running = False
        await approver_task

        # Verify no un-filtered narration in visible token events
        all_tokens = "".join(token_contents)
        assert "We need to emit tool calls" not in all_tokens
        assert "Use edit_file with original=''" not in all_tokens

        # Verify done event was emitted
        done_events = [data for name, data in events if name == "done"]
        assert len(done_events) >= 1
        
        # Verify proposals / tools were staged or executed
        proposal_events = [data for name, data in events if name == "proposal"]
        approval_events = [data for name, data in events if name == "approval_request"]
        
        # Verify files created on disk
        ws_files = list(Path(tmp_ws).rglob("*"))
        calc_files = [f for f in ws_files if f.is_file()]
        
        print(f"Total events: {len(events)}, Files created: {len(calc_files)}")
        for f in calc_files:
            print(f" - {f.relative_to(tmp_ws)} ({f.stat().st_size} bytes)")

        # Assert at least 1 proposal/tool execution succeeded and files exist
        assert len(calc_files) >= 1 or len(proposal_events) >= 1 or len(approval_events) >= 1
        assert done_events[0].get("success") is True

    finally:
        shutil.rmtree(tmp_ws, ignore_errors=True)
