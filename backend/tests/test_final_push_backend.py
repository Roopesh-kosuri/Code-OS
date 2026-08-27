"""
Final bounded coverage push suite for backend.
Integration and unit tests targeting:
- duo/service.py
- chat_harness_routes.py
- service.py (proposal edge cases)
- agent_tools.py
- terminal/service.py & run_service.py
- git/service.py & github_service.py
- python_debugger.py
- mcp_manager.py
- executor.py
"""
import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import get_token
from app.db.database import get_db, init_db


@pytest.fixture(autouse=True)
async def setup_test_database():
    await init_db()
    yield


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {get_token()}"}


@pytest.fixture
def test_client(auth_headers):
    with patch("app.main.mcp_manager.initialize_servers", new_callable=AsyncMock), \
         patch("app.main.mcp_manager.shutdown", new_callable=AsyncMock):
        with TestClient(app) as client:
            client.headers.update(auth_headers)
            yield client


# ===================================================================
# 1. DUO / SERVICE.PY TESTS
# ===================================================================

class TestDuoServiceCoverage:
    def test_extract_json_variants(self):
        from app.features.duo.service import _extract_json

        # 1. Direct JSON
        data = _extract_json('{"approved": true, "reasoning": "all good"}')
        assert data["approved"] is True

        # 2. Markdown json fence
        fence = 'Here is verdict:\n```json\n{"approved": false, "reasoning": "bugs found"}\n```\nThanks.'
        data = _extract_json(fence)
        assert data["approved"] is False
        assert data["reasoning"] == "bugs found"

        # 3. Bare fence
        bare = '```\n{"approved": true, "reasoning": "neat"}\n```'
        data = _extract_json(bare)
        assert data["approved"] is True

        # 4. Invalid json raises ValueError
        with pytest.raises(ValueError, match="No valid JSON found"):
            _extract_json("no json here at all")

    @pytest.mark.asyncio
    async def test_call_model_timeout_handling(self):
        from app.features.duo.service import _call_model, ModelConfig
        from app.features.ai.schemas import ChatMessage

        cfg = ModelConfig(provider="mock", model="mock-model")

        async def slow_stream(*args, **kwargs):
            await asyncio.sleep(2.0)
            yield "token"

        mock_provider = MagicMock()
        mock_provider.stream_chat = slow_stream

        with patch("app.features.duo.service._build_provider", return_value=mock_provider):
            with pytest.raises(TimeoutError, match="Model call timed out"):
                await _call_model(cfg, [ChatMessage(role="user", content="hi")], timeout_seconds=0.05)

    @pytest.mark.asyncio
    async def test_duo_session_crud_and_cancel(self, tmp_path):
        from app.features.duo.service import (
            start_session, cancel_session, get_session, list_sessions,
            DuoSessionRequest, ModelConfig, _active_tasks
        )
        from app.db.database import get_db

        ws = str(tmp_path)
        db = await get_db()
        await db.execute(
            "INSERT OR IGNORE INTO workspaces(path, name, last_opened_at) VALUES (?, ?, '2026-01-01T00:00:00')",
            (ws, tmp_path.name)
        )
        await db.commit()

        req = DuoSessionRequest(
            workspace=ws,
            task_description="Implement a feature",
            max_rounds=2,
            generator=ModelConfig(provider="openai", model="gpt-4o"),
            critic=ModelConfig(provider="openai", model="gpt-4o"),
        )

        # Mock loop so it doesn't run external LLM calls
        with patch("app.features.duo.service._run_loop", new_callable=AsyncMock):
            session = await start_session(req)
            assert session.id in _active_tasks or session.status == "running"
            assert session.workspace == ws

            fetched = await get_session(session.id)
            assert fetched.id == session.id

            all_sessions = await list_sessions(ws)
            assert any(s.id == session.id for s in all_sessions)

            cancelled = await cancel_session(session.id)
            assert cancelled.status == "cancelled"

            # Cancelling nonexistent raises or returns cleanly
            with pytest.raises(HTTPException) as exc_info:
                await get_session("nonexistent-uuid")
            assert exc_info.value.status_code == 404


