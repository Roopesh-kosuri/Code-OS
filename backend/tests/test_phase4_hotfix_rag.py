from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from app.features.ai.rag.vector_index_service import (
    index_file,
    init_vector_store,
    semantic_search,
    schedule_rag_reindex,
    reindex_workspace_now,
    reconcile_workspace_index,
    get_rag_stats,
    CODE_EXTENSIONS,
)
from app.features.ai.intelligence.task_classifier import classify_task
from app.features.ai.harness.plan_parser import _classify_rules, _classify_task_effort
from app.features.ai.harness.prompt_builder import (
    _build_system_prompt,
    _gather_budgeted_rag_context,
    _is_codebase_inquiry,
    _QUICK_TASK_SYSTEM_PROMPT,
)
from app.features.ai.harness.tool_executor import CORE_CODING_TOOLS, SLIM_CODING_TOOLS
from app.features.ai.agents.agent_tools import _handle_search_code


def test_semantic_search_guidance_present_in_tier1_prompt(tmp_path):
    """Verify that tier 1 prompt contains guidance preferring semantic_search for conceptual inquiries."""
    workspace = str(tmp_path)
    prompt = _build_system_prompt(workspace, tier=1, context={})

    assert "semantic_search" in prompt
    assert "prefer `semantic_search` over lexical `search_code`" in prompt
    assert "prefer `semantic_search` over lexical `search_code`" in _QUICK_TASK_SYSTEM_PROMPT

    # Also verify semantic_search is exposed in available tool manifests
    core_tool_names = [t["function"]["name"] for t in CORE_CODING_TOOLS]
    slim_tool_names = [t["function"]["name"] for t in SLIM_CODING_TOOLS]
    assert "semantic_search" in core_tool_names
    assert "semantic_search" in slim_tool_names


@pytest.mark.asyncio
async def test_md_file_indexed_into_codebase_rag_on_create(tmp_path):
    """Verify that .md files are treated as indexable code files and successfully indexed into codebase_rag."""
    assert ".md" in CODE_EXTENSIONS
    workspace = str(tmp_path)
    doc_path = tmp_path / "docs" / "architecture.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "# System Architecture\nThe application uses an asynchronous message bus with Redis pub/sub for event dispatch.",
        encoding="utf-8",
    )

    chunks = await index_file(workspace, str(doc_path))
    assert chunks >= 1

    col = init_vector_store(workspace, collection_name="codebase_rag")
    assert col.count() >= 1

    # Verify manual reindex now path
    reindex_status = await reindex_workspace_now(workspace)
    assert reindex_status["files_indexed"] >= 1
    assert reindex_status["total_chunks"] >= 1


@pytest.mark.asyncio
async def test_repro_login_system(tmp_path):
    """
    Repro test:
    1. login_system.md contains auth logic (bcrypt, JWT) but NEVER the word 'authentication'.
    2. Lexical search for 'authentication' returns 0 matches.
    3. Semantic search for 'how does authentication work' surfaces login_system.md.
    4. Assembled RAG context contains bcrypt / JWT chunks.
    """
    workspace = str(tmp_path)
    login_md = tmp_path / "login_system.md"
    content = """# User Login System
When users submit their credentials to `/api/login`, the system verifies their password using salted bcrypt hashes.
Upon successful validation, a signed JWT access token is minted with RS256 algorithm and a 1-hour expiration.
The token contains claims for user ID, roles, and tenant ID. Subsequent requests validate this bearer token."""

    login_md.write_text(content, encoding="utf-8")

    # Confirm the word "authentication" is absent from the file
    assert "authentication" not in content.lower()

    # Confirm lexical search returns 0 matches
    lexical_result = _handle_search_code(workspace, {"query": "authentication"})
    assert "No matches found" in lexical_result.output or "login_system.md" not in lexical_result.output

    # Index into codebase_rag
    await index_file(workspace, str(login_md))

    # Ask conceptual question
    query = "How does authentication work in this codebase?"
    assert _is_codebase_inquiry(query) is True

    # Gather budgeted RAG context
    results, rag_snippet = await _gather_budgeted_rag_context(workspace, query, max_chars=1200)

    assert len(results) > 0
    assert any("login_system.md" in (r.get("relative_path") or r.get("path", "")) for r in results)
    assert "bcrypt" in rag_snippet
    assert "JWT" in rag_snippet


