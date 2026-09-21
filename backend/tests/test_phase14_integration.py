"""Phase 14 Integration & Static Regression Guard Tests.

Verifies:
1. Zero bare "successfully completed" occurrences in backend/app and src.
2. Completion paths gate through verification matrix.
3. Verification hooks run in canonical order and record events.
4. Cancellation event halts verification and yields UNVERIFIED.
5. Multi-path turns verify all touched files in a single pass.
"""

import ast
import asyncio
import os
import re
from pathlib import Path
import pytest

from app.features.ai.harness.verification_matrix import (
    execute_verification_matrix,
    compute_verdict,
    Verdict,
    VerdictState,
    VerifyResult,
    VerifyStatus,
)


FORBIDDEN_COMPLETION_PHRASES = (
    "successfully completed",
    "completed successfully",
    "workflow execution completed successfully",
    "all tasks completed successfully",
)


def test_no_production_string_says_successfully_completed():
    """Verify that zero occurrences of bare completion phrases exist in production code."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backend_app = repo_root / "backend" / "app"
    src_dir = repo_root / "src"

    violations: list[str] = []

    # Check backend/app python files
    for py_file in backend_app.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(content.splitlines(), start=1):
            line_lower = line.lower()
            # Allow docstrings/comments that specifically document the ban
            if "strictly forbidden" in line_lower or "do not say" in line_lower or "forbidden" in line_lower:
                continue
            for phrase in FORBIDDEN_COMPLETION_PHRASES:
                if phrase in line_lower:
                    violations.append(f"{py_file.relative_to(repo_root)}:{line_no} [{phrase}] -> {line.strip()}")

    # Check src frontend files (production code only)
    for ext in ("*.ts", "*.tsx", "*.js", "*.jsx"):
        for js_file in src_dir.rglob(ext):
            if "__tests__" in js_file.parts or ".test." in js_file.name or ".spec." in js_file.name:
                continue
            content = js_file.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(content.splitlines(), start=1):
                line_lower = line.lower()
                if "strictly forbidden" in line_lower or "do not say" in line_lower or "forbidden" in line_lower:
                    continue
                for phrase in FORBIDDEN_COMPLETION_PHRASES:
                    if phrase in line_lower:
                        violations.append(f"{js_file.relative_to(repo_root)}:{line_no} [{phrase}] -> {line.strip()}")

    assert not violations, (
        f"Found {len(violations)} occurrences of forbidden completion phrases:\n"
        + "\n".join(violations)
    )


def test_completion_paths_all_use_verdict():
    """Verify that chat_harness and dag_engine completion points are gated by verification matrix."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    chat_harness_path = repo_root / "backend" / "app" / "features" / "ai" / "chat_harness.py"
    dag_engine_path = repo_root / "backend" / "app" / "features" / "ai" / "dag_engine.py"

    chat_code = chat_harness_path.read_text(encoding="utf-8")
    dag_code = dag_engine_path.read_text(encoding="utf-8")

    # In chat_harness, _execute_turn_verification must be defined and called
    assert "def _execute_turn_verification(" in chat_code
    assert "async for ve in _execute_turn_verification(" in chat_code

    # In dag_engine, no bare "successfully completed" in task or job logs
    assert "Workflow execution completed successfully" not in dag_code
    assert "successfully completed task" not in dag_code
    assert "Workflow execution verified." in dag_code
    assert "completed task '{task['title']}' (verified)" in dag_code


@pytest.mark.asyncio
async def test_hooks_run_in_order_and_all_recorded(tmp_path):
    """Verify that verification matrix executes hooks in canonical order and records all SSE events."""
    # Create test workspace
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('hello')\n")

    events: list[str] = []

    verdict, results = await execute_verification_matrix(
        workspace_root=tmp_path,
        touched_files=["hello.py"],
        pre_images={"hello.py": None},
        readback_statuses={"hello.py": "passed"},
        raw_settings={"code_os_verify_enabled": True, "code_os_verify_security_enabled": True},
        event_emitter=events.append,
    )

    # Events emitted: verification_started, verification_hook_finished (readback), hook_finished (security), hook_finished (tests), verification_result
    event_names = []
    for ev in events:
        for line in ev.splitlines():
            if line.startswith("event: "):
                event_names.append(line.split("event: ")[1].strip())

    assert "verification_started" in event_names
    assert "verification_hook_finished" in event_names
    assert "verification_result" in event_names

    # First event must be verification_started, last must be verification_result
    assert event_names[0] == "verification_started"
    assert event_names[-1] == "verification_result"

    # Hook results order: readback_hash, security_scan, test_suite
    hook_names = [r.hook for r in results]
    assert hook_names[0] == "readback_hash"
    assert hook_names[1] == "security_scan"
    assert hook_names[2] == "test_suite"


@pytest.mark.asyncio
async def test_cancel_turn_cancels_verification(tmp_path):
    """Verify that cancellation halts verification early and marks verdict UNVERIFIED."""
    cancel_ev = asyncio.Event()
    cancel_ev.set()  # Already cancelled

    events: list[str] = []
    verdict, results = await execute_verification_matrix(
        workspace_root=tmp_path,
        touched_files=["app.py"],
        pre_images={"app.py": None},
        readback_statuses={"app.py": "passed"},
        event_emitter=events.append,
        cancellation_event=cancel_ev,
    )

    assert verdict.state == VerdictState.UNVERIFIED
    assert any("cancelled" in r.lower() for r in verdict.reasons)


@pytest.mark.asyncio
async def test_multi_apply_turn_runs_matrix_once_with_all_paths(tmp_path):
    """Verify that multi-file changes are all passed to verification matrix in one pass."""
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("x = 1\n")
    f2.write_text("y = 2\n")

    events: list[str] = []
    verdict, results = await execute_verification_matrix(
        workspace_root=tmp_path,
        touched_files=["a.py", "b.py"],
        pre_images={"a.py": None, "b.py": None},
        readback_statuses={"a.py": "passed", "b.py": "passed"},
        event_emitter=events.append,
    )

    # Readback hash verified both files
    assert results[0].hook == "readback_hash"
    assert results[0].status == VerifyStatus.PASSED

    # Verification started event included both files
    started_ev = [ev for ev in events if "verification_started" in ev][0]
    assert "a.py" in started_ev
    assert "b.py" in started_ev


@pytest.mark.asyncio
async def test_execute_turn_verification_generator(tmp_path):
    """Test the chat_harness._execute_turn_verification generator directly."""
    from app.features.ai.chat_harness import _execute_turn_verification

    f = tmp_path / "math_mod.py"
    f.write_text("def add(a, b): return a + b\n")

    yielded_events: list[str] = []
    async for ev in _execute_turn_verification(
        workspace=str(tmp_path),
        turn_applied_paths=["math_mod.py"],
        turn_pre_images={"math_mod.py": None},
        turn_readback_statuses={"math_mod.py": "passed"},
    ):
        yielded_events.append(ev)

    assert len(yielded_events) >= 3
    # The last yielded event must be done
    assert "event: done" in yielded_events[-1]
    assert "successfully completed" not in yielded_events[-1].lower()
