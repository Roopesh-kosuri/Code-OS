"""Regression tests for Phase 6.2: Proposal Integrity Gate."""

import asyncio
import sys
from types import SimpleNamespace
from types import ModuleType

import pytest
from app.features.ai.harness.content_integrity import (
    validate_content_integrity,
    is_placeholder_content,
    validate_language_syntax,
    is_truncated_content,
    check_cross_turn_contamination,
    validate_file_target,
)
from app.features.ai.schemas import FileChange
from app.features.ai.harness.stage_finalizer import _finalize_staged_changes
from app.features.ai.harness import stage_finalizer


async def _finalize_with_approval(staged, workspace):
    """Drive the approval handshake and collect a real finalization transaction."""
    events = []

    async def collect():
        async for event in _finalize_staged_changes(staged, str(workspace), user_query="update file"):
            events.append(event)

    task = asyncio.create_task(collect())
    for _ in range(100):
        if stage_finalizer._pending_approvals:
            pending = next(iter(stage_finalizer._pending_approvals.values()))
            pending.approved = True
            pending.event.set()
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("approval request was not created")
    await task
    return "".join(events)


def _patch_transaction_dependencies(monkeypatch, apply):
    async def create(_payload):
        return SimpleNamespace(id="transaction-proposal")

    async def no_tests(*_args):
        return False, 0, 0, "no required test runner"

    settings_service = ModuleType("app.features.settings.service")

    async def get_setting(_key):
        return "false"

    settings_service.get_setting = get_setting
    verifier = ModuleType("app.features.automation.verifier")
    verifier.should_trigger_auto_verify = lambda *_args, **_kwargs: False
    verifier.run_browser_verification = None

    monkeypatch.setattr(stage_finalizer, "_get_create_proposal", lambda: create)
    monkeypatch.setattr(stage_finalizer, "_get_apply_proposal", lambda: apply)
    monkeypatch.setattr(stage_finalizer, "_discover_and_run_test_snapshot", no_tests)
    monkeypatch.setitem(sys.modules, "app.features.settings.service", settings_service)
    monkeypatch.setitem(sys.modules, "app.features.automation.verifier", verifier)


def test_reject_placeholder_code():
    """Verify detection and blocking of generic placeholder patterns."""
    placeholders = [
        "your updated code here",
        "// your code here",
        "// TODO: implement this function",
        "# TODO: implement this function",
        "pass  # implement later",
        "/* insert code here */",
        "// <insert code>",
        "# REPLACE THIS",
    ]
    for p in placeholders:
        is_ph, msg = is_placeholder_content(p)
        assert is_ph is True, f"Failed to detect placeholder in: '{p}'"

        status, warning = validate_content_integrity("test.py", p)
        assert status in ("incomplete", "blocked")
        assert "placeholder" in (warning or "").lower()

    # Valid code should not be flagged as placeholder
    valid_py = "def hello():\n    return 'world'\n"
    is_ph, _ = is_placeholder_content(valid_py)
    assert is_ph is False


def test_reject_syntax_errors():
    """Verify syntax validation for Python, JS/TS, and JSON."""
    bad_py = "def bad_syntax(:\n    pass\n"
    ok, err = validate_language_syntax("broken.py", bad_py)
    assert ok is False
    assert "syntax error" in (err or "").lower()

    # Clean python
    ok_py = "def good_syntax():\n    return True\n"
    ok, _ = validate_language_syntax("good.py", ok_py)
    assert ok is True

    # Broken JSON
    bad_json = '{"key": "value",}'
    ok, _ = validate_language_syntax("config.json", bad_json)
    assert ok is False

    # Broken JS braces
    bad_js = "function test() { if (true) { return 1; }"
    ok, _ = validate_language_syntax("app.js", bad_js)
    assert ok is False

    # Valid JS
    good_js = "function test() { if (true) { return 1; } }"
    ok, _ = validate_language_syntax("app.js", good_js)
    assert ok is True


def test_reject_truncation():
    """Verify truncation detection on incomplete file contents."""
    truncated_samples = [
        "function runProcess() {\n    return\n",  # unclosed brace
        "import os\ndef test():",  # cut off at def
    ]
    for sample in truncated_samples:
        is_trunc, _ = is_truncated_content(sample)
        assert is_trunc is True, f"Expected truncation detected for: {sample}"

    valid_sample = "def calculate_total():\n    return 42\n"
    is_trunc, _ = is_truncated_content(valid_sample)
    assert is_trunc is False


def test_reject_cross_turn_contamination():
    """Verify detection when file content mirrors assistant conversation prose."""
    history = [
        {"role": "user", "content": "Can you review my CV?"},
        {
            "role": "assistant",
            "content": "Roopesh Ram Varma Kosuri's CV was reviewed and no references were found.",
        },
    ]
    garbage_content = "Roopesh Ram Varma Kosuri's CV was reviewed and no references were found."
    is_contam, warning = check_cross_turn_contamination(garbage_content, conversation_messages=history)
    assert is_contam is True
    assert "unrelated earlier response" in warning or "cross-turn contamination" in warning

    normal_code = "import express from 'express';\nconst app = express();\n"
    is_contam, _ = check_cross_turn_contamination(normal_code, conversation_messages=history)
    assert is_contam is False


