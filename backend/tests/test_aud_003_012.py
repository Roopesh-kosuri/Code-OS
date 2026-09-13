"""
backend/tests/test_aud_003_012.py -- Regression tests for AUD-003 and AUD-012.

AUD-003: test_contamination_gate_blocks_copied_prose_in_live_flow
AUD-012: test_rag_queue_bounded_under_burst
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path

from app.features.ai.schemas import FileChange
from app.features.ai.harness.content_integrity import validate_content_integrity, check_cross_turn_contamination
from app.features.ai.harness.stage_finalizer import _finalize_staged_changes
from app.features.ai.harness.approval_coordinator import _pending_approvals, clear_all_pending
from app.features.ai.rag.vector_index_service import (
    schedule_rag_reindex,
    cancel_rag_reindex,
    get_rag_reindex_queue_size,
    _pending_reindex,
    MAX_REINDEX_QUEUE_SIZE,
)


# ------------------------------------------------------------------------------------
# AUD-003: Proposal Integrity Contamination Gate Wiring
# ------------------------------------------------------------------------------------

class TestAud003ContaminationGate:
    """Verify live finalizer blocks copied prose using provenance-separated history."""

    def setup_method(self):
        clear_all_pending()

    def teardown_method(self):
        clear_all_pending()

    @pytest.mark.asyncio
    async def test_contamination_gate_blocks_copied_prose_in_live_flow(self, tmp_path):
        """End-to-end: live finalizer with cross-turn copied assistant prose blocks proposal."""
        copied_prose = (
            "Roopesh Ram Varma Kosuri's CV was reviewed and no references were found in the document."
        )
        history = [
            {"role": "user", "content": "Can you check my CV?"},
            {"role": "assistant", "content": copied_prose, "provenance": "assistant_prose"},
        ]

        staged_changes = [
            FileChange(
                path="output.txt",
                original="",
                updated=copied_prose,
            )
        ]

        events = []
        async for ev in _finalize_staged_changes(
            staged_changes=staged_changes,
            workspace=str(tmp_path),
            tier=1,
            user_query="save the notes",
            conversation_messages=history,
        ):
            events.append(ev)

        # Must emit integrity_check_failed finalization
        finalization_events = [e for e in events if "event: finalization" in e]
        assert finalization_events, "AUD-003: finalization event must be emitted"
        final_payload = json.loads(finalization_events[0].split("data: ", 1)[1].strip())
        assert final_payload.get("success") is False, "AUD-003: proposal must be rejected"
        assert final_payload.get("reason") == "integrity_check_failed"

        # No pending approvals created
        assert len(_pending_approvals) == 0, "AUD-003: blocked proposal must not create pending approval"

    def test_ordinary_source_repetition_not_blocked(self):
        """Ordinary code repetition from user or tool does NOT trigger false-positive contamination."""
        normal_code = "def calculate_total(a: int, b: int) -> int:\n    return a + b\n"
        history = [
            {"role": "user", "content": "Please implement calculate_total(a: int, b: int) -> int returning a + b"},
        ]

        status, warning = validate_content_integrity(
            path="calc.py",
            content=normal_code,
            user_query="implement calculate_total",
            conversation_messages=history,
        )
        assert status == "valid", f"AUD-003: normal code repetition must be valid, got {status}: {warning}"
        assert warning is None

    def test_check_cross_turn_contamination_provenance_filter(self):
        """Assistant prose triggers contamination; user code instruction does not."""
        prose = "Roopesh Ram Varma Kosuri's CV was reviewed and no references were found in the document."
        code = "def add(x: int, y: int) -> int:\n    return x + y\n"

        history_assistant = [{"role": "assistant", "content": prose, "provenance": "assistant_prose"}]
        history_user = [{"role": "user", "content": code, "provenance": "user"}]

        # Staging assistant prose is flagged as contamination
        is_contam, warn = check_cross_turn_contamination(prose, conversation_messages=history_assistant)
        assert is_contam is True

        # Staging user code is NOT flagged as contamination
        is_contam2, _ = check_cross_turn_contamination(code, conversation_messages=history_user)
        assert is_contam2 is False


# ------------------------------------------------------------------------------------
# AUD-012: RAG Reindex Queue Bounded & Coalesced
# ------------------------------------------------------------------------------------

class TestAud012RagQueueBound:
    """Verify RAG reindex queue has bounded memory, per-path coalescing, and cancellation."""

    def setup_method(self):
        _pending_reindex.clear()

    def teardown_method(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(cancel_rag_reindex())
            else:
                loop.run_until_complete(cancel_rag_reindex())
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_rag_queue_bounded_under_burst(self, tmp_path):
        """Tens of thousands of saves remain bounded and index final state correctly."""
        file_a = tmp_path / "burst_file.py"
        file_a.write_text("initial = True\n", encoding="utf-8")

        loop = asyncio.get_running_loop()

        # Burst 1: 1,000 rapid modified events for a single file
        for _ in range(1000):
            schedule_rag_reindex(str(tmp_path), "burst_file.py", "modified", loop=loop)

        # Queue size for a single file must be exactly 1 (coalesced)
        assert get_rag_reindex_queue_size() == 1, (
            f"AUD-012: single file burst must coalesce to size 1, got {get_rag_reindex_queue_size()}"
        )

        # Then deleted event arrives: last-event-wins
        schedule_rag_reindex(str(tmp_path), "burst_file.py", "deleted", loop=loop)
        assert get_rag_reindex_queue_size() == 1
        key = (str(tmp_path), str(file_a.resolve()))
        assert _pending_reindex[key] == "deleted", "AUD-012: last-event-wins must reflect 'deleted'"

        # Then modified event arrives: flips back to 'modified'
        schedule_rag_reindex(str(tmp_path), "burst_file.py", "modified", loop=loop)
        assert _pending_reindex[key] == "modified", "AUD-012: last-event-wins must reflect 'modified'"

        # Burst 2: 1,500 distinct files must stay bounded by MAX_REINDEX_QUEUE_SIZE
        for i in range(MAX_REINDEX_QUEUE_SIZE + 500):
            p = tmp_path / f"file_{i}.py"
            p.write_text(f"x = {i}\n", encoding="utf-8")
            schedule_rag_reindex(str(tmp_path), f"file_{i}.py", "modified", loop=loop)

        assert get_rag_reindex_queue_size() <= MAX_REINDEX_QUEUE_SIZE, (
            f"AUD-012: queue size exceeded maximum bound: {get_rag_reindex_queue_size()} > {MAX_REINDEX_QUEUE_SIZE}"
        )

    @pytest.mark.asyncio
    async def test_rag_queue_lifecycle_cancellation(self, tmp_path):
        """cancel_rag_reindex cleanly stops the worker and clears pending queue items."""
        loop = asyncio.get_running_loop()
        f = tmp_path / "test.py"
        f.write_text("x = 1\n", encoding="utf-8")

        schedule_rag_reindex(str(tmp_path), "test.py", "modified", loop=loop)
        assert get_rag_reindex_queue_size() == 1

        await cancel_rag_reindex()
        assert get_rag_reindex_queue_size() == 0, "AUD-012: queue must be cleared on cancellation"