@pytest.mark.asyncio
async def test_tier1_codebase_question_includes_rag_context(tmp_path):
    """Verify that tier 1 codebase inquiries assemble and inject semantic RAG context."""
    workspace = str(tmp_path)
    src_file = tmp_path / "auth_service.py"
    src_file.write_text(
        "def verify_password(plain, hashed):\n    return bcrypt.checkpw(plain, hashed)\n",
        encoding="utf-8",
    )
    await index_file(workspace, str(src_file))

    # Codebase conceptual inquiry
    inquiry = "How does authentication work in this codebase?"
    assert _is_codebase_inquiry(inquiry) is True

    # Non-codebase query should return False
    assert _is_codebase_inquiry("fix the typo in line 42") is False

    _, rag_snippets = await _gather_budgeted_rag_context(workspace, inquiry, max_chars=1200)
    assert len(rag_snippets) > 0
    assert "auth_service.py" in rag_snippets

    # Verify that _build_system_prompt for tier 1 includes the RAG snippets
    prompt = _build_system_prompt(workspace, tier=1, context={}, rag_snippet_summary=rag_snippets)
    assert "auth_service.py" in prompt
    assert "bcrypt.checkpw" in prompt


# ── Phase 4.2 Hotfix Regression Tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_reconciliation_indexes_preexisting_files(tmp_path):
    """Verify that startup reconciliation indexes pre-existing files into codebase_rag."""
    workspace = str(tmp_path)
    # Create pre-existing files before reconciliation
    f1 = tmp_path / "service.py"
    f1.write_text("def handle_auth():\n    return 'auth'\n", encoding="utf-8")
    f2 = tmp_path / "login_system.md"
    f2.write_text("# Login System\nVerifies passwords with bcrypt.\n", encoding="utf-8")

    # Initially, collection count is 0
    col = init_vector_store(workspace, collection_name="codebase_rag")
    assert col.count() == 0

    # Run reconciliation
    res = await reconcile_workspace_index(workspace)
    assert res["files_indexed"] >= 2
    assert res["total_chunks"] >= 2

    # Verify both files are in indexed_files and stats report correct data
    stats = await get_rag_stats(workspace)
    assert "service.py" in stats["indexed_files"]
    assert "login_system.md" in stats["indexed_files"]
    assert stats["chunk_count"] >= 2
    assert stats["last_index_at"] is not None


def test_codebase_question_never_tier0_without_context():
    """Verify that codebase inquiries are NEVER classified as Tier 0 (Fast Answer)."""
    questions = [
        "How does authentication work in this codebase?",
        "Explain the architecture of this repo",
        "Where is database initialized in this project?",
        "How does the plugin system work in this repo?",
        "Can you describe how login is implemented in this codebase?",
    ]

    for q in questions:
        # task_classifier level
        classified = classify_task(q)
        assert classified.get("effort_tier") >= 1, f"Expected effort_tier >= 1 for '{q}', got {classified}"
        assert classified.get("difficulty") != "FAST", f"Expected difficulty != FAST for '{q}', got {classified}"

        # plan_parser _classify_rules level
        tier, label, _ = _classify_rules(q.lower())
        assert tier >= 1, f"Expected tier >= 1 in _classify_rules for '{q}', got {tier} ({label})"

        # plan_parser _classify_task_effort level
        tier2, label2, _ = _classify_task_effort(q)
        assert tier2 >= 1, f"Expected tier >= 1 in _classify_task_effort for '{q}', got {tier2} ({label2})"


@pytest.mark.asyncio
async def test_rag_injection_event_emitted(tmp_path, temp_db):
    """Verify that chat harness yields a 'rag_context' SSE event and writes activity log."""
    from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest, _load_activity_log

    workspace = str(tmp_path)
    auth_file = tmp_path / "login_system.md"
    auth_file.write_text("# Login System\nUses salted bcrypt hashes and JWT tokens.\n", encoding="utf-8")
    await index_file(workspace, str(auth_file))

    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=workspace,
        messages=[{"role": "user", "content": "How does authentication work in this codebase?"}],
    )

    async def mock_stream(*args, **kwargs):
        yield "Authentication uses bcrypt and JWT.\n[DONE]"

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream()])

    events = []
    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        async for sse_chunk in run_chat_agent(req):
            events.append(sse_chunk)

    # Check for rag_context event
    rag_events = [e for e in events if "event: rag_context" in e]
    assert len(rag_events) >= 1, f"Expected 'event: rag_context' in SSE stream, got: {events}"
    assert "login_system.md" in rag_events[0]
    assert "chunks_count" in rag_events[0]

    # Check activity log for rag_injection
    act_log = _load_activity_log(workspace)
    rag_logs = [entry for entry in act_log if entry.get("action_type") == "rag_injection"]
    assert len(rag_logs) >= 1, f"Expected 'rag_injection' in activity log, got: {act_log}"
    assert "rag_context" in rag_logs[0].get("details", "")