def test_file_target_grounding():
    """Verify file grounding checks against prompt intent."""
    # node.js created when prompt had nothing to do with node
    is_gr, reason = validate_file_target("node.js", user_query="implement user login in python")
    assert is_gr is False
    assert "node.js" in (reason or "")

    is_gr_valid, _ = validate_file_target("src/login/login_module.py", user_query="implement user login in python")
    assert is_gr_valid is True


def test_iteration_cap_filters_incomplete_edits():
    """Verify that validate_content_integrity accurately categorizes incomplete vs valid files."""
    status_ph, _ = validate_content_integrity("src/login/login_module.py", "your updated code here")
    assert status_ph in ("incomplete", "blocked")

    real_code = "def authenticate(user, password):\n    return True\n"
    status_good, _ = validate_content_integrity("src/login/login_module.py", real_code)
    assert status_good == "valid"


@pytest.mark.asyncio
async def test_proposal_integrity_gate_blocks_proposal():
    """Verify that stage_finalizer blocks proposals containing syntax-broken files."""
    staged = [
        FileChange(
            path="broken.py",
            original="",
            updated="def broken_func(:\n    pass\n",
        )
    ]
    events = []
    async for evt in _finalize_staged_changes(staged, workspace="C:\\fake\\ws", tier=1, user_query="fix"):
        events.append(evt)

    # Must emit rejection/error event
    event_str = "".join(events)
    assert "integrity_check_failed" in event_str or "Syntax error" in event_str or "Proposal Integrity Check Failed" in event_str


@pytest.mark.asyncio
async def test_post_apply_read_back_mismatch_restores_original_bytes(tmp_path, monkeypatch):
    target = tmp_path / "module.txt"
    original = b"original\x00bytes\n"
    target.write_bytes(original)
    staged = [FileChange(path="module.txt", original=original.decode("utf-8"), updated="汉字🙂\n")]

    async def apply(_proposal_id):
        target.write_bytes("汉字🙂\n".encode("utf-16"))

    _patch_transaction_dependencies(monkeypatch, apply)
    events = await _finalize_with_approval(staged, tmp_path)

    assert target.read_bytes() == original
    assert '"reason": "rolled_back"' in events
    assert "read_back_failed" in events


@pytest.mark.asyncio
async def test_required_verification_failure_restores_original_bytes(tmp_path, monkeypatch):
    target = tmp_path / "module.txt"
    original = b"before\n"
    target.write_bytes(original)
    staged = [FileChange(path="module.txt", original="before\n", updated="after\n")]

    async def apply(_proposal_id):
        target.write_bytes(b"after\n")

    calls = 0

    async def regression_snapshot(*_args):
        nonlocal calls
        calls += 1
        return (True, 2, 0, "2 passed") if calls == 1 else (True, 1, 1, "1 passed, 1 failed")

    _patch_transaction_dependencies(monkeypatch, apply)
    monkeypatch.setattr(stage_finalizer, "_discover_and_run_test_snapshot", regression_snapshot)
    events = await _finalize_with_approval(staged, tmp_path)

    assert target.read_bytes() == original
    assert '"reason": "rolled_back"' in events
    assert "test_regression" in events


@pytest.mark.asyncio
async def test_created_file_rollback_removes_file_and_empty_parent_dirs(tmp_path, monkeypatch):
    target = tmp_path / "created" / "nested" / "module.txt"
    staged = [FileChange(path="created/nested/module.txt", original="", updated="created\n")]

    async def apply(_proposal_id):
        target.parent.mkdir(parents=True)
        target.write_bytes(b"wrong\n")

    _patch_transaction_dependencies(monkeypatch, apply)
    events = await _finalize_with_approval(staged, tmp_path)

    assert not target.exists()
    assert not target.parent.exists()
    assert not target.parent.parent.exists()
    assert '"reason": "rolled_back"' in events


@pytest.mark.asyncio
async def test_restore_failure_is_surfaced_as_hard_rollback_failed(tmp_path, monkeypatch):
    target = tmp_path / "module.txt"
    target.write_text("before\n", encoding="utf-8")
    staged = [FileChange(path="module.txt", original="before\n", updated="expected\n")]

    async def apply(_proposal_id):
        target.write_text("wrong\n", encoding="utf-8")

    _patch_transaction_dependencies(monkeypatch, apply)
    monkeypatch.setattr(
        stage_finalizer,
        "_restore_checkpoint",
        lambda *_args: (False, "simulated restore I/O failure", []),
    )
    events = await _finalize_with_approval(staged, tmp_path)

    assert '"reason": "rollback_failed"' in events
    assert "Rollback failed after read_back_failed" in events
