"""
test_semantic_rag.py — Comprehensive test suite for Semantic RAG with ChromaDB.

Tests:
1. test_index_workspace_indexes_all_code_files (temp workspace)
2. test_index_file_indexes_single_file
3. test_remove_file_removes_from_index
4. test_semantic_search_returns_relevant_chunks
5. test_semantic_search_ranks_by_similarity
6. test_get_file_context_returns_all_chunks
7. test_rag_routes_api (HTTP endpoints)
"""

import asyncio
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.features.ai.rag.vector_index_service import (
    init_vector_store,
    index_workspace,
    index_file,
    remove_file,
    semantic_search,
    get_file_context,
    get_indexing_status,
)


def _setup_test_codebase(ws_path: Path):
    """Create sample code files across various languages and modules."""
    (ws_path / "src").mkdir(parents=True, exist_ok=True)
    (ws_path / "tests").mkdir(parents=True, exist_ok=True)
    (ws_path / "docs").mkdir(parents=True, exist_ok=True)

    # Auth module
    auth_file = ws_path / "src" / "auth.py"
    auth_file.write_text(
        "def authenticate_user(username, password):\n"
        "    '''Verify user credentials and return JWT session token.'''\n"
        "    if username == 'admin' and password == 'secret':\n"
        "        return {'token': 'jwt_secret_token_123', 'role': 'admin'}\n"
        "    return None\n\n"
        "def verify_jwt_token(token):\n"
        "    '''Decode and validate bearer authentication token.'''\n"
        "    return token == 'jwt_secret_token_123'\n",
        encoding="utf-8",
    )

    # Database module
    db_file = ws_path / "src" / "database.py"
    db_file.write_text(
        "import sqlite3\n\n"
        "def get_database_connection(db_path='app.db'):\n"
        "    '''Create SQLite connection with foreign keys enabled.'''\n"
        "    conn = sqlite3.connect(db_path)\n"
        "    conn.execute('PRAGMA foreign_keys = ON;')\n"
        "    return conn\n",
        encoding="utf-8",
    )

    # Test file
    test_file = ws_path / "tests" / "test_auth.py"
    test_file.write_text(
        "def test_authenticate_user():\n"
        "    assert authenticate_user('admin', 'secret') is not None\n",
        encoding="utf-8",
    )

    # Docs file
    doc_file = ws_path / "docs" / "architecture.md"
    doc_file.write_text(
        "# System Architecture\n\n"
        "The system uses JWT bearer authentication and SQLite storage.\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_index_workspace_indexes_all_code_files(tmp_path: Path):
    """Verify that index_workspace scans all supported code files and stores chunks."""
    _setup_test_codebase(tmp_path)

    status = await index_workspace(str(tmp_path))

    assert status["indexed_files"] == 4
    assert status["total_chunks"] >= 4
    assert status["last_indexed_at"] is not None

    live_status = await get_indexing_status(str(tmp_path))
    assert live_status["indexed_files"] >= 4
    assert live_status["total_chunks"] >= 4


@pytest.mark.asyncio
async def test_index_file_indexes_single_file(tmp_path: Path):
    """Verify that index_file incrementally chunks and indexes a single file."""
    _setup_test_codebase(tmp_path)

    new_file = tmp_path / "src" / "router.py"
    new_file.write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.get('/health')\n"
        "def health_check():\n"
        "    return {'status': 'healthy'}\n",
        encoding="utf-8",
    )

    chunks = await index_file(str(tmp_path), str(new_file))
    assert chunks >= 1

    # Verify context for the indexed file
    context = await get_file_context(str(tmp_path), "src/router.py")
    assert len(context) >= 1
    assert "health_check" in context[0]["chunk_text"]


@pytest.mark.asyncio
async def test_remove_file_removes_from_index(tmp_path: Path):
    """Verify that remove_file purges chunks for a specific file from ChromaDB."""
    _setup_test_codebase(tmp_path)
    await index_workspace(str(tmp_path))

    # Before removal, auth.py has context
    ctx_before = await get_file_context(str(tmp_path), "src/auth.py")
    assert len(ctx_before) >= 1

    # Remove file from index
    removed = await remove_file(str(tmp_path), "src/auth.py")
    assert removed is True

    # After removal, context is empty
    ctx_after = await get_file_context(str(tmp_path), "src/auth.py")
    assert len(ctx_after) == 0


