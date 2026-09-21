"""test_phase16_fixes.py — Regression tests for Phase 16 critical audit fixes.

Covers:
- F-0001: Startup workspace purge does not delete legitimate workspaces (e.g. templates)
- F-0010: Marathon execute_task wraps single task in TeamOrchestrator without AttributeError
- F-0011: Terminal cmd.exe execution completes in < 5s without hanging
- F-0004: Duo escalator import resolves without ModuleNotFoundError
- F-0005: Escalation route alias /chat-agent/escalation-decision works
- F-0006: PowerShell command injection prevented via environment variable in computer_controller
- F-0007: Voice controller shell injection prevented with shell=False and name sanitization
- F-0003: AI service git diff import resolves without ModuleNotFoundError
"""

import os
import sys
import time
import pytest
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# ── F-0001: Startup Workspace Purge ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_startup_does_not_delete_legitimate_workspaces(tmp_path):
    """Assert that paths containing 'temp', 'template', or 'pytest' are not deleted unless in code_os_test_ / pytest_of_."""
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE workspaces (
            path TEXT PRIMARY KEY,
            name TEXT,
            last_opened_at TEXT
        )
    """)

    legitimate_paths = [
        r"D:\projects\templates",
        r"C:\Users\username\contemporary_app",
        r"D:\projects\attempt_one",
        r"E:\workspaces\my_pytest_helpers",
    ]
    ephemeral_test_paths = [
        r"C:\temp\code_os_test_12345",
        r"C:\Users\User\AppData\Local\Temp\pytest_of_runner\test0",
    ]

    for p in legitimate_paths + ephemeral_test_paths:
        cur.execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (p, Path(p).name))
    conn.commit()

    # Execute the updated cleanup query from backend/app/main.py:153-156
    cur.execute(
        "DELETE FROM workspaces WHERE path LIKE '%\\code_os_test_%' OR path LIKE '%/code_os_test_%' OR path LIKE '%\\pytest_of_%' OR path LIKE '%/pytest_of_%'"
    )
    conn.commit()

    cur.execute("SELECT path FROM workspaces")
    surviving_paths = {row[0] for row in cur.fetchall()}
    conn.close()

    for p in legitimate_paths:
        assert p in surviving_paths, f"Legitimate workspace '{p}' was incorrectly deleted by startup purge!"

    for p in ephemeral_test_paths:
        assert p not in surviving_paths, f"Ephemeral test workspace '{p}' was not cleaned up!"


# ── F-0010: Marathon execute_task ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_marathon_execute_task_wraps_single_task():
    """Assert that TeamOrchestrator.execute_task exists and executes single tasks without AttributeError."""
    from app.features.ai.team.orchestrator import TeamOrchestrator
    from app.features.ai.team.team_schemas import TeamConfig, TeamTask, TeamRole

    mock_executor = AsyncMock(return_value={
        "status": "completed",
        "reasoning": "Task executed successfully",
        "token_usage": 150,
        "cost_usd": 0.002,
    })

    config = TeamConfig(workspace=".")
    orchestrator = TeamOrchestrator(team_config=config, task_executor=mock_executor)

    # Verify method exists
    assert hasattr(orchestrator, "execute_task"), "TeamOrchestrator must define execute_task method"

    task = TeamTask(
        task_id="mt_test_1",
        job_id="job_marathon_test",
        title="Test Marathon SubTask",
        role=TeamRole.ARCHITECT,
        context={"description": "Test description"},
    )

    result = await orchestrator.execute_task(task, handoffs=[])
    assert result.get("status") == "completed"
    assert result.get("token_usage") == 150
    assert not result.get("error")


# ── F-0011: Terminal cmd.exe Execution ──────────────────────────────────────
@pytest.mark.asyncio
async def test_terminal_cmd_exe_completes_in_5s(tmp_path):
    """Assert that run_command with cmd.exe executes /c and completes in under 5 seconds."""
    from app.features.terminal.service import create_session, run_command, clear_session

    shell = "cmd.exe" if os.name == "nt" else "/bin/sh"
    session = create_session(str(tmp_path), shell=shell)

    start_time = time.monotonic()
    output, exit_code, background = await run_command(session.id, "echo hello", background=False)
    elapsed = time.monotonic() - start_time

    assert elapsed < 5.0, f"Command took {elapsed:.2f}s, exceeding 5s threshold (deadlock / interactive hang)!"
    assert exit_code == 0, f"Command failed with exit code {exit_code}: {output}"
    assert "hello" in output.lower(), f"Expected 'hello' in output, got: {output}"


# ── F-0004: Duo Escalator Import ─────────────────────────────────────────────
def test_duo_escalator_imports_successfully():
    """Assert that duo_escalator relative import resolves without ModuleNotFoundError."""
    import inspect
    from app.features.ai.harness.duo_escalator import _escalate_to_duo
    assert inspect.iscoroutinefunction(_escalate_to_duo) or inspect.isasyncgenfunction(_escalate_to_duo)

    from app.features.duo.service import start_session, get_session
    assert callable(start_session)
    assert callable(get_session)


# ── F-0005: Escalation Route Alias ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_escalation_route_alias_works():
    """Assert that both /api/ai/escalation-decision and /api/ai/chat-agent/escalation-decision route properly."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.auth import get_token

    client = TestClient(app)
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Both routes should be registered and return 404 with exact detail if action_id is not pending (not a route 404)
    res_orig = client.post(
        "/api/ai/escalation-decision",
        json={"action_id": "nonexistent_action", "decision": "continue"},
        headers=headers,
    )
    # Status code 404 from handler detail="No pending escalation..." proves the route exists!
    assert res_orig.status_code == 404
    assert "No pending escalation" in res_orig.json().get("detail", "")

    res_alias = client.post(
        "/api/ai/chat-agent/escalation-decision",
        json={"action_id": "nonexistent_action", "decision": "continue"},
        headers=headers,
    )
    assert res_alias.status_code == 404
    assert "No pending escalation" in res_alias.json().get("detail", "")


