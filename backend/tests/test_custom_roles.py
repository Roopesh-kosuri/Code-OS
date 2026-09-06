from __future__ import annotations

import asyncio
import json
from pathlib import Path
import pytest

from app.db.database import init_db, close_db, get_pool
from app.features.ai.job_service import (
    create_job,
    create_task,
    save_custom_role,
    get_custom_roles,
    delete_custom_role,
    save_job_custom_roles_snapshot,
    get_job_custom_roles_snapshot,
)
from app.features.ai.team.roles import CustomTeamRole, get_role_instance
from app.features.ai.team.team_schemas import (
    TeamConfig,
    TeamRole,
    TeamTask,
    HandoffArtifact,
)
from app.features.ai.team.orchestrator import TeamOrchestrator


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path: Path):
    db_path = tmp_path / "test_team.db"
    await init_db(db_path)
    yield
    await close_db()


# ── Test 1: Custom Role Persists (CRUD) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_custom_role_persists(tmp_path: Path):
    ws = str(tmp_path / "ws1")
    role_data = {
        "workspace": ws,
        "name": "Security Auditor",
        "handle": "auditor",
        "description": "Scans code for CVEs and vulnerabilities",
        "color": "#f43f5e",
        "icon": "shield",
        "allowed_tools": ["read_file", "search_code", "list_directory"],
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-latest",
    }

    saved = await save_custom_role(role_data)
    assert saved["id"] is not None
    assert saved["name"] == "Security Auditor"
    assert saved["handle"] == "auditor"
    assert "read_file" in saved["allowed_tools"]
    assert saved["icon"] == "shield"

    # Query custom roles for ws
    roles = await get_custom_roles(ws)
    assert len(roles) == 1
    assert roles[0]["handle"] == "auditor"

    # Query for different workspace should be empty
    other_roles = await get_custom_roles(str(tmp_path / "ws2"))
    assert len(other_roles) == 0

    # Delete custom role
    deleted = await delete_custom_role(saved["id"], workspace=ws)
    assert deleted is True

    roles_after = await get_custom_roles(ws)
    assert len(roles_after) == 0


# ── Test 2: Custom Role Tool Enforcement ──────────────────────────────────────

def test_custom_role_tool_enforcement(tmp_path: Path):
    ws = str(tmp_path)
    custom_role = CustomTeamRole(
        name="Linter",
        handle="linter",
        description="Lints files only",
        color="#6366f1",
        icon="terminal",
        allowed_tools=["read_file", "list_directory"],
        workspace=ws,
    )

    # 1. Allowed tool passes
    allowed, _ = custom_role.validate_tool_permission("read_file", {"path": "main.py"})
    assert allowed is True

    # 2. Disallowed tool (edit_file) rejected
    allowed, reason = custom_role.validate_tool_permission("edit_file", {"path": "main.py"})
    assert allowed is False
    assert "disallowed for role 'linter'" in reason

    with pytest.raises(PermissionError) as exc_info:
        custom_role.execute_tool(
            "edit_file",
            {"path": "main.py", "updated": "a = 1", "original": ""},
            workspace=ws,
            raise_on_disallowed=True,
        )
    assert "Permission denied" in str(exc_info.value)

    # 3. Allowlisted command execution
    allowed_cmd, _ = custom_role.validate_tool_permission("run_command", {"command": "git status"})
    # Not in allowed_tools so False
    assert allowed_cmd is False

    # Role with run_command permitted
    runner_role = CustomTeamRole(
        name="Tester",
        handle="custom_tester",
        allowed_tools=["run_command"],
        workspace=ws,
    )
    # Safe command allowed
    allowed_git, _ = runner_role.validate_tool_permission("run_command", {"command": "git diff"})
    assert allowed_git is True

    # Dangerous command rejected even with run_command in allowed_tools
    allowed_rm, r_rm = runner_role.validate_tool_permission("run_command", {"command": "rm -rf /"})
    assert allowed_rm is False
    assert "allowlist" in r_rm.lower()


# ── Test 3: Custom Role Cannot Get Computer Tools (Safety Bounds) ─────────────

@pytest.mark.asyncio
async def test_custom_role_cannot_get_computer_tools(tmp_path: Path):
    ws = str(tmp_path)
    dirty_tools = [
        "browser_click",
        "browser_navigate",
        "bash_unrestricted",
        "computer_use",
        "mouse_click",
        "read_file",
        "search_code",
    ]

    saved = await save_custom_role({
        "workspace": ws,
        "name": "Hacker Agent",
        "handle": "hacker",
        "allowed_tools": dirty_tools,
    })

    # Only safe tools survived sanitization
    survived = set(saved["allowed_tools"])
    assert "browser_click" not in survived
    assert "computer_use" not in survived
    assert "bash_unrestricted" not in survived
    assert "read_file" in survived
    assert "search_code" in survived

    role_instance = CustomTeamRole.from_row(saved)
    assert "browser_click" not in role_instance.allowed_tools
    assert "computer_use" not in role_instance.allowed_tools


# ── Test 4: Custom Role Snapshot On Job Start (Refinement R1) ─────────────────