@pytest.mark.asyncio
async def test_rag_stats_endpoint_reports_missing_files(tmp_path, temp_db, async_client):
    """Verify that get_rag_stats and GET /api/rag/stats report chunk count, indexed files, and missing files sample."""
    from app.features.workspaces.trust_service import set_workspace_trust

    workspace = str(tmp_path)
    await set_workspace_trust(workspace, True)

    file_a = tmp_path / "indexed_module.py"
    file_a.write_text("def foo():\n    return 42\n", encoding="utf-8")
    file_b = tmp_path / "unindexed_module.py"
    file_b.write_text("def bar():\n    return 99\n", encoding="utf-8")

    # Index only file_a
    await index_file(workspace, str(file_a))

    stats = await get_rag_stats(workspace)
    assert stats["chunk_count"] >= 1
    assert "indexed_module.py" in stats["indexed_files"]
    assert "unindexed_module.py" not in stats["indexed_files"]
    assert "unindexed_module.py" in stats["missing_files_sample"]
    assert stats["last_index_at"] is not None

    # Test via API endpoint
    response = await async_client.get(f"/api/rag/stats?workspace={workspace}")
    assert response.status_code == 200
    data = response.json()
    assert data["chunk_count"] >= 1
    assert "indexed_module.py" in data["indexed_files"]
    assert "unindexed_module.py" in data["missing_files_sample"]


# ── Phase 4.3 Regression Tests: Scope/Ranking & Retrieval-Failure UX ──────────

@pytest.mark.asyncio
async def test_uploads_dir_excluded_from_codebase_rag(tmp_path):
    """Verify that .code_os/uploads and uploads directories are excluded from indexing and stats."""
    workspace = str(tmp_path)
    # Create normal source file
    src = tmp_path / "src" / "service.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("def run():\n    return True\n", encoding="utf-8")

    # Create upload files
    up1 = tmp_path / ".code_os" / "uploads" / "report.md"
    up1.parent.mkdir(parents=True, exist_ok=True)
    up1.write_text("# Uploaded report on authentication\nLots of auth keywords\n", encoding="utf-8")

    up2 = tmp_path / "uploads" / "data.md"
    up2.parent.mkdir(parents=True, exist_ok=True)
    up2.write_text("# Another upload with authentication\n", encoding="utf-8")

    # Direct index_file on upload path returns 0
    cnt1 = await index_file(workspace, str(up1))
    assert cnt1 == 0
    cnt2 = await index_file(workspace, str(up2))
    assert cnt2 == 0

    # Reindex workspace
    status = await reindex_workspace_now(workspace)
    assert status["files_indexed"] == 1

    stats = await get_rag_stats(workspace)
    assert any("service.py" in f for f in stats["indexed_files"])
    assert not any("uploads" in f for f in stats["indexed_files"])
    assert not any("uploads" in f for f in stats["missing_files_sample"])


@pytest.mark.asyncio
async def test_login_system_top3_for_authentication_query(tmp_path):
    """Verify that login_system.md ranks in top 3 for 'authentication' query without literal word match."""
    workspace = str(tmp_path)
    login_file = tmp_path / "login_system.md"
    login_file.write_text(
        "# User Login System\n"
        "Users submit credentials to /api/login and passwords are verified using salted bcrypt hashes.\n"
        "Upon successful verification, signed RS256 JWT access tokens are minted with claims for user identity.",
        encoding="utf-8",
    )
    db_file = tmp_path / "database.py"
    db_file.write_text(
        "import asyncpg\nasync def get_db_pool():\n    return await asyncpg.create_pool('postgresql://localhost/db')\n",
        encoding="utf-8",
    )
    worker_file = tmp_path / "worker.py"
    worker_file.write_text(
        "import celery\napp = celery.Celery('tasks')\n@app.task\ndef background_job(x):\n    return x * 2\n",
        encoding="utf-8",
    )

    await reconcile_workspace_index(workspace)

    results = await semantic_search(workspace, "authentication", top_k=3)
    assert len(results) > 0
    top_paths = [r.get("relative_path") or r.get("path", "") for r in results]
    assert any("login_system.md" in p for p in top_paths[:3])


