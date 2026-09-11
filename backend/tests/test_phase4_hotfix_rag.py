from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.features.ai.rag.vector_index_service import (
    index_file,
    init_vector_store,
    semantic_search,
    schedule_rag_reindex,
    reindex_workspace_now,
    CODE_EXTENSIONS,
)
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