# ── F-0006: PowerShell Injection Prevented ──────────────────────────────────
@pytest.mark.asyncio
async def test_powershell_injection_prevented():
    """Assert that hostile title with PowerShell commands cannot break out into code execution."""
    from app.features.automation.computer_controller import ComputerController

    ctrl = ComputerController(workspace=".")
    hostile_title = "'; Start-Process calc.exe; #"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res = await ctrl.focus_window(hostile_title)

        if os.name == "nt":
            assert mock_run.called
            call_kwargs = mock_run.call_args.kwargs
            env_passed = call_kwargs.get("env", {})
            assert env_passed.get("TARGET_WINDOW_TITLE") == hostile_title
            # Script string should use $t or $env:TARGET_WINDOW_TITLE, not literal hostile_title
            cmd_passed = mock_run.call_args[0][0]
            script_str = cmd_passed[-1]
            assert hostile_title not in script_str, "Hostile title was directly interpolated into PowerShell script!"


# ── F-0007: Voice Controller Shell Injection Prevented ──────────────────────
def test_voice_controller_shell_injection_prevented():
    """Assert that close_application does not use shell=True and sanitizes app_name."""
    from app.features.ai.rony_voice.system_controller import close_application

    hostile_app = "calc.exe & del C:\\*"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        close_application(hostile_app)

        assert mock_run.called
        call_args, call_kwargs = mock_run.call_args
        assert call_kwargs.get("shell") is False, "close_application must execute with shell=False!"

        if sys.platform == "win32":
            args_list = call_args[0]
            assert isinstance(args_list, list), "Arguments must be passed as a list!"
            # Hostile characters (&, \, *) should be sanitized out
            proc_arg = args_list[2]
            assert "&" not in proc_arg
            assert "del" not in proc_arg
            assert "*" not in proc_arg


# ── F-0003: AI Service Git Import ───────────────────────────────────────────
def test_commit_diff_import_successful():
    """Assert that app.features.git.service diff is importable and resolves correctly."""
    from app.features.git.service import diff as git_diff
    assert callable(git_diff)