# ===================================================================
# 2. CHAT HARNESS ROUTES TESTS
# ===================================================================

class TestChatHarnessRoutesCoverage:
    def test_token_usage_and_provider_health_endpoints(self, test_client):
        # 1. Token usage
        res = test_client.get("/api/ai/token-usage")
        assert res.status_code == 200
        data = res.json()
        assert "openai" in data
        assert "daily_limit" in data["openai"]

        # 2. Provider health
        res = test_client.get("/api/ai/provider-health")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict)

        # 3. Validate model
        res = test_client.get("/api/ai/validate-model?provider=openai&model=gpt-4o")
        assert res.status_code == 200
        assert "valid" in res.json()

        # 4. Reset token usage
        res = test_client.post("/api/ai/token-usage/reset")
        assert res.status_code == 200
        assert res.json().get("status") == "ok"

    def test_chat_agent_state_and_capabilities(self, test_client, tmp_path):
        ws = str(tmp_path)

        # Sandbox capabilities
        res = test_client.get("/api/ai/chat-agent/sandbox/capabilities")
        assert res.status_code == 200
        assert "docker_available" in res.json()

        # Interrupted state (none initially)
        res = test_client.get(f"/api/ai/chat-agent/interrupted-state?workspace={ws}")
        assert res.status_code == 200
        assert res.json().get("has_interrupted") is False

        # Delete interrupted state
        res = test_client.delete(f"/api/ai/chat-agent/interrupted-state?workspace={ws}")
        assert res.status_code == 200

        # Trusted commands add & delete
        res = test_client.post(
            "/api/ai/chat-agent/trusted-commands",
            json={"workspace": ws, "pattern": "pytest *"}
        )
        assert res.status_code == 200
        assert res.json().get("added") is True

        res = test_client.delete(
            f"/api/ai/chat-agent/trusted-commands?workspace={ws}&pattern=pytest *"
        )
        assert res.status_code == 200

        # Cancel agent run
        res = test_client.post("/api/ai/chat-agent/cancel")
        assert res.status_code == 200

        # Activity log export / read
        res = test_client.get(f"/api/ai/chat-agent/activity-log?workspace={ws}")
        assert res.status_code == 200


# ===================================================================
# 3. AI SERVICE PROPOSAL EDGE CASES
# ===================================================================

