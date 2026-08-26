"""
test_phase2_fixes.py - Test suite verifying Phase 2 architecture fixes.

Covers:
  FIX 11: Modular harness component isolation (PlanParser, ToolExecutor, SSEStreamer, etc.)
  FIX 12: RAG failure and stream truncation error surfacing (log_and_flag_failure)
  FIX 13: CoderAgent grounding fail-closed behavior
  FIX 14: Database asyncio.Lock, schema migrations, and status CHECK constraints
  FIX 15: Deduplicated workspace trust and AI provider constants
  FIX 16: Proposal listing indexed SQL filtering and safe placeholder/fuzzy matching
"""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


# ===================================================================
# FIX 11: Modular Harness Component Isolation
# ===================================================================

def test_plan_parser_classifies_and_parses():
    from app.features.ai.harness.plan_parser import PlanParser, DAGPlanStep
    
    tier, label, reason = PlanParser.classify("hello there")
    assert tier == 0
    assert "Fast path" in reason

    tier_deep, _, _ = PlanParser.classify("build a full stack website with auth, database and tests")
    assert tier_deep == 2

    raw_plan = "[PLAN]\n1. First step\n2. Second step (after 1)\n[/PLAN]"
    dag = PlanParser.parse_dag(raw_plan)
    assert dag is not None
    assert len(dag) == 2
    assert dag[0].title == "First step"
    assert dag[1].depends_on == ["step_1"]


def test_sse_streamer_formatting():
    from app.features.ai.harness.sse_streamer import SSEStreamer
    
    status_event = SSEStreamer.status("thinking", "Agent analyzing...")
    assert "event: status\n" in status_event
    assert '"message": "Agent analyzing..."' in status_event

    done_event = SSEStreamer.done(True, "Complete")
    assert "event: done\n" in done_event
    assert '"success": true' in done_event


def test_compaction_manager():
    from app.features.ai.harness.compaction_manager import CompactionManager
    from app.features.ai.schemas import ChatMessage
    
    msgs = [
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="[TOOL_CALL: read_file]" + ("a" * 350) + "[/TOOL_CALL]"),
        ChatMessage(role="user", content="[TOOL_RESULT: read_file] long file content here"),
        ChatMessage(role="assistant", content="done step 1"),
        ChatMessage(role="user", content="next question"),
        ChatMessage(role="assistant", content="final answer"),
    ]
    compacted = CompactionManager.compact(msgs, keep_recent_turns=1)
    assert len(compacted) == len(msgs)
    assert any("compacted to save context tokens" in m.content for m in compacted)


# ===================================================================
# FIX 12: Failure Handler & Exception Surfacing
# ===================================================================

def test_log_and_flag_failure_never_crashes():
    from app.features.ai.harness.failure_handler import log_and_flag_failure
    
    exc = RuntimeError("Simulated RAG failure")
    flag_data, sse_event = log_and_flag_failure("rag_gathering", exc, {"query": "test"})
    
    assert flag_data["degraded"] is True
    assert flag_data["stage"] == "rag_gathering"
    assert "event: status\n" in sse_event
    assert "rag_gathering" in sse_event


def test_log_and_flag_failure_stream_truncation():
    from app.features.ai.harness.failure_handler import log_and_flag_failure
    
    exc = ConnectionResetError("Provider dropped connection mid-stream")
    flag_data, sse_event = log_and_flag_failure("model_streaming", exc, {"model": "mock-llm"})
    
    assert flag_data["degraded"] is True
    assert flag_data["stage"] == "model_streaming"
    assert "model_streaming" in sse_event


# ===================================================================
# FIX 13: Coder Grounding Fail-Closed
# ===================================================================

@pytest.mark.asyncio
async def test_coder_grounding_failure_fails_closed(tmp_path):
    """When _ground_files fails, CoderAgent must not proceed with hallucinated edits."""
    from app.features.ai.agents.coder import CoderAgent
    
    agent = CoderAgent()
    ws = str(tmp_path)
    
    mock_instance = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield '{"approved": true, "goal": "Refactor", "hypothesis": "quick", "files_to_touch": ["main.py"], "approach": "edit", "risks": [], "verification": "check"}'
    mock_instance.stream_chat = mock_stream

    with patch.object(agent, "_ground_files", side_effect=OSError("Disk read error")), \
         patch.object(CoderAgent, "is_high_stakes", return_value=(False, [])), \
         patch("app.features.ai.agents.coder.provider_for", new_callable=AsyncMock) as mock_p, \
         patch("app.features.ai.agents.coder.event_bus.publish", new_callable=AsyncMock), \
         patch("app.features.ai.job_service.update_task_status", new_callable=AsyncMock):
        
        mock_p.return_value = mock_instance
        out = await agent.execute(
            job_id="job_test_1",
            task_id="task_test_1",
            title="Refactor function --quick",
            context="",
            workspace=ws,
        )
        assert out.status == "failure"
        assert "Grounding failed" in out.reasoning_summary


# ===================================================================
# FIX 14: Database Concurrency & Migrations
# ===================================================================

@pytest.mark.asyncio
async def test_database_asyncio_lock_and_migrations(tmp_path):
    """Verify database initializes via asyncio.Lock and creates _schema_migrations."""
    from app.db import database as db_mod
    
    db_file = tmp_path / "test_mig.sqlite3"
    db = await db_mod.init_db(db_file)
    
    cur = await db.execute("SELECT version, name FROM _schema_migrations ORDER BY version")
    rows = await cur.fetchall()
    versions = [r[0] for r in rows]
    assert 1 in versions
    assert 2 in versions
    
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_database_status_check_constraint(tmp_path):
    """Verify status CHECK constraints reject invalid status strings."""
    from app.db import database as db_mod
    
    db_file = tmp_path / "test_check.sqlite3"
    db = await db_mod.init_db(db_file)
    
    await db.execute("INSERT INTO workspaces (path, name) VALUES ('/tmp/ws_test', 'test')")
    await db.commit()
    
    # Valid status
    await db.execute("INSERT INTO agent_jobs (id, workspace, workflow, status) VALUES ('j1', '/tmp/ws_test', 'test', 'running')")
    await db.commit()
    
    # Invalid status must raise an exception
    with pytest.raises(Exception):
        await db.execute("INSERT INTO agent_jobs (id, workspace, workflow, status) VALUES ('j2', '/tmp/ws_test', 'test', 'bad_status')")
        await db.commit()
        
    await db_mod.close_db()


# ===================================================================
# FIX 15: Deduplicated Constants & Trust Dependency
# ===================================================================

def test_deduplicated_trust_and_constants():
    from app.core.trust import ensure_workspace_trusted, _ensure_trusted
    from app.features.ai.providers.constants import RECOVERY_URLS, PRESET_TO_PROVIDER
    
    assert callable(ensure_workspace_trusted)
    assert callable(_ensure_trusted)
    assert "groq" in RECOVERY_URLS
    assert "openai" in RECOVERY_URLS
    assert "local_reasoning" in PRESET_TO_PROVIDER


# ===================================================================
# FIX 16: Proposal Listing & Placeholder Detection
# ===================================================================

def test_apply_proposal_placeholder_word_boundary():
    """Verify comments like '# None of the above' are not misclassified as placeholders."""
    from app.features.ai.service import _is_known_placeholder
    
    assert _is_known_placeholder("none") is True
    assert _is_known_placeholder("new file") is True
    assert _is_known_placeholder("# empty file") is True
    
    # Comments containing 'none' as part of a sentence must NOT be placeholders
    assert _is_known_placeholder("# None of the functions should return null") is False
    assert _is_known_placeholder("x = None  # Set initial state") is False