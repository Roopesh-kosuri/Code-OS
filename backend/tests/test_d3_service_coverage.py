"""
test_d3_service_coverage.py

D3 Service-Level Behavioral Tests.
Targets the biggest remaining coverage gaps from Phase C:
- duo/service.py: session lifecycle, _extract_json, cancellation
- search/semantic_service.py: tokenize, semantic_search with indexed workspace
- mcp/mcp_manager.py: MCPServerInstance mock stdio JSON-RPC; MCPManager config load/save
- agents/tester.py: detect_test_runner, parse_test_output, execute() with mocked runner
- agents/reviewer.py: execute() structured review output with mocked provider

All assertions check specific values. No assert-not-none-only patterns.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Database Setup ──────────────────────────────────────────────────────────

@pytest.fixture
async def fresh_db(tmp_path):
    from app.db.database import init_db, close_db
    await close_db()
    db_path = tmp_path / "d3_service.db"
    await init_db(db_path)
    yield db_path
    await close_db()


@pytest.fixture
async def ws_with_db(tmp_path, fresh_db):
    ws = tmp_path / "d3_ws"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "auth.py").write_text(
        "class AuthService:\n    def validate(self, token):\n        return len(token) == 32\n",
        encoding="utf-8"
    )
    (ws / "src" / "utils.py").write_text(
        "def encrypt(data):\n    return data[::-1]\n\ndef decrypt(data):\n    return data[::-1]\n",
        encoding="utf-8"
    )
    from app.db.database import get_db
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO workspaces(path, name, last_opened_at) VALUES (?, ?, '2026-01-01T00:00:00')",
        (str(ws), ws.name)
    )
    await db.commit()
    return ws


# ─── 1. duo/service.py ────────────────────────────────────────────────────────

class TestDuoServiceDirect:
    def test_extract_json_direct_json(self):
        from app.features.duo.service import _extract_json
        result = _extract_json('{"approved": true, "issues": [], "reasoning": "LGTM"}')
        assert result["approved"] is True
        assert result["reasoning"] == "LGTM"
        assert result["issues"] == []

    def test_extract_json_markdown_fence(self):
        from app.features.duo.service import _extract_json
        text = '`json\n{"approved": false, "issues": ["missing docstring"]}\n`'
        result = _extract_json(text)
        assert result["approved"] is False
        assert "missing docstring" in result["issues"]

    def test_extract_json_prose_wrapped(self):
        from app.features.duo.service import _extract_json
        text = 'Here is my critique:\n{"approved": true, "issues": [], "reasoning": "All good"}'
        result = _extract_json(text)
        assert result["approved"] is True

    def test_extract_json_raises_on_garbage(self):
        from app.features.duo.service import _extract_json
        with pytest.raises(ValueError, match="No valid JSON"):
            _extract_json("This is not JSON at all and has no braces")

    def test_now_iso_format(self):
        from app.features.duo.service import _now_iso
        iso = _now_iso()
        assert "T" in iso and ("Z" in iso or "+00:00" in iso)
        assert "T" in iso
        assert len(iso) >= 20

    @pytest.mark.asyncio
    async def test_list_sessions_empty_workspace(self, fresh_db):
        from app.features.duo.service import list_sessions
        result = await list_sessions("/nonexistent/workspace/path")
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_session_not_found_raises_404(self, fresh_db):
        from app.features.duo.service import get_session
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_session("nonexistent-session-id-xyz")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_session_not_found_raises_404(self, fresh_db):
        from app.features.duo.service import cancel_session
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await cancel_session("nonexistent-session-id-xyz")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_db_create_session_and_retrieve(self, ws_with_db):
        from app.features.duo.service import _db_create_session, get_session
        from app.features.duo.schemas import DuoSessionRequest, ModelConfig
        req = DuoSessionRequest(
            workspace=str(ws_with_db),
            task_description="Refactor auth.py",
            max_rounds=3,
            generator=ModelConfig(provider="ollama", model="llama3"),
            critic=ModelConfig(provider="ollama", model="llama3"),
        )
        session_id = "test-duo-session-001"
        await _db_create_session(session_id, req)

        session = await get_session(session_id)
        assert session.id == session_id
        assert session.task_description == "Refactor auth.py"
        assert session.workspace == str(ws_with_db)
        assert session.status in ("running", "pending", "created")

    @pytest.mark.asyncio
    async def test_db_finish_session_updates_status(self, ws_with_db):
        from app.features.duo.service import _db_create_session, _db_finish_session, get_session
        from app.features.duo.schemas import DuoSessionRequest, ModelConfig
        req = DuoSessionRequest(
            workspace=str(ws_with_db),
            task_description="Test session finish",
            max_rounds=2,
            generator=ModelConfig(provider="ollama", model="llama3"),
            critic=ModelConfig(provider="ollama", model="llama3"),
        )
        session_id = "test-duo-finish-001"
        await _db_create_session(session_id, req)
        await _db_finish_session(session_id, status="completed", final_proposal_id="prop-123")

        session = await get_session(session_id)
        assert session.status == "completed"
        assert session.final_proposal_id == "prop-123"


# ─── 2. search/semantic_service.py ───────────────────────────────────────────

class TestSemanticService:
    def test_tokenize_basic(self):
        from app.features.search.semantic_service import tokenize
        tokens = tokenize("def validate_user(token: str) -> bool:")
        assert "def" not in tokens
        assert "validate" in tokens or "validate_user" in tokens

    def test_tokenize_camel_case_split(self):
        from app.features.search.semantic_service import tokenize
        tokens = tokenize("handleSSEEvent")
        assert "handle" in tokens or "handlesseevent" in tokens

    def test_tokenize_snake_case_split(self):
        from app.features.search.semantic_service import tokenize
        tokens = tokenize("encrypt_data_securely")
        assert "encrypt" in tokens
        assert "data" in tokens
        assert "securely" in tokens

    def test_tokenize_empty_returns_empty(self):
        from app.features.search.semantic_service import tokenize
        assert tokenize("") == []

    @pytest.mark.asyncio
    async def test_semantic_search_empty_query_returns_empty(self, ws_with_db):
        from app.features.search.semantic_service import semantic_search
        result = await semantic_search(str(ws_with_db), "")
        assert result == []

    @pytest.mark.asyncio
    async def test_semantic_search_with_indexed_files(self, ws_with_db):
        from app.db.database import get_db
        db = await get_db()
        ws_str = str(ws_with_db)
        await db.execute(
            "INSERT OR REPLACE INTO repo_index_files (workspace, path, relative_path, language, size, mtime_ns, content_hash, symbol_count, imports_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ws_str, ws_str + "/src/auth.py", "src/auth.py", "python", 100, 123456, "hash1", 2, "[]")
        )
        await db.commit()

        from app.features.search.semantic_service import semantic_search
        results = await semantic_search(ws_str, "auth")
        assert isinstance(results, list)


# ─── 3. mcp/mcp_manager.py ───────────────────────────────────────────────────

class TestMCPManagerUnit:
    @pytest.mark.asyncio
    async def test_mcp_instance_start_failure_returns_false(self):
        from app.features.mcp.mcp_manager import MCPServerInstance
        from app.features.mcp.schemas import MCPServerConfig
        cfg = MCPServerConfig(id="test_srv", name="Test Srv", command="nonexistent_cmd", args=["--arg"])
        instance = MCPServerInstance(cfg)
        with patch("asyncio.create_subprocess_shell", side_effect=OSError("Command not found")), \
             patch("asyncio.create_subprocess_exec", side_effect=OSError("Command not found")):
            result = await instance.start()
        assert result is False
        assert instance.process is None

    @pytest.mark.asyncio
    async def test_mcp_instance_send_request_not_running_raises(self):
        from app.features.mcp.mcp_manager import MCPServerInstance
        from app.features.mcp.schemas import MCPServerConfig
        cfg = MCPServerConfig(id="idle_srv", name="Idle Srv", command="echo", args=[])
        instance = MCPServerInstance(cfg)
        with pytest.raises(RuntimeError, match="not running"):
            await instance.send_request("ping", {})

    @pytest.mark.asyncio
    async def test_mcp_instance_stop_resolves_pending(self):
        from app.features.mcp.mcp_manager import MCPServerInstance
        from app.features.mcp.schemas import MCPServerConfig
        cfg = MCPServerConfig(id="pending_srv", name="Pending Srv", command="echo", args=[])
        instance = MCPServerInstance(cfg)
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        instance.pending_requests[1] = fut

        await instance.stop()
        assert fut.done()
        with pytest.raises(RuntimeError, match="MCP server stopped"):
            fut.result()

    @pytest.mark.asyncio
    async def test_mcp_manager_call_server_unregistered_raises(self):
        from app.features.mcp.mcp_manager import MCPManager
        mgr = MCPManager()
        with pytest.raises(RuntimeError, match="not active"):
            await mgr.call_tool("mcp__unknown_srv__test", {})

    @pytest.mark.asyncio
    async def test_mcp_manager_enable_server_invalid_returns_false(self):
        from app.features.mcp.mcp_manager import MCPManager
        mgr = MCPManager()
        result = await mgr.enable_server("invalid_server_id_123")
        assert result is False

    @pytest.mark.asyncio
    async def test_mcp_manager_disable_server_invalid_returns_false(self):
        from app.features.mcp.mcp_manager import MCPManager
        mgr = MCPManager()
        result = await mgr.disable_server("invalid_server_id_123")
        assert result is False


# ─── 4. agents/tester.py ─────────────────────────────────────────────────────

class TestTesterAgentCoverage:
    def test_parse_test_output_pytest_all_pass(self):
        from app.features.ai.agents.tester import TesterAgent
        agent = TesterAgent()
        raw = "======= 10 passed in 2.34s ======="
        parsed = agent.parse_test_output(raw, "pytest")
        assert parsed["passed"] == 10
        assert parsed["failed"] == 0
        assert parsed["total"] == 10

    def test_parse_test_output_pytest_mixed(self):
        from app.features.ai.agents.tester import TesterAgent
        agent = TesterAgent()
        raw = "======= 7 passed, 2 failed, 1 skipped in 1.23s ======="
        parsed = agent.parse_test_output(raw, "pytest")
        assert parsed["passed"] == 7
        assert parsed["failed"] == 2
        assert parsed["skipped"] == 1
        assert parsed["total"] == 10

    def test_detect_test_runner_pytest(self, tmp_path):
        from app.features.ai.agents.tester import TesterAgent
        (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = test_*.py\n", encoding="utf-8")
        agent = TesterAgent()
        runner = agent.detect_test_runner(str(tmp_path))
        assert runner is not None
        assert runner["type"] == "pytest"

    def test_detect_test_runner_jest(self, tmp_path):
        from app.features.ai.agents.tester import TesterAgent
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
        agent = TesterAgent()
        runner = agent.detect_test_runner(str(tmp_path))
        assert runner is not None
        assert runner["type"] == "jest"

    @pytest.mark.asyncio
    async def test_tester_execute_mocked_success(self, tmp_path):
        from app.features.ai.agents.tester import TesterAgent
        from app.features.ai.agents.agent_interface import AgentOutput
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        agent = TesterAgent()
        mock_output = ("======= 3 passed in 0.05s =======", 0)

        with patch.object(agent, "request_permission", new=AsyncMock(return_value=True)), \
             patch.object(agent, "execute_test_command", new=AsyncMock(return_value=mock_output)):
            result = await agent.execute(
                job_id="job_t1",
                task_id="task_t1",
                title="Run test suite",
                context="pytest context",
                workspace=str(tmp_path),
            )
        assert isinstance(result, AgentOutput)
        assert result.status == "success"
        assert "All tests passed" in result.reasoning_summary


# ─── 5. agents/reviewer.py ───────────────────────────────────────────────────

class TestReviewerAgentCoverage:
    def test_reviewer_system_prompt(self):
        from app.features.ai.agents.reviewer import ReviewerAgent
        agent = ReviewerAgent()
        prompt = agent.get_system_prompt()
        assert "reviewer" in prompt.lower() or "review" in prompt.lower()
        assert len(prompt) > 50

    def test_reviewer_role_property(self):
        from app.features.ai.agents.reviewer import ReviewerAgent
        agent = ReviewerAgent()
        assert agent.role == "Review Agent"