@pytest.mark.asyncio
async def test_semantic_search_tool_returns_scored_chunks(tmp_path, temp_db):
    """Verify that invoking the semantic_search tool returns formatted scored chunks with the read_file hint."""
    from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest

    workspace = str(tmp_path)
    auth_file = tmp_path / "login_system.md"
    auth_file.write_text("# Login System\nUses salted bcrypt hashes and JWT tokens.\n", encoding="utf-8")
    await index_file(workspace, str(auth_file))

    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=workspace,
        messages=[{"role": "user", "content": "Check auth"}],
    )

    iteration_step = 0
    async def mock_stream(*args, **kwargs):
        nonlocal iteration_step
        if iteration_step == 0:
            iteration_step += 1
            yield '[TOOL_CALL: semantic_search]\n{"query": "authentication"}\n[/TOOL_CALL]'
        else:
            yield "Here is the authentication system based on the search results.\n[DONE]"

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream(), mock_stream()])

    events = []
    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        async for sse_chunk in run_chat_agent(req):
            events.append(sse_chunk)

    tool_results = [e for e in events if "tool_result" in e and "semantic_search" in e]
    assert len(tool_results) >= 1
    assert "score:" in tool_results[0]
    assert "Hint: use read_file on these paths for full content." in tool_results[0]


@pytest.mark.asyncio
async def test_reconcile_prunes_polluted_records(tmp_path):
    """Verify that reconcile_workspace_index purges any previously-indexed uploads or ignored files."""
    workspace = str(tmp_path)
    col = init_vector_store(workspace, collection_name="codebase_rag")
    col.add(
        documents=["Forensic audit with authentication tokens"],
        metadatas=[{"file_path": ".code_os/uploads/polluted.md", "chunk_index": 0, "line_range": "1-10"}],
        ids=["polluted_1"],
    )
    col.add(
        documents=["Valid source code"],
        metadatas=[{"file_path": "valid_service.py", "chunk_index": 0, "line_range": "1-5"}],
        ids=["valid_1"],
    )
    assert col.count() == 2

    # Create the valid file on disk so reconcile sees it
    (tmp_path / "valid_service.py").write_text("def valid(): pass\n", encoding="utf-8")

    # Run reconcile
    res = await reconcile_workspace_index(workspace)

    # Check collection contents
    data = col.get()
    all_fps = [m.get("file_path", "") for m in data.get("metadatas", [])]
    assert not any("uploads" in fp for fp in all_fps)
    assert any("valid_service.py" in fp for fp in all_fps)


@pytest.mark.asyncio
async def test_retrieval_failure_answers_honestly_without_ask_user(tmp_path, temp_db):
    """Verify that when retrieval yields no matches, attempting to ask_user is intercepted and rejected with retrieval failure policy."""
    from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest

    workspace = str(tmp_path)
    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=workspace,
        messages=[{"role": "user", "content": "Find authentication logic"}],
    )

    step = 0
    async def mock_stream(*args, **kwargs):
        nonlocal step
        if step == 0:
            step += 1
            yield '[TOOL_CALL: search_code]\n{"query": "authentication"}\n[/TOOL_CALL]'
        elif step == 1:
            step += 1
            yield '[TOOL_CALL: ask_user]\n{"question": "Could you provide more context on which file has authentication?", "options": ["Option A", "Option B"]}\n[/TOOL_CALL]'
        else:
            yield "I searched the codebase for authentication logic but could not find any references. The closest matches are...\n[DONE]"

    mock_provider = MagicMock()
    mock_provider.stream_chat = MagicMock(side_effect=[mock_stream(), mock_stream(), mock_stream()])

    events = []
    with patch("app.features.ai.chat_harness.provider_for", new=AsyncMock(return_value=mock_provider)):
        async for sse_chunk in run_chat_agent(req):
            events.append(sse_chunk)

    # Verify that NO interactive ask_user card was emitted to the user
    ask_user_events = [e for e in events if "event: ask_user" in e]
    assert len(ask_user_events) == 0

    # Verify tool_error status event was emitted with the policy directive
    tool_error_events = [e for e in events if "tool_error" in e and "Retrieval failure policy" in e]
    assert len(tool_error_events) >= 1