class TestAiServiceProposalEdgeCases:
    @pytest.mark.asyncio
    async def test_apply_proposal_not_pending_409(self, tmp_path):
        from app.features.ai.service import create_proposal, apply_proposal
        from app.features.ai.schemas import EditProposalRequest, FileChange

        ws = str(tmp_path)
        req = EditProposalRequest(
            workspace=ws,
            title="Test Proposal",
            summary="Proposal summary",
            changes=[FileChange(path="hello.txt", original="", updated="world")]
        )
        dto = await create_proposal(req)
        
        # Manually change status to rejected
        db = await get_db()
        await db.execute("UPDATE edit_proposals SET status='rejected' WHERE id=?", (dto.id,))
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await apply_proposal(dto.id)
        assert exc_info.value.status_code == 409
        assert "not pending" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_apply_proposal_path_traversal_403(self, tmp_path):
        from app.features.ai.service import create_proposal
        from app.features.ai.schemas import EditProposalRequest, FileChange

        ws = str(tmp_path)
        req = EditProposalRequest(
            workspace=ws,
            title="Traversal Proposal",
            summary="Proposal summary",
            changes=[FileChange(path="../../outside.txt", original="", updated="bad")]
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_proposal(req)
        assert exc_info.value.status_code == 403
        assert "escapes workspace" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_apply_proposal_crlf_and_placeholder_replacement(self, tmp_path):
        from app.features.ai.service import create_proposal, apply_proposal
        from app.features.ai.schemas import EditProposalRequest, FileChange

        ws = str(tmp_path)
        target_file = tmp_path / "code.py"
        target_file.write_text("def foo():\r\n    return 1\r\n", encoding="utf-8")

        # 1. CRLF original matched and replaced
        req = EditProposalRequest(
            workspace=ws,
            title="Fix CRLF",
            summary="Proposal summary",
            changes=[FileChange(path="code.py", original="def foo():\n    return 1\n", updated="def foo():\n    return 2\n")]
        )
        dto = await create_proposal(req)
        applied = await apply_proposal(dto.id)
        assert applied.status == "applied"
        assert target_file.read_text(encoding="utf-8").strip() == "def foo():\n    return 2"

        # 2. Known placeholder replacement replaces entire file
        req2 = EditProposalRequest(
            workspace=ws,
            title="Placeholder",
            summary="Proposal summary",
            changes=[FileChange(path="code.py", original="empty file", updated="def bar():\n    return 42\n")]
        )
        dto2 = await create_proposal(req2)
        applied2 = await apply_proposal(dto2.id)
        assert applied2.status == "applied"
        assert target_file.read_text(encoding="utf-8").strip() == "def bar():\n    return 42"

    @pytest.mark.asyncio
    async def test_list_proposals_filtering(self, tmp_path):
        from app.features.ai.service import create_proposal, list_proposals
        from app.features.ai.schemas import EditProposalRequest, FileChange

        ws = str(tmp_path)
        p1 = await create_proposal(EditProposalRequest(workspace=ws, title="P1", summary="S1", changes=[]))
        p2 = await create_proposal(EditProposalRequest(workspace=ws, title="P2", summary="S2", changes=[]))

        all_p = await list_proposals(workspace=ws)
        assert len(all_p) >= 2
        assert all(p.status == "pending" for p in all_p)


# ===================================================================
# 4. AGENT TOOLS SUCCESS, FAILURE, AND PATH REJECTION
# ===================================================================

class TestAgentToolsCoverage:
    def test_read_file_scenarios(self, tmp_path):
        from app.features.ai.agents.agent_tools import _handle_read_file

        ws = str(tmp_path)
        f = tmp_path / "sample.txt"
        f.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5", encoding="utf-8")

        # 1. Success with pagination
        res = _handle_read_file(ws, {"path": "sample.txt", "start_line": 2, "limit": 2})
        assert res.success is True
        assert "Lines 2-3 of 5" in res.output
        assert "Line 2\nLine 3" in res.output

        # 2. Path rejected
        res = _handle_read_file(ws, {"path": "../../etc/passwd"})
        assert res.success is False
        assert "Path rejected" in res.error

        # 3. File not found
        res = _handle_read_file(ws, {"path": "nonexistent.txt"})
        assert res.success is False
        assert "File not found" in res.error

    def test_list_directory_scenarios(self, tmp_path):
        from app.features.ai.agents.agent_tools import _handle_list_directory

        ws = str(tmp_path)
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "file.txt").write_text("data", encoding="utf-8")

        # 1. Success tree
        res = _handle_list_directory(ws, {"path": ".", "max_depth": 2})
        assert res.success is True
        assert "subdir/" in res.output

        # 2. Not a directory
        f = tmp_path / "not_dir.txt"
        f.write_text("hello", encoding="utf-8")
        res = _handle_list_directory(ws, {"path": "not_dir.txt"})
        assert res.success is False
        assert "Not a directory" in res.error

        # 3. Path rejected
        res = _handle_list_directory(ws, {"path": "../.."})
        assert res.success is False
        assert "Path rejected" in res.error

    def test_search_code_and_edit_file(self, tmp_path):
        from app.features.ai.agents.agent_tools import _handle_search_code, _handle_edit_file

        ws = str(tmp_path)
        f = tmp_path / "main.py"
        f.write_text("def unique_search_target():\n    pass\n", encoding="utf-8")

        # Search code success
        res = _handle_search_code(ws, {"query": "unique_search_target"})
        assert res.success is True
        assert "unique_search_target" in res.output

        # Search code missing query
        res = _handle_search_code(ws, {"query": ""})
        assert res.success is False
        assert "Missing required parameter" in res.error

        # Edit file staging
        staged = []
        res = _handle_edit_file(ws, {"path": "main.py", "original": "pass", "updated": "return 1"}, staged)
        assert res.success is True
        assert len(staged) == 1
        assert staged[0].path == "main.py"

        # Edit file missing path
        res = _handle_edit_file(ws, {"path": ""}, staged)
        assert res.success is False

    def test_summarize_test_output(self):
        from app.features.ai.agents.agent_tools import summarize_test_output

        assert summarize_test_output("") == "(no output)"
        short = "short output"
        assert summarize_test_output(short, max_chars=50) == short

        long_output = "PASSED test_1\nFAILED test_2\nAssertionError: expected 1 got 2\n" + ("extra line\n" * 50)
        summary = summarize_test_output(long_output, max_chars=100)
        assert len(summary) <= 250


