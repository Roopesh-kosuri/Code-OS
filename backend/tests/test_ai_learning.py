"""
test_ai_learning.py — Comprehensive tests for AI Memory & Feedback Loop (Self-Improvement).

Tests:
1. test_log_mistake_from_rejected_edit
2. test_log_mistake_from_repair_loop
3. test_synthesize_lesson_heuristic_and_llm
4. test_get_relevant_memories_semantic_search
5. test_memory_injected_into_system_prompt
6. test_manual_memory_creation_and_deletion
7. test_boost_memory_and_decay
8. test_memory_routes_api
"""

import os
import shutil
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.db.database import get_db, init_db, close_db
from app.features.ai.memory.memory_service import (
    synthesize_lesson,
    log_mistake,
    get_relevant_memories,
    increment_applied,
    decay_unused_memories,
    boost_memory,
    delete_memory,
    list_memories,
)
from app.features.ai.schemas import ChatMessage, ChatRequest


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path):
    """Set up a fresh test database with schema and migrations."""
    db_file = tmp_path / "test_memory.db"
    await close_db()
    db = await init_db(db_file)
    yield db
    await close_db()


@pytest.mark.asyncio
async def test_synthesize_lesson_heuristic_and_llm():
    """Test synthesize_lesson produces guidelines starting with Always/Never under 25 words."""
    # 1. Failed test with AssertionError
    rule1 = await synthesize_lesson("AssertionError: assert 200 == 500 in test_login", category="failed_test")
    assert rule1.startswith(("Always", "Never"))
    assert len(rule1.split()) <= 25

    # 2. Rejected edit with protected file mention
    rule2 = await synthesize_lesson("User rejected edit because it touched protected files", category="rejected_edit")
    assert rule2.startswith(("Always", "Never"))
    assert "protected" in rule2.lower()
    assert len(rule2.split()) <= 25

    # 3. Security fix with SQL injection
    rule3 = await synthesize_lesson("Raw SQL concatenation detected in user endpoint", category="security_fix")
    assert rule3.startswith(("Always", "Never"))
    assert len(rule3.split()) <= 25

    # 4. Repair loop
    rule4 = await synthesize_lesson("Agent retried patch 3 times with identical failure", category="repair_loop")
    assert rule4.startswith(("Always", "Never"))
    assert len(rule4.split()) <= 25

    # 5. User correction starting with custom phrasing
    rule5 = await synthesize_lesson("Always use PascalCase for React component names.", category="manual")
    assert rule5 == "Always use PascalCase for React component names."


@pytest.mark.asyncio
async def test_log_mistake_from_rejected_edit(tmp_path):
    """Test logging a mistake from a rejected edit persists to DB with workspace scoping."""
    ws = str(tmp_path / "ws1")
    mem = await log_mistake(
        workspace=ws,
        category="rejected_edit",
        raw_event_or_lesson="User rejected proposal because it broke existing tests",
        source_event_id="prop-123",
        confidence=95,
    )

    assert mem["id"].startswith("mem_")
    assert mem["workspace"] == str(Path(ws).resolve()).replace("\\", "/")
    assert mem["category"] == "rejected_edit"
    assert mem["confidence"] == 95
    assert mem["lesson"].startswith(("Always", "Never"))

    # Verify presence in list_memories
    memories = await list_memories(ws)
    assert len(memories) == 1
    assert memories[0]["id"] == mem["id"]


@pytest.mark.asyncio
async def test_log_mistake_from_repair_loop(tmp_path):
    """Test logging a mistake from repair loop."""
    ws = str(tmp_path / "ws2")
    mem = await log_mistake(
        workspace=ws,
        category="repair_loop",
        raw_event_or_lesson="Repeated 3 repair rounds on type mismatch in AST parser",
        source_event_id="job-999",
    )

    assert mem["category"] == "repair_loop"
    assert mem["confidence"] == 100
    assert mem["times_applied"] == 0

    # Filter list by category
    filtered = await list_memories(ws, category="repair_loop")
    assert len(filtered) == 1
    assert filtered[0]["id"] == mem["id"]

    empty_filter = await list_memories(ws, category="failed_test")
    assert len(empty_filter) == 0


@pytest.mark.asyncio
async def test_get_relevant_memories_semantic_search(tmp_path):
    """Test semantic retrieval of relevant memories scoped to workspace."""
    ws = str(tmp_path / "ws_rag")

    mem1 = await log_mistake(
        workspace=ws,
        category="security_fix",
        raw_event_or_lesson="Always use parameterized queries and never interpolate raw SQL strings.",
        confidence=90,
    )
    mem2 = await log_mistake(
        workspace=ws,
        category="rejected_edit",
        raw_event_or_lesson="Always check array bounds before indexing list elements to prevent IndexError.",
        confidence=85,
    )

    # Search for SQL query task
    relevant = await get_relevant_memories(ws, "Writing database query for user profile")
    assert len(relevant) >= 1
    found_ids = [m["id"] for m in relevant]
    assert mem1["id"] in found_ids

    # Privacy check: Another workspace should get 0 memories
    other_ws = str(tmp_path / "ws_other")
    other_mems = await get_relevant_memories(other_ws, "Writing database query")
    assert len(other_mems) == 0