@pytest.mark.asyncio
async def test_custom_role_snapshot_on_job_start(tmp_path: Path):
    from app.core.paths import normalize_path
    ws = str(tmp_path)
    ws_norm = str(normalize_path(ws))
    pool = await get_pool()
    await pool.write_execute("INSERT OR REPLACE INTO workspaces (path, name) VALUES (?, ?)", (ws_norm, "ws"))

    job_id = "job_snap_001"
    await create_job(job_id, ws, "team_mode", user_request="Security Audit")

    role_data = await save_custom_role({
        "workspace": ws,
        "name": "Security Auditor",
        "handle": "auditor",
        "description": "Original description",
        "allowed_tools": ["read_file", "search_code"],
    })

    # Snapshot at job start (Refinement R1)
    roles = await get_custom_roles(ws)
    await save_job_custom_roles_snapshot(job_id, roles)

    # Modify the custom role in the database after job start
    await save_custom_role({
        "id": role_data["id"],
        "workspace": ws,
        "name": "Changed Name",
        "handle": "auditor",
        "description": "Edited after job started",
        "allowed_tools": ["read_file"],
    })

    # Also delete it from the DB
    await delete_custom_role(role_data["id"], workspace=ws)
    assert len(await get_custom_roles(ws)) == 0

    # Job snapshot remains immutable!
    snapshot = await get_job_custom_roles_snapshot(job_id)
    assert len(snapshot) == 1
    assert snapshot[0]["name"] == "Security Auditor"
    assert snapshot[0]["description"] == "Original description"
    assert set(snapshot[0]["allowed_tools"]) == {"read_file", "search_code"}

    # Orchestrator initialized with snapshot uses the snapshot definitions
    cfg = TeamConfig(workspace=ws, custom_roles=snapshot)
    orchestrator = TeamOrchestrator(team_config=cfg)
    assert "auditor" in orchestrator.custom_roles_by_handle
    assert orchestrator.custom_roles_by_handle["auditor"]["name"] == "Security Auditor"


# ── Test 5: Workspace Isolation (Refinement R4) ───────────────────────────────

@pytest.mark.asyncio
async def test_custom_roles_are_workspace_isolated(tmp_path: Path):
    ws1 = str(tmp_path / "workspace_alpha")
    ws2 = str(tmp_path / "workspace_beta")

    # Save role in Workspace 1
    role_ws1 = await save_custom_role({
        "workspace": ws1,
        "name": "Alpha Reviewer",
        "handle": "alpha_rev",
        "allowed_tools": ["read_file"],
    })

    # Unique constraint prevents duplicate (workspace, handle)
    # But allows same handle across different workspaces
    role_ws2 = await save_custom_role({
        "workspace": ws2,
        "name": "Beta Reviewer",
        "handle": "alpha_rev",  # same handle, different workspace
        "allowed_tools": ["read_file", "search_code"],
    })
    assert role_ws1["id"] != role_ws2["id"]

    # Assigning role from workspace 1 to a workspace 2 job MUST be rejected
    ws2_roles = await get_custom_roles(ws2)
    # ws2 only has Beta Reviewer
    assert len(ws2_roles) == 1
    assert ws2_roles[0]["name"] == "Beta Reviewer"

    # Orchestrator on workspace 2
    cfg2 = TeamConfig(workspace=ws2, custom_roles=ws2_roles)
    orch2 = TeamOrchestrator(team_config=cfg2)

    # Task using unknown role in ws2 raises Workspace isolation violation
    foreign_task = TeamTask(
        task_id="t_foreign",
        job_id="j_ws2",
        title="Unauthorized foreign role task",
        role="non_existent_role",
    )
    with pytest.raises(ValueError) as exc_info:
        await orch2.execute_dag([foreign_task], job_id="j_ws2")
    assert "Workspace isolation violation" in str(exc_info.value)


# ── Test 6: Approval Tagging Shows Custom Role Name (Refinement R3) ────────────

@pytest.mark.asyncio
async def test_custom_role_approval_shows_role_name(tmp_path: Path):
    ws = str(tmp_path)
    snapshot = [{
        "workspace": ws,
        "name": "CodeReviewer",
        "handle": "reviewer_custom",
        "allowed_tools": ["read_file", "run_command"],
    }]
    cfg = TeamConfig(workspace=ws, custom_roles=snapshot)
    orch = TeamOrchestrator(team_config=cfg)

    emitted_events: list[dict] = []
    orch.subscribe(lambda evt: emitted_events.append({"event": evt.event, "data": evt.data}))

    # Request approval for custom role
    pending = await orch.request_task_approval(
        task_id="t_appr_1",
        role="reviewer_custom",
        action_type="run_command",
        detail="npm audit",
        reason="Check for vulnerabilities",
        command="npm audit",
    )

    # Verify approval object has custom role's display name
    assert pending.agent_role == "CodeReviewer"
    assert pending.metadata["agent_role"] == "CodeReviewer"
    assert pending.metadata["handle"] == "reviewer_custom"

    # Verify emitted team_approval event has custom role display name
    appr_events = [e for e in emitted_events if e["event"] == "team_approval"]
    assert len(appr_events) == 1
    assert appr_events[0]["data"]["agent_role"] == "CodeReviewer"