# ===================================================================
# 5. TERMINAL AND RUN SERVICE
# ===================================================================

class TestTerminalAndRunServiceCoverage:
    def test_terminal_session_lifecycle(self, tmp_path):
        from app.features.terminal.service import (
            create_session, rename_session, kill_session, list_sessions,
            _sanitize_environment, _is_cd_command
        )

        ws = str(tmp_path)
        session = create_session(cwd=ws)
        assert session.cwd == str(tmp_path.resolve())

        renamed = rename_session(session.id, "Renamed Terminal")
        assert renamed.name == "Renamed Terminal"

        sessions_list = list_sessions()
        assert any(s.id == session.id for s in sessions_list)

        kill_session(session.id)
        assert all(s.id != session.id for s in list_sessions())

        with pytest.raises(HTTPException) as exc_info:
            rename_session("nonexistent", "new name")
        assert exc_info.value.status_code == 404

    def test_terminal_sanitization_and_cd(self):
        from app.features.terminal.service import _sanitize_env, _is_cd_command

        env = {
            "PATH": "C:\\Windows\\system32",
            "USER": "tester",
            "AWS_SECRET_ACCESS_KEY": "supersecret",
            "GITHUB_TOKEN": "ghp_12345",
            "DATABASE_PASSWORD": "pass",
        }
        clean = _sanitize_env(env)
        assert "AWS_SECRET_ACCESS_KEY" not in clean
        assert "GITHUB_TOKEN" not in clean
        assert "DATABASE_PASSWORD" not in clean
        assert "USER" in clean or "PATH" in clean

        assert _is_cd_command("cd") is True
        assert _is_cd_command("cd mydir") is True
        assert _is_cd_command("ls") is False

    def test_run_service_toolchains_and_kill(self):
        from app.features.terminal.language_detector import get_all_toolchains
        from app.features.terminal.run_service import kill_run_process

        toolchains = get_all_toolchains()
        assert isinstance(toolchains, list)
        assert len(toolchains) > 0

        success, msg = kill_run_process("nonexistent-run-id")
        assert success is False
        assert "not found" in msg


# ===================================================================
# 6. GIT SERVICE AND GITHUB SERVICE
# ===================================================================