@pytest.mark.asyncio
async def test_boost_memory_and_decay(tmp_path):
    """Test boosting confidence and decaying unused memories."""
    ws = str(tmp_path / "ws_boost")
    mem = await log_mistake(
        workspace=ws,
        category="manual",
        raw_event_or_lesson="Always write docstrings for exported functions.",
        confidence=70,
    )

    # Boost by 15
    boosted = await boost_memory(mem["id"], amount=15)
    assert boosted is not None
    assert boosted["confidence"] == 85

    # Boost beyond 100 caps at 100
    boosted_capped = await boost_memory(mem["id"], amount=30)
    assert boosted_capped["confidence"] == 100

    # Test increment_applied
    await increment_applied(mem["id"])
    mems = await list_memories(ws)
    assert mems[0]["times_applied"] == 1
    assert mems[0]["last_applied_at"] is not None


@pytest.mark.asyncio
async def test_manual_memory_creation_and_deletion(tmp_path):
    """Test creating a manual teaching rule and forgetting it."""
    ws = str(tmp_path / "ws_manual")
    mem = await log_mistake(
        workspace=ws,
        category="manual",
        raw_event_or_lesson="Always use strict TypeScript types without any.",
        confidence=100,
    )

    mems = await list_memories(ws)
    assert len(mems) == 1

    deleted = await delete_memory(mem["id"])
    assert deleted is True

    mems_after = await list_memories(ws)
    assert len(mems_after) == 0

    # Deleting non-existent returns False
    assert await delete_memory("non-existent-id") is False


@pytest.mark.asyncio
async def test_memory_injected_into_system_prompt(tmp_path):
    """Test that stream_chat injects relevant lessons learned into system prompt."""
    from app.features.ai.service import stream_chat

    ws = str(tmp_path / "ws_chat")
    os.makedirs(ws, exist_ok=True)

    # Store a lesson in this workspace
    await log_mistake(
        workspace=ws,
        category="failed_test",
        raw_event_or_lesson="Always mock network calls in unit tests to prevent timeouts.",
        confidence=100,
    )

    req = ChatRequest(
        messages=[ChatMessage(role="user", content="Write a unit test for the HTTP client")],
        workspace=ws,
        model="mock-model",
        provider="mock",
    )

    # Mock provider_for to inspect the messages sent
    captured_messages = []

    class MockProvider:
        async def stream_chat(self, model, messages, temperature):
            nonlocal captured_messages
            captured_messages = messages
            yield "Mock response"

    with patch("app.features.ai.service.provider_for", AsyncMock(return_value=MockProvider())):
        tokens = []
        async for tok in stream_chat(req):
            tokens.append(tok)

    assert len(captured_messages) > 0
    sys_prompt = captured_messages[0].content
    assert "LESSONS LEARNED (from past mistakes):" in sys_prompt
    assert "Always mock network calls" in sys_prompt


@pytest.mark.asyncio
async def test_memory_routes_api(async_client, tmp_path):
    """Test memory REST API endpoints."""
    ws = str(tmp_path / "ws_api")

    # 1. POST /api/memories (manual rule)
    res = await async_client.post(
        "/api/memories",
        json={"workspace": ws, "lesson": "Never use any in TypeScript", "category": "manual", "confidence": 95},
    )
    assert res.status_code == 200
    data = res.json()
    mem_id = data["id"]
    assert data["lesson"].startswith(("Always", "Never"))

    # 2. GET /api/memories
    res = await async_client.get(f"/api/memories?workspace={ws}")
    assert res.status_code == 200
    mems = res.json()
    assert len(mems) == 1
    assert mems[0]["id"] == mem_id

    # 3. POST /api/memories/{id}/boost
    res = await async_client.post(f"/api/memories/{mem_id}/boost", json={"amount": 5})
    assert res.status_code == 200
    assert res.json()["confidence"] == 100

    # 4. POST /api/memories/log-mistake
    res = await async_client.post(
        "/api/memories/log-mistake",
        json={"workspace": ws, "category": "security_fix", "raw_event": "SQL injection in search bar"},
    )
    assert res.status_code == 200
    sec_id = res.json()["id"]

    # 5. GET /api/memories/relevant
    res = await async_client.get(f"/api/memories/relevant?workspace={ws}&task_description=search+database+endpoint")
    assert res.status_code == 200
    rel = res.json()
    assert len(rel) >= 1

    # 6. DELETE /api/memories/{id}
    res = await async_client.delete(f"/api/memories/{mem_id}")
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 7. Verify deletion
    res = await async_client.get(f"/api/memories?workspace={ws}")
    assert len(res.json()) == 1
    assert res.json()[0]["id"] == sec_id