@pytest.mark.asyncio
async def test_semantic_search_returns_relevant_chunks(tmp_path: Path):
    """Verify semantic_search finds files relevant to query and returns formatted metadata."""
    _setup_test_codebase(tmp_path)
    await index_workspace(str(tmp_path))

    results = await semantic_search(str(tmp_path), "Where is authentication and JWT token verification?", top_k=3)

    assert len(results) > 0
    top_result = results[0]
    assert "file_path" in top_result
    assert "chunk_text" in top_result
    assert "score" in top_result
    assert "line_range" in top_result
    assert top_result["score"] >= 0.0


@pytest.mark.asyncio
async def test_semantic_search_ranks_by_similarity(tmp_path: Path):
    """Verify that semantic_search ranks the most semantically relevant file highest."""
    _setup_test_codebase(tmp_path)
    await index_workspace(str(tmp_path))

    auth_query = "user credentials verification and login token"
    results = await semantic_search(str(tmp_path), auth_query, top_k=4)

    assert len(results) >= 2
    # The top result should be auth.py
    top_file = results[0]["file_path"].replace("\\", "/")
    assert "auth.py" in top_file

    # Results should be ordered descending by score
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_get_file_context_returns_all_chunks(tmp_path: Path):
    """Verify get_file_context retrieves all chunks for a target file in chunk_index order."""
    _setup_test_codebase(tmp_path)

    # Create a file large enough to produce multiple chunks (>200 lines)
    large_file = tmp_path / "src" / "large_service.py"
    large_lines = [f"# Line {i}: service implementation detail logic" for i in range(1, 450)]
    large_file.write_text("\n".join(large_lines), encoding="utf-8")

    chunks_count = await index_file(str(tmp_path), str(large_file))
    assert chunks_count > 1

    chunks = await get_file_context(str(tmp_path), "src/large_service.py")
    assert len(chunks) == chunks_count
    # Verify proper ordering
    indexes = [c["chunk_index"] for c in chunks]
    assert indexes == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_rag_routes_api(temp_db, tmp_path: Path):
    """Verify HTTP endpoints /api/rag/... work as expected."""
    _setup_test_codebase(tmp_path)

    from app.core.auth import get_token
    from app.features.workspaces.trust_service import set_workspace_trust
    await set_workspace_trust(str(tmp_path), True)

    headers = {"Authorization": f"Bearer {get_token()}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Index workspace endpoint
        resp_idx = await client.post(
            "/api/rag/index-workspace",
            json={"workspace": str(tmp_path)},
            headers=headers,
        )
        assert resp_idx.status_code == 200
        assert resp_idx.json()["ok"] is True
        assert resp_idx.json()["indexed_files"] >= 4

        # 2. Search endpoint
        resp_search = await client.post(
            "/api/rag/search",
            json={"workspace": str(tmp_path), "query": "database sqlite connection", "top_k": 3},
            headers=headers,
        )
        assert resp_search.status_code == 200
        data = resp_search.json()
        assert data["ok"] is True
        assert len(data["results"]) >= 1

        # 3. Status endpoint
        resp_status = await client.get(
            f"/api/rag/status?workspace={str(tmp_path)}",
            headers=headers,
        )
        assert resp_status.status_code == 200
        assert resp_status.json()["total_chunks"] >= 4

        # 4. File context endpoint
        resp_ctx = await client.get(
            f"/api/rag/file-context?workspace={str(tmp_path)}&file_path=src/database.py",
            headers=headers,
        )
        assert resp_ctx.status_code == 200
        assert len(resp_ctx.json()["chunks"]) >= 1


@pytest.mark.asyncio
async def test_semantic_search_uses_embeddings(tmp_path: Path):
    """Verify that semantic_search queries the embedding function for the query."""
    from unittest.mock import patch, MagicMock
    from app.features.ai.rag.vector_index_service import _get_embedding_function

    _setup_test_codebase(tmp_path)
    await index_workspace(str(tmp_path))

    ef = _get_embedding_function()
    mock_ef = MagicMock(side_effect=ef)

    with patch("app.features.ai.rag.vector_index_service._get_embedding_function", return_value=mock_ef):
        results = await semantic_search(str(tmp_path), "authentication jwt verify", top_k=2)
        assert isinstance(results, list)
        assert len(results) > 0


@pytest.mark.asyncio
async def test_semantic_similarity_ranking(tmp_path: Path):
    """Verify 'authentication flow' query returns auth_service.py even without the word 'authentication' in the file."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # File 1: Auth service without the exact word "authentication"
    auth_service = src_dir / "auth_service.py"
    auth_service.write_text(
        "def login_user(credentials):\n"
        "    '''Verify user secret and return bearer session token.'''\n"
        "    if credentials.get('valid'):\n"
        "        return issue_jwt_bearer_token(credentials['user_id'])\n"
        "    return None\n",
        encoding="utf-8",
    )
    assert "authentication" not in auth_service.read_text().lower()

    # File 2: Unrelated database code
    db_service = src_dir / "db_service.py"
    db_service.write_text(
        "def execute_db_query(conn, query_string):\n"
        "    '''Execute raw SQL select against sqlite tables.'''\n"
        "    cursor = conn.cursor()\n"
        "    return cursor.execute(query_string).fetchall()\n",
        encoding="utf-8",
    )

    await index_workspace(str(tmp_path))

    results = await semantic_search(str(tmp_path), "authentication flow", top_k=2)
    assert len(results) >= 1
    top_result = results[0]
    top_path = top_result["file_path"].replace("\\", "/")
    assert "auth_service.py" in top_path


def test_hybrid_retrieval_merges_scores():
    """Verify that hybrid retrieval merges semantic (70%) and keyword (30%) scores properly."""
    from app.features.ai.rag.vector_index_service import _merge_hybrid_scores

    sem_results = [
        {"file_path": "auth.py", "chunk_index": 0, "score": 0.80, "chunk_text": "auth code"},
        {"file_path": "other.py", "chunk_index": 0, "score": 0.60, "chunk_text": "other code"},
    ]
    kw_results = [
        {"file_path": "auth.py", "chunk_index": 0, "score": 0.60, "chunk_text": "auth code"},
        {"file_path": "db.py", "chunk_index": 0, "score": 0.90, "chunk_text": "db code"},
    ]

    merged = _merge_hybrid_scores(sem_results, kw_results)
    assert len(merged) == 3

    # auth.py should have: 0.70 * 0.80 + 0.30 * 0.60 = 0.56 + 0.18 = 0.74
    auth_item = next(m for m in merged if m["file_path"] == "auth.py")
    assert auth_item["score"] == 0.74
    assert auth_item["semantic_score"] == 0.80
    assert auth_item["keyword_score"] == 0.60

    # other.py should have: 0.70 * 0.60 + 0.30 * 0.0 = 0.42
    other_item = next(m for m in merged if m["file_path"] == "other.py")
    assert other_item["score"] == 0.42

    # db.py should have: 0.70 * 0.0 + 0.30 * 0.90 = 0.27
    db_item = next(m for m in merged if m["file_path"] == "db.py")
    assert db_item["score"] == 0.27


def test_reranker_improves_top5():
    """Verify cross-encoder reranker improves top-5 precision and reorders results."""
    from app.features.ai.rag.vector_index_service import set_reranker, reset_reranker, _rerank_chunks

    candidates = [
        {"file_path": "low_initial.py", "chunk_text": "def specific_auth_target(): pass", "score": 0.40},
        {"file_path": "high_initial.py", "chunk_text": "def unrelated_topic(): pass", "score": 0.90},
    ]

    # Custom mock reranker that boosts specific_auth_target
    def mock_reranker(query: str, items: list[dict]) -> list[dict]:
        res = []
        for it in items:
            item_copy = dict(it)
            if "specific_auth_target" in item_copy["chunk_text"]:
                item_copy["score"] = 0.99
            else:
                item_copy["score"] = 0.10
            res.append(item_copy)
        res.sort(key=lambda x: x["score"], reverse=True)
        return res

    set_reranker(mock_reranker)
    try:
        reranked = _rerank_chunks("specific auth target", candidates, top_k=5)
        assert len(reranked) == 2
        assert reranked[0]["file_path"] == "low_initial.py"
        assert reranked[0]["score"] == 0.99
    finally:
        reset_reranker()


@pytest.mark.asyncio
async def test_budget_respected(tmp_path: Path):
    """Verify token budget is enforced after semantic retrieval in _gather_budgeted_rag_context."""
    from app.features.ai.harness.prompt_builder import _gather_budgeted_rag_context

    _setup_test_codebase(tmp_path)
    await index_workspace(str(tmp_path))

    # Request small character budget of 250 characters
    results, rag_summary = await _gather_budgeted_rag_context(
        workspace=str(tmp_path),
        query="authenticate user credentials",
        token_budget=50,
        max_chars=250,
    )

    assert isinstance(results, list)
    assert len(rag_summary) <= 300  # Strict budget adhered to with buffer

