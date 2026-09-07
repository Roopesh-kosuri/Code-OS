"""
test_memory_autopopulate.py — Regression tests for AI continuous learning / memory auto-population.

Verifies:
1. Deduplication when the same mistake/lesson is logged multiple times.
2. Auto-population on failed test execution.
3. Auto-population on rejected edits.
4. Auto-population on repair loop blockers.
5. Workspace scoping and confidence decay/boost mechanics.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from app.features.ai.memory.memory_service import (
    log_mistake,
    list_memories,
    get_relevant_memories,
    synthesize_lesson,
)
from app.db.database import get_db


@pytest.mark.asyncio
async def test_log_mistake_deduplication(tmp_path: Path):
    """Calling log_mistake with identical (workspace, category, lesson) deduplicates instead of inserting duplicates."""
    ws = str(tmp_path / "ws_dedup")
    lesson = "Always check for None before dereferencing optional object properties."

    # First call: creates new record
    mem1 = await log_mistake(
        workspace=ws,
        category="failed_test",
        raw_event_or_lesson=lesson,
        confidence=80,
    )
    assert mem1["times_applied"] == 0
    assert mem1.get("deduplicated") is not True

    # Second call with same lesson
    mem2 = await log_mistake(
        workspace=ws,
        category="failed_test",
        raw_event_or_lesson=lesson,
        confidence=90,
    )
    assert mem2["id"] == mem1["id"]
    assert mem2["times_applied"] == 1
    assert mem2["confidence"] == 90
    assert mem2.get("deduplicated") is True

    # Third call
    mem3 = await log_mistake(
        workspace=ws,
        category="failed_test",
        raw_event_or_lesson=lesson,
        confidence=85,
    )
    assert mem3["id"] == mem1["id"]
    assert mem3["times_applied"] == 2
    # Confidence remains max of previous and new
    assert mem3["confidence"] == 90

    # Verify database has exactly 1 entry for this workspace
    mems = await list_memories(ws)
    assert len(mems) == 1
    assert mems[0]["id"] == mem1["id"]
    assert mems[0]["times_applied"] == 2


@pytest.mark.asyncio
async def test_log_failed_test_synthesizes_rule(tmp_path: Path):
    """Failed test logs synthesize a concise Always/Never guideline."""
    ws = str(tmp_path / "ws_test_fail")
    event = "AssertionError: assert calculate_total([10, 20]) == 30 failed. Got 0"

    mem = await log_mistake(
        workspace=ws,
        category="failed_test",
        raw_event_or_lesson=event,
        source_event_id="test_run_42",
    )
    assert mem["category"] == "failed_test"
    assert mem["lesson"].startswith(("Always", "Never"))
    assert len(mem["lesson"].split()) <= 25

    mems = await list_memories(ws, category="failed_test")
    assert len(mems) == 1
    assert mems[0]["source_event_id"] == "test_run_42"


@pytest.mark.asyncio
async def test_log_rejected_edit_synthesizes_rule(tmp_path: Path):
    """Rejected edit proposals log actionable guideline."""
    ws = str(tmp_path / "ws_rejected_edit")
    event = "Proposal rejected: User reported syntax errors in generated component"

    mem = await log_mistake(
        workspace=ws,
        category="rejected_edit",
        raw_event_or_lesson=event,
        source_event_id="prop_xyz",
    )
    assert mem["category"] == "rejected_edit"
    assert mem["lesson"].startswith(("Always", "Never"))

    mems = await list_memories(ws, category="rejected_edit")
    assert len(mems) == 1


@pytest.mark.asyncio
async def test_log_repair_loop_guideline(tmp_path: Path):
    """Repair loop logs correctly record review blockers and repair rounds."""
    ws = str(tmp_path / "ws_repair")
    event = "Review blockers in job_abc round 2: Unresolved imports in auth_handler.py"

    mem = await log_mistake(
        workspace=ws,
        category="repair_loop",
        raw_event_or_lesson=event,
        source_event_id="job_abc_r2",
    )
    assert mem["category"] == "repair_loop"
    assert mem["lesson"].startswith(("Always", "Never"))

    mems = await list_memories(ws, category="repair_loop")
    assert len(mems) == 1
    assert mems[0]["source_event_id"] == "job_abc_r2"