class TestGitAndGithubServiceCoverage:
    def test_git_service_operations(self, tmp_path):
        from app.features.git.service import (
            repo_for, status, is_dangerous_file, diff
        )
        from git import Repo

        # Create real git repo
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        repo = Repo.init(str(repo_dir))

        # Check dangerous file patterns
        assert is_dangerous_file(".env") is True
        assert is_dangerous_file("id_rsa") is True
        assert is_dangerous_file("normal.py") is False

        # Add file and check status
        test_file = repo_dir / "app.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        st = status(str(repo_dir))
        assert "app.py" in st["untracked"]

        # Diff
        df = diff(str(repo_dir))
        assert isinstance(df, str)

    def test_github_service_blocked_and_relative(self, tmp_path):
        from app.features.git.github_service import _relative_workspace_file, _is_blocked
        from git import Repo

        repo_dir = tmp_path / "gh_repo"
        repo_dir.mkdir()
        repo = Repo.init(str(repo_dir))

        (repo_dir / "safe.txt").write_text("ok", encoding="utf-8")
        rel = _relative_workspace_file(str(repo_dir), "safe.txt")
        assert rel == "safe.txt"

        assert _is_blocked(repo, ".env") is True
        assert _is_blocked(repo, "key.pem") is True
        assert _is_blocked(repo, "safe.txt") is False


# ===================================================================
# 7. PYTHON DEBUGGER AND MCP MANAGER
# ===================================================================

class TestDebuggerAndMcpCoverage:
    @pytest.mark.asyncio
    async def test_debugger_session_cap_429(self, tmp_path):
        from app.features.debug.python_debugger import (
            start_debugger, DebugStartRequest, _sessions, DebugSession, MAX_DEBUG_SESSIONS
        )

        ws = str(tmp_path)
        f = tmp_path / "script.py"
        f.write_text("print(1)", encoding="utf-8")

        # Fill sessions map up to MAX_DEBUG_SESSIONS
        dummy_sessions = {}
        for i in range(MAX_DEBUG_SESSIONS):
            mock_proc = MagicMock()
            mock_proc.returncode = None
            dummy_sessions[1000 + i] = DebugSession(
                process=mock_proc,
                port=5000 + i,
                governor_task=asyncio.create_task(asyncio.sleep(10)),
                timeout_task=asyncio.create_task(asyncio.sleep(10)),
                output_task=asyncio.create_task(asyncio.sleep(10)),
                workspace=ws,
            )

        with patch.dict(_sessions, dummy_sessions, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                await start_debugger(DebugStartRequest(workspace=ws, file_path="script.py"))
            assert exc_info.value.status_code == 429
            assert "Maximum concurrent debug sessions reached" in exc_info.value.detail

        # Cancel dummy tasks to clean up
        for s in dummy_sessions.values():
            s.governor_task.cancel()
            s.timeout_task.cancel()
            s.output_task.cancel()

    @pytest.mark.asyncio
    async def test_mcp_instance_send_request_and_read_loop(self):
        from app.features.mcp.mcp_manager import MCPServerInstance
        from app.features.mcp.schemas import MCPServerConfig

        cfg = MCPServerConfig(id="test-server", name="Test Server", command="echo", args=[])
        instance = MCPServerInstance(cfg)
        
        # Process not running raises RuntimeError
        with pytest.raises(RuntimeError, match="is not running"):
            await instance.send_request("tools/list", {})

        # Stop clears pending requests with error
        fut = asyncio.get_running_loop().create_future()
        instance.pending_requests[1] = fut
        await instance.stop()
        assert fut.done()
        with pytest.raises(RuntimeError, match="MCP server stopped"):
            fut.result()


# ===================================================================
# 8. SANDBOX EXECUTOR GOVERNOR AND TIMEOUT
# ===================================================================

class TestExecutorCoverage:
    def test_windows_sandbox_detect(self, tmp_path):
        from app.features.ai.sandbox.executor import (
            _detect_container_runtime, _detect_windows_sandbox, _generate_wsb_config
        )

        runtime = _detect_container_runtime()
        assert isinstance(runtime, dict)
        assert "docker_available" in runtime

        wsb_config = _generate_wsb_config(str(tmp_path))
        assert "<Configuration>" in wsb_config
        assert str(tmp_path) in wsb_config