@pytest.mark.asyncio
async def test_no_second_clarification_after_user_answer(tmp_path, temp_db):
    """Verify that once user answers a clarification, subsequent ask_user calls in that turn are blocked with directive to proceed."""
    from app.features.ai.chat_harness import (
        run_chat_agent,
        ChatAgentRequest,
        respond_to_user_question,
        _pending_user_responses,
    )

    workspace = str(tmp_path)
    req = ChatAgentRequest(
        provider="mock",
        model="mock-model",
        workspace=workspace,
        messages=[{"role": "user", "content": "Configure auth"}],
    )

    step = 0
    async def mock_stream(*args, **kwargs):
        nonlocal step
        if step == 0:
            step += 1
            yield '[TOOL_CALL: ask_user]\n{"question": "Do you want JWT or Session?", "options": ["JWT", "Session"]}\n[/TOOL_CALL]'
        elif step == 1:
            step += 1
            yield '[TOOL_CALL: ask_user]\n{"question": "Do you prefer RS256 or HS256?", "options": ["RS256", "HS256"]}\n[/TOOL_CALL]'
        else:
            yield "Configuring JWT authentication now.\n[DONE]"

    mock_provider = MagicMock()
    mock_provider.stream_chat = mock_stream

    events = []
    async def run_agent():
        async for sse_chunk in run_chat_agent(req):
            events.append(sse_chunk)

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        task = asyncio.create_task(run_agent())

        # Wait for first ask_user card to be registered
        for _ in range(50):
            if _pending_user_responses:
                break
            await asyncio.sleep(0.05)

        assert len(_pending_user_responses) == 1
        action_id = list(_pending_user_responses.keys())[0]
        respond_to_user_question(action_id, "JWT")

        await task

    # Verify that only 1 event: ask_user was ever emitted
    ask_user_cards = [e for e in events if "event: ask_user" in e]
    assert len(ask_user_cards) == 1

    # Verify the second clarification was rejected with directive
    second_clarification_errors = [e for e in events if "Proceed with the task using the user's answer now" in e]
    assert len(second_clarification_errors) >= 1


def test_meta_narration_stripped_from_final_answer():
    """Verify that tool-planning meta-narration sentences are stripped from the final answer text."""
    from app.features.ai.harness.compaction_manager import strip_meta_narration, _clean_response_text

    narrated = (
        "To further investigate, I will use the search_code function to find the auth endpoints. "
        "Let me inspect the codebase files to verify.\n\n"
        "The login system uses bcrypt for password hashing and RS256 JWT tokens for sessions."
    )
    cleaned = strip_meta_narration(narrated)
    assert "To further investigate" not in cleaned
    assert "search_code" not in cleaned
    assert "The login system uses bcrypt" in cleaned

    # Also verify via _clean_response_text
    cleaned_all = _clean_response_text(narrated)
    assert "To further investigate" not in cleaned_all
    assert "The login system uses bcrypt" in cleaned_all


def test_fallback_chain_runs_before_clarification(tmp_path):
    """Verify system prompts and rules enforce fallback chain (semantic_search -> search_code -> read_file) before answering."""
    from app.features.ai.harness.prompt_builder import _build_system_prompt, _QUICK_TASK_SYSTEM_PROMPT, _DEEP_TASK_SYSTEM_PROMPT

    workspace = str(tmp_path)
    tier1_prompt = _build_system_prompt(workspace, tier=1, context={})
    tier2_prompt = _build_system_prompt(workspace, tier=2, context={})

    for p in (tier1_prompt, tier2_prompt, _QUICK_TASK_SYSTEM_PROMPT, _DEEP_TASK_SYSTEM_PROMPT):
        assert "fallback chain" in p.lower()
        assert "semantic_search" in p
        assert "search_code" in p
        assert "read_file" in p
        assert "never call `ask_user`" in p.lower() or "never quiz the user" in p.lower()
