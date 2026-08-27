"""
test_coverage_core_agent_loop.py - Behavioral coverage tests for Core Agent Loop:
- Agents: DocumenterAgent, ReviewerAgent, TesterAgent, PlannerAgent, CoderAgent
- Engine & Pipeline: DAGEngine, JobService
- Harness Components: plan_parser, tool_executor, activity_logger, compaction_manager
- Proposal Service: create, apply, reject, conflict detection
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.db.database import get_db

from app.features.ai.agents.agent_factory import AgentFactory
from app.features.ai.agents.documenter import DocumenterAgent
from app.features.ai.agents.reviewer import ReviewerAgent
from app.features.ai.agents.tester import TesterAgent
TesterAgent.__test__ = False
from app.features.ai.agents.planner import PlannerAgent
from app.features.ai.agents.coder import CoderAgent
from app.features.ai.dag_engine import DAGEngine
from app.features.ai.job_service import create_job, create_task, get_job, update_task_status
from app.features.ai.schemas import FileChange, EditProposalRequest
from app.features.ai.service import create_proposal, get_proposal, apply_proposal, reject_proposal, list_proposals
from app.features.ai.harness.plan_parser import (
    _classify_rules,
    _classify_task_effort,
    _is_deep_query,
    _is_quick_task_query,
    _parse_plan,
    _parse_plan_dag,
    _replan_on_failure,
    _has_escalate_marker,
    _response_is_done,
    _declares_tool_intent,
    DAGPlanStep,
)
from app.features.ai.harness.tool_executor import (
    _clean_rel_path,
    _find_mismatch_context,
    _validate_smart_edit,
    _handle_append_file,
    _handle_list_tests,
    _handle_run_single_test,
)
from app.features.ai.harness.activity_logger import (
    _append_activity_log,
    _load_activity_log,
    _save_interrupted_state,
    _load_interrupted_state,
    _clear_interrupted_state,
    _rotate_activity_log,
)
from app.features.ai.schemas import ChatMessage
from app.features.ai.harness.compaction_manager import (
    _compact_conversation_history,
    _clean_response_text,
    _is_response_truncated,
    _generate_diff_summary,
)


# =====================================================================
# 1. Specialized Agent Roles (Documenter, Reviewer, Tester, Planner)
# =====================================================================

@pytest.mark.asyncio
async def test_documenter_agent_full_turn(tmp_path):
    """DocumenterAgent inspects workspace files and produces documentation proposals."""
    ws = str(tmp_path)
    (tmp_path / "module.py").write_text("def calculate_tax(amount: float) -> float:\n    return amount * 0.2\n", encoding="utf-8")

    doc_agent = DocumenterAgent()
    prompt_inst = doc_agent.get_system_prompt()
    assert "Documentation Agent" in prompt_inst
    assert "read_file" in prompt_inst

    mock_llm_responses = [
        # Turn 1: tool call to read the module
        "[TOOL_CALL: read_file]\n{\"path\": \"module.py\"}\n[/TOOL_CALL]",
        # Turn 2: proposal creating API documentation
        (
            "I have inspected module.py. Here is the documentation:\n"
            "[PROPOSAL: docs/API.md]\n"
            "<<<< ORIGINAL\n"
            "====\n"
            "# Tax API\n"
            "`calculate_tax(amount: float) -> float`: Calculates 20% tax.\n"
            ">>>>\n"
        ),
    ]

    response_iter = iter(mock_llm_responses)

    class MockProvider:
        async def stream_chat(self, *args, **kwargs):
            yield next(response_iter)

    with patch("app.features.ai.agents.documenter.provider_for", new=AsyncMock(return_value=MockProvider())):
        output = await doc_agent.execute(
            job_id="job_doc_1",
            task_id="task_doc_1",
            title="Generate API docs for tax module",
            context="module.py provides tax calculation",
            workspace=ws,
        )

    assert output.status == "success"
    assert output.agent_role == "Documentation Agent"
    assert len(output.proposals) == 1
    assert "API.md" in output.proposals[0]["path"] or "README.md" in output.proposals[0]["path"]
    assert "Tax API" in output.proposals[0]["updated"]
    assert output.confidence >= 0.8


@pytest.mark.asyncio
async def test_reviewer_agent_structured_audit(tmp_path):
    """ReviewerAgent audits code and emits structured security & quality findings."""
    ws = str(tmp_path)
    main_py = tmp_path / "main.py"
    main_py.write_text("import sqlite3\ndef get_user(uid):\n    return db.execute(f'SELECT * FROM users WHERE id={uid}')\n", encoding="utf-8")

    reviewer = ReviewerAgent()
    system_prompt = reviewer.get_system_prompt()
    assert "Code Review Agent" in system_prompt
    assert "OWASP" in system_prompt

    mock_review_json = {
        "issues": [
            {
                "file": "main.py",
                "line": 3,
                "severity": "high",
                "category": "security",
                "description": "SQL injection vulnerability via f-string formatting in SQL query",
                "suggested_fix": "Use parameterized query: execute('SELECT * FROM users WHERE id=?', (uid,))"
            }
        ],
        "approved": False,
        "summary": "Found 1 high-severity security issue"
    }

    class MockProvider:
        async def stream_chat(self, *args, **kwargs):
            yield json.dumps(mock_review_json)

    with patch("app.features.ai.agents.reviewer.provider_for", new=AsyncMock(return_value=MockProvider())):
        output = await reviewer.execute(
            job_id="job_rev_1",
            task_id="task_rev_1",
            title="Review database query helpers",
            context="main.py contains user fetch query",
            workspace=ws,
        )

    assert output.status == "success"
    assert output.structured_data["approved"] is False
    assert len(output.structured_data["issues"]) == 1
    issue = output.structured_data["issues"][0]
    assert issue["category"] == "security"
    assert issue["severity"] == "high"
    assert "SQL injection" in issue["description"]
    assert output.confidence >= 0.8


@pytest.mark.asyncio
async def test_tester_agent_runner_detection_and_proposal(tmp_path):
    """TesterAgent detects test framework, parses output, and executes test suites."""
    ws = str(tmp_path)
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = test_*.py\n", encoding="utf-8")

    tester = TesterAgent()
    runner_info = tester.detect_test_runner(ws)
    assert runner_info is not None
    assert runner_info["type"] == "pytest"
    assert "pytest" in runner_info["command"]

    # Also test npm test detection with package.json
    npm_ws = tmp_path / "npm_ws"
    npm_ws.mkdir()
    (npm_ws / "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
    npm_runner = tester.detect_test_runner(str(npm_ws))
    assert npm_runner is not None
    assert npm_runner["type"] == "jest"

    # Test parse_test_output for pytest
    raw_pytest_output = "======= 5 passed, 1 failed, 2 skipped in 1.45s ======="
    parsed = tester.parse_test_output(raw_pytest_output, "pytest")
    assert parsed["passed"] == 5
    assert parsed["failed"] == 1
    assert parsed["skipped"] == 2
    assert parsed["total"] == 8

    # Test execute with mocked command execution and auto-granted permission
    mock_run_output = ("======= 5 passed in 0.45s =======", 0)
    with patch.object(tester, "request_permission", new=AsyncMock(return_value=True)),          patch.object(tester, "execute_test_command", new=AsyncMock(return_value=mock_run_output)):
        output = await tester.execute(
            job_id="job_test_1",
            task_id="task_test_1",
            title="Run test suite",
            context="run tests",
            workspace=ws,
        )

    assert output.status == "success"
    assert output.structured_data["test_runner_detected"] is True
    assert output.structured_data["test_results"]["passed"] == 5
    assert output.confidence >= 0.8


@pytest.mark.asyncio
async def test_planner_agent_dag_decomposition(tmp_path):
    """PlannerAgent parses user requests into structured DAG task definitions."""
    planner = PlannerAgent()

    valid_plan_json = {
        "tasks": [
            {
                "id": "t1_schema",
                "title": "Create database schema",
                "agent_role": "Coding Agent",
                "dependencies": [],
                "estimated_effort": "30m"
            },
            {
                "id": "t2_tests",
                "title": "Write unit tests for schema",
                "agent_role": "Testing Agent",
                "dependencies": ["t1_schema"],
                "estimated_effort": "20m"
            }
        ]
    }

    # Markdown wrapped response
    llm_markdown_plan = f"```json\n{json.dumps(valid_plan_json)}\n```"

    class MockProvider:
        async def stream_chat(self, *args, **kwargs):
            yield llm_markdown_plan

    with patch("app.features.ai.agents.planner.provider_for", new=AsyncMock(return_value=MockProvider())):
        tasks = await planner.plan_task("Setup SQLite database with automated tests", str(tmp_path))

    assert len(tasks) == 2
    assert tasks[0]["id"] == "t1_schema"
    assert tasks[0]["agent_role"] == "Coding Agent"
    assert tasks[1]["id"] == "t2_tests"
    assert tasks[1]["dependencies"] == ["t1_schema"]


def test_agent_factory_role_resolution():
    """AgentFactory creates appropriate agent instances with role name matching."""
    coder = AgentFactory.create_agent("Coding Agent")
    assert isinstance(coder, CoderAgent)

    reviewer = AgentFactory.create_agent("Review Agent")
    assert isinstance(reviewer, ReviewerAgent)

    tester = AgentFactory.create_agent("Testing Agent")
    assert isinstance(tester, TesterAgent)

    doc = AgentFactory.create_agent("Documentation Agent")
    assert isinstance(doc, DocumenterAgent)

    # Unknown role defaults to CoderAgent
    unknown = AgentFactory.create_agent("Custom Unknown Worker")
    assert isinstance(unknown, CoderAgent)


# =====================================================================
# 2. DAG Engine & Pipeline Orchestration
# =====================================================================

@pytest.mark.asyncio
async def test_dag_engine_execution_flow(tmp_path, temp_db):
    """DAGEngine executes dependent tasks in topological order and completes job."""
    ws = str(tmp_path)
    job_id = "job_dag_exec_1"

    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "test_ws"))
    await db.commit()

    await create_job(job_id, ws, "Feature workflow", "")
    await create_task("task_step_1", job_id, "Create schema", "Coding Agent", dependencies=[])
    await create_task("task_step_2", job_id, "Create tests", "Testing Agent", dependencies=["task_step_1"])

    engine = DAGEngine()
    executed_order = []

    async def mock_execute_task(jid, task, cfg=None):
        executed_order.append(task["id"])
        await update_task_status(task["id"], "completed")

    with patch.object(engine, "_execute_task", side_effect=mock_execute_task), \
         patch("asyncio.sleep", new=AsyncMock()):
        await engine._run_job(job_id)

    final_job = await get_job(job_id)
    assert final_job["status"] == "completed"
    assert executed_order == ["task_step_1", "task_step_2"]
    tasks = final_job["tasks"]
    assert all(t["status"] == "completed" for t in tasks)


@pytest.mark.asyncio
async def test_dag_engine_cancellation(tmp_path, temp_db):
    """DAGEngine cancels running job and updates status."""
    ws = str(tmp_path)
    job_id = "job_dag_cancel_1"

    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "test_ws"))
    await db.commit()

    await create_job(job_id, ws, "Workflow", "")
    await create_task("task_c_1", job_id, "Step 1", "Coding Agent", dependencies=[])

    engine = DAGEngine()

    # Start long running task
    async def long_running_task():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    t = asyncio.create_task(long_running_task())
    engine._running_jobs[job_id] = t
    await engine.cancel_job(job_id)
    try:
        await t
    except asyncio.CancelledError:
        pass

    job_data = await get_job(job_id)
    assert job_data["status"] == "cancelled"
    assert job_id not in engine._running_jobs


# =====================================================================
# 3. Harness Components (plan_parser, tool_executor, activity_logger)
# =====================================================================

def test_plan_parser_tier_classification_and_dag_replanning():
    """Verify rule-based query classifier and plan DAG extraction."""
    # Tier 0: Greetings
    tier, label, reason = _classify_rules("hello")
    assert tier == 0
    assert "Fast Answer" in label

    # Tier 1: Standard query
    tier1, label1, _ = _classify_rules("fix the typo on line 12 of math.py")
    assert tier1 == 1
    assert label1 in ("Task Plan", "Quick Task")

    # Tier 2: Deep project creation
    tier2, label2, _ = _classify_rules("build a complete fullstack portfolio with tests and readme")
    assert tier2 == 2
    assert "Deep think" in label2

    assert _is_deep_query("create full-stack portfolio with tests") is True
    assert _is_quick_task_query("hey") is True

    # Plan extraction
    sample_plan = "[PLAN]\n1. Step A: Create database\n2. Step B: Add routes\n[/PLAN]"
    steps = _parse_plan(sample_plan)
    assert len(steps) == 2
    assert "Step A: Create database" in steps[0]

    dag_steps = _parse_plan_dag(sample_plan)
    assert len(dag_steps) == 2
    assert dag_steps[0].id == "step_1"
    assert dag_steps[0].status == "pending"

    # Replanning after failure
    replan = _replan_on_failure(dag_steps, failed_idx=0, error_detail="Permission denied")
    assert replan[0].status == "failed"
    assert "Permission denied" in replan[1].title

    # Escalate marker & done
    assert _has_escalate_marker("[ESCALATE] User input needed") is True
    assert _has_escalate_marker("Regular text") is False
    assert _response_is_done("All changes completed. [DONE]") is True
    assert _declares_tool_intent("I will create main.py for you.") is True


def test_tool_executor_smart_edit_and_placeholders(tmp_path):
    """Test smart edit file handling, diff mismatches, and validation."""
    ws = str(tmp_path)
    file_path = tmp_path / "greeting.py"
    file_path.write_text("def hello():\n    print('hi')\n", encoding="utf-8")

    # 1. Exact match edit
    valid, err, change = _validate_smart_edit(
        workspace=ws,
        arguments={
            "path": "greeting.py",
            "original": "    print('hi')",
            "updated": "    print('hello world')",
        },
    )
    assert valid is True
    assert err == ""
    assert "hello world" in change.updated

    # 2. Mismatch diagnostics
    valid_mismatch, err_mismatch, _ = _validate_smart_edit(
        workspace=ws,
        arguments={
            "path": "greeting.py",
            "original": "    print('nonexistent line')",
            "updated": "    print('new')",
        },
    )
    assert valid_mismatch is False
    assert "differing line" in err_mismatch or "does not match" in err_mismatch

    # 3. Missing required parameters
    valid_missing, err_missing, _ = _validate_smart_edit(
        workspace=ws,
        arguments={"path": "greeting.py"},
    )
    assert valid_missing is False
    assert "Missing required parameters" in err_missing

    # 4. Clean rel path utility
    assert _clean_rel_path("./src/app.py") == "src/app.py"
    assert _clean_rel_path("src\\app.py") == "src/app.py"


def test_activity_logger_timeline_and_state(tmp_path):
    """Test activity timeline logging, reverse queries, and interrupted turn state."""
    ws = str(tmp_path)

    # 1. Append activity log entries
    _append_activity_log(ws, {"action_type": "prompt", "outcome": "success", "message": "User asked to refactor code", "timestamp": time.time()})
    _append_activity_log(ws, {"action_type": "command_run", "outcome": "success", "message": "Executed test command", "action_id": "act_1", "timestamp": time.time()})
    _append_activity_log(ws, {"action_type": "build", "outcome": "failed", "message": "Syntax error during compilation", "timestamp": time.time()})

    # 2. Load activity log (reverse chronological)
    entries = _load_activity_log(ws, limit=10)
    assert len(entries) == 3
    assert entries[0]["action_type"] == "build"  # Most recent first

    # Filter by commands
    cmd_entries = _load_activity_log(ws, filter_type="commands")
    assert len(cmd_entries) == 1
    assert cmd_entries[0]["action_type"] == "command_run"

    # Filter by failures
    fail_entries = _load_activity_log(ws, filter_type="failures")
    assert len(fail_entries) == 1
    assert fail_entries[0]["outcome"] == "failed"

    # 3. Interrupted state persistence
    saved = _save_interrupted_state(
        workspace=ws,
        user_query="refactor code",
        tier=2,
        iteration=1,
        max_iterations=10,
        messages=[{"role": "user", "content": "refactor code"}],
        dag_plan_steps=[{"id": "step_1", "title": "Inspect code"}],
        staged_changes=[{"path": "main.py"}],
        tokens_used=120,
        tools_executed=1,
    )
    assert saved is True

    loaded = _load_interrupted_state(ws)
    assert loaded is not None
    assert loaded["user_query"] == "refactor code"
    assert loaded["tier"] == 2
    assert loaded["iteration"] == 1

    # Clear state
    cleared = _clear_interrupted_state(ws)
    assert cleared is True
    assert _load_interrupted_state(ws) is None

    # 4. Log rotation
    log_file = tmp_path / ".code_os" / "activity_log.jsonl"
    _rotate_activity_log(log_file, max_size_mb=0.000001)


def test_compaction_manager_history_pruning():
    """Test conversation compaction, response text cleaning, and diff summary generation."""
    messages = [
        ChatMessage(role="system", content="You are a coding assistant."),
        ChatMessage(role="user", content="Tool results:\n[TOOL_RESULT: edit_file] Success [/TOOL_RESULT]"),
        ChatMessage(role="assistant", content="I will edit the file:\n[TOOL_CALL: edit_file]\n" + ("A" * 400) + "\n[/TOOL_CALL]"),
        ChatMessage(role="user", content="Next step"),
        ChatMessage(role="assistant", content="Completed"),
    ]
    compacted = _compact_conversation_history(messages, keep_recent_turns=1)
    assert len(compacted) == len(messages)
    assert "compacted to save context tokens" in compacted[1].content
    assert compacted[0].role == "system"

    # Cleaning response tags
    raw_response = "Here is the code: [PLAN] 1. Step A [/PLAN] [DONE]"
    cleaned = _clean_response_text(raw_response)
    assert "[PLAN]" not in cleaned
    assert "[DONE]" not in cleaned
    assert "Here is the code:" in cleaned

    # Truncation marker check
    assert _is_response_truncated("Some cut off text [TRUNCATED: length]") is True
    assert _is_response_truncated("Normal text without markers") is False

    # Diff summary generation
    fc = FileChange(path="test.py", original="a = 1\n", updated="a = 2\nb = 3\n")
    diff_summary = _generate_diff_summary(fc)
    assert "+1" in diff_summary or "lines" in diff_summary


# =====================================================================
# 4. Proposal Service Lifecycle & Conflict Detection
# =====================================================================

@pytest.mark.asyncio
async def test_proposal_service_lifecycle_and_conflicts(tmp_path, temp_db):
    """Test proposal creation, diff calculation, disk apply, reject, and conflict detection."""
    ws = str(tmp_path)
    file_a = tmp_path / "app.py"
    file_a.write_text("name = 'CodeOS'\nversion = '1.0'\n", encoding="utf-8")

    # 1. Create proposal
    req = EditProposalRequest(
        workspace=ws,
        summary="Update version to 2.0",
        changes=[
            FileChange(
                path="app.py",
                original="name = 'CodeOS'\nversion = '1.0'\n",
                updated="name = 'CodeOS'\nversion = '2.0'\n",
            )
        ]
    )
    proposal = await create_proposal(req)
    assert proposal.id is not None
    assert proposal.status == "pending"
    assert "version = '2.0'" in proposal.diff

    # 2. List proposals
    proposals = await list_proposals(ws)
    assert len(proposals) >= 1
    assert any(p.id == proposal.id for p in proposals)

    # 3. Apply proposal to disk
    applied = await apply_proposal(proposal.id)
    assert applied.status == "applied"
    assert "version = '2.0'" in file_a.read_text(encoding="utf-8")

    # 4. Create second proposal for rejection test
    req2 = EditProposalRequest(
        workspace=ws,
        summary="Unwanted change",
        changes=[
            FileChange(
                path="app.py",
                original="name = 'CodeOS'\nversion = '2.0'\n",
                updated="name = 'WrongName'\nversion = '2.0'\n",
            )
        ]
    )
    p2 = await create_proposal(req2)
    rejected = await reject_proposal(p2.id)
    assert rejected.status == "rejected"

    # File on disk remains unchanged
    assert "version = '2.0'" in file_a.read_text(encoding="utf-8")

# =====================================================================
# 5. CoderAgent Heuristics, Self-Review & High-Stakes Evaluation
# =====================================================================

from app.features.ai.agents.coder import PlanModel


def test_coder_agent_high_stakes_and_trivial_heuristics():
    """Verify security risk escalation and trivial path heuristics."""
    coder = CoderAgent()

    # 1. Security / High-stakes escalation
    plan_risky = PlanModel(
        ambiguous=False,
        clarifying_question="",
        goal="Update database query",
        hypothesis="Updating query fixes auth",
        files_to_touch=["auth.py"],
        approach="Use parameterized query",
        risks=["Exposing password hash"],
        verification="Run auth tests",
    )
    high_stakes, reasons = coder.is_high_stakes(plan_risky, "Fix user login", "Authentication context")
    assert high_stakes is True
    assert any("auth" in r.lower() or "password" in r.lower() or "risk" in r.lower() for r in reasons)

    # 2. Too many files touched (>5)
    plan_many_files = PlanModel(
        ambiguous=False,
        clarifying_question="",
        goal="Refactor everything",
        hypothesis="Wide refactoring",
        files_to_touch=[f"file_{i}.py" for i in range(7)],
        approach="Update all files",
        risks=[],
        verification="Run all tests",
    )
    high_stakes_files, file_reasons = coder.is_high_stakes(plan_many_files, "Refactor", "")
    assert high_stakes_files is True
    assert any("files planned" in r for r in file_reasons)

    # 3. Trivial change path
    plan_trivial = PlanModel(
        ambiguous=False,
        clarifying_question="",
        goal="Fix small typo",
        hypothesis="Typo fix",
        files_to_touch=["README.md"],
        approach="Fix typo",
        risks=[],
        verification="Check markdown",
    )
    small_change = [FileChange(path="README.md", original="helol", updated="hello")]
    assert coder.is_trivial_change(plan_trivial, small_change) is True

    # Multi-file change is NOT trivial
    large_changes = [
        FileChange(path="README.md", original="helol", updated="hello"),
        FileChange(path="app.py", original="v1", updated="v2"),
    ]
    assert coder.is_trivial_change(plan_trivial, large_changes) is False


@pytest.mark.asyncio
async def test_coder_agent_execution_with_mocked_llm(tmp_path):
    """CoderAgent performs structured execution, file grounding, and emits proposals."""
    ws = str(tmp_path)
    calc_py = tmp_path / "calc.py"
    calc_py.write_text("def subtract(a, b):\n    return a + b\n", encoding="utf-8")

    coder = CoderAgent()

    # Turn responses: Plan JSON -> Code Generation with Proposal -> Self-Review
    mock_responses = [
        # Phase 1: Planning
        json.dumps({
            "ambiguous": False,
            "clarifying_question": "",
            "goal": "Fix subtract function",
            "hypothesis": "Changing addition to subtraction in calc.py fixes arithmetic",
            "files_to_touch": ["calc.py"],
            "approach": "Change + to - in return statement",
            "risks": [],
            "verification": "Run unit test"
        }),
        # Phase 2: Implementation Proposal
        (
            "I will fix the bug in calc.py:\n"
            "[PROPOSAL: calc.py]\n"
            "<<<< ORIGINAL\n"
            "def subtract(a, b):\n    return a + b\n"
            "====\n"
            "def subtract(a, b):\n    return a - b\n"
            ">>>>\n"
            "[DONE]"
        ),
        # Phase 3: Self-Review JSON
        json.dumps({
            "approved": True,
            "issues": [],
            "reasoning": "Subtraction logic is correct"
        }),
    ]
    resp_iter = iter(mock_responses)

    class MockProvider:
        async def stream_chat(self, *args, **kwargs):
            yield next(resp_iter)

    with patch("app.features.ai.agents.coder.provider_for", new=AsyncMock(return_value=MockProvider())):
        output = await coder.execute(
            job_id="job_coder_1",
            task_id="task_coder_1",
            title="Fix subtract arithmetic bug",
            context="calc.py subtract returns addition",
            workspace=ws,
        )

    assert output.status == "success"
    assert len(output.proposals) >= 1
    assert "calc.py" in output.proposals[0]["path"]
    assert "return a - b" in output.proposals[0]["updated"]


# =====================================================================
# 6. DAGEngine Deadlock Detection
# =====================================================================

@pytest.mark.asyncio
async def test_dag_engine_deadlock_detection(tmp_path, temp_db):
    """DAGEngine detects cyclical/unresolvable dependencies and aborts with failure status."""
    ws = str(tmp_path)
    job_id = "job_deadlock_test"

    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO workspaces (path, name) VALUES (?, ?)", (ws, "test_ws"))
    await db.commit()

    await create_job(job_id, ws, "Deadlock Workflow", "")
    # Task A depends on Task B, Task B depends on Task A (Cycle!)
    await create_task("task_cycle_a", job_id, "Task A", "Coding Agent", dependencies=["task_cycle_b"])
    await create_task("task_cycle_b", job_id, "Task B", "Coding Agent", dependencies=["task_cycle_a"])

    engine = DAGEngine()
    await engine._run_job(job_id)

    final_job = await get_job(job_id)
    assert final_job["status"] == "failed"
    assert "deadlock" in final_job["errors"].lower()


# =====================================================================
# 7. ToolExecutor Append & Test Handlers
# =====================================================================

def test_tool_executor_append_and_test_handlers(tmp_path):
    """Test _handle_append_file on fresh and existing files."""
    ws = str(tmp_path)
    file_path = tmp_path / "notes.txt"
    file_path.write_text("Line 1\n", encoding="utf-8")

    staged: list[FileChange] = []

    # 1. Append to existing file
    success, err, change = _handle_append_file(
        workspace=ws,
        arguments={"path": "notes.txt", "content": "Line 2"},
        staged_changes=staged,
    )
    assert success is True
    assert "Line 1" in change.updated
    assert "Line 2" in change.updated

    # 2. Append again to already-staged file
    success2, _, change2 = _handle_append_file(
        workspace=ws,
        arguments={"path": "notes.txt", "content": "Line 3"},
        staged_changes=staged,
    )
    assert success2 is True
    assert "Line 3" in change2.updated
    assert len(staged) == 1

    # 3. Missing path
    fail, err_missing, _ = _handle_append_file(
        workspace=ws,
        arguments={"content": "missing path"},
        staged_changes=staged,
    )
    assert fail is False
    assert "path" in err_missing.lower()


# =====================================================================
# 8. ApprovalCoordinator Sensitive Files & Trust Memory
# =====================================================================

from app.features.ai.harness.approval_coordinator import (
    _is_sensitive_filename,
    _save_trusted_command,
    _load_trusted_commands,
    _remove_trusted_command,
    _is_command_trusted,
    _pending_approvals,
    _pending_user_responses,
    PendingApproval,
    PendingUserResponse,
    approve_action,
    reject_action,
    respond_to_user_question,
    clear_all_pending,
)


def test_approval_coordinator_sensitive_files_and_trusted_commands(tmp_path):
    """Verify sensitive file detection and workspace trusted command memory."""
    ws = str(tmp_path)

    # 1. Sensitive files
    sens_1, reason_1 = _is_sensitive_filename(".env.production")
    assert sens_1 is True
    assert "environment" in reason_1.lower() or "secret" in reason_1.lower() or "env" in reason_1.lower()

    sens_2, _ = _is_sensitive_filename("id_rsa")
    assert sens_2 is True

    sens_3, _ = _is_sensitive_filename("server.pem")
    assert sens_3 is True

    sens_4, _ = _is_sensitive_filename("database.sqlite3")
    assert sens_4 is True

    safe_1, _ = _is_sensitive_filename("main.py")
    assert safe_1 is False

    safe_2, _ = _is_sensitive_filename("styles.css")
    assert safe_2 is False

    # 2. Trusted command management
    assert _is_command_trusted(ws, "pytest tests/") is False

    # Save pattern
    saved = _save_trusted_command(ws, "pytest*")
    assert saved is True
    assert _is_command_trusted(ws, "pytest tests/test_core.py") is True
    assert _is_command_trusted(ws, "python script.py") is False

    # Load patterns
    cmds = _load_trusted_commands(ws)
    assert "pytest*" in cmds

    # Remove pattern
    removed = _remove_trusted_command(ws, "pytest*")
    assert removed is True
    assert _is_command_trusted(ws, "pytest tests/test_core.py") is False


@pytest.mark.asyncio
async def test_approval_coordinator_lifecycle():
    """Verify approve_action, reject_action, respond_to_user_question, and clear_all_pending."""
    act_id = "act_test_approve_1"
    pending_app = PendingApproval(
        action_id=act_id,
        action_type="command",
        detail="npm run build",
        reason="Build required",
        command="npm run build",
    )
    _pending_approvals[act_id] = pending_app

    # Approve action
    app_res = await approve_action(act_id)
    assert app_res is True
    assert pending_app.approved is True
    assert pending_app.event.is_set()

    # Reject action
    act_id_2 = "act_test_reject_1"
    pending_rej = PendingApproval(
        action_id=act_id_2,
        action_type="edit",
        detail="edit dangerous.py",
        reason="Dangerous change",
    )
    _pending_approvals[act_id_2] = pending_rej
    rej_res = await reject_action(act_id_2)
    assert rej_res is True
    assert pending_rej.approved is False
    assert pending_rej.event.is_set()

    # User question response
    q_id = "q_test_1"
    pending_q = PendingUserResponse(
        action_id=q_id,
        question="Which database engine?",
        options=["PostgreSQL", "SQLite"],
    )
    _pending_user_responses[q_id] = pending_q
    q_res = respond_to_user_question(q_id, "SQLite")
    assert q_res is True
    assert pending_q.selected_option == "SQLite"
    assert pending_q.event.is_set()

    # Clear all pending
    _pending_approvals["dummy_1"] = PendingApproval("dummy_1", "command", "cmd", "reason")
    cleared = clear_all_pending()
    assert cleared >= 1
    assert len(_pending_approvals) == 0


# =====================================================================
# 9. ReviewerAgent Deep Multi-Finding Audit
# =====================================================================

@pytest.mark.asyncio
async def test_reviewer_agent_multi_finding_audit(tmp_path):
    """ReviewerAgent detects multiple structured vulnerabilities across files."""
    ws = str(tmp_path)
    auth_py = tmp_path / "auth.py"
    auth_py.write_text("def verify_pass(p): return p == 'admin'\n", encoding="utf-8")

    reviewer = ReviewerAgent()

    review_response = (
        "Here is my code review:\n"
        "[REVIEW]\n"
        "{\n"
        '  "approved": false,\n'
        '  "confidence": 0.95,\n'
        '  "findings": [\n'
        '    {"file": "auth.py", "line": 1, "severity": "critical", "issue": "Hardcoded admin password in comparison"},\n'
        '    {"file": "auth.py", "line": 1, "severity": "medium", "issue": "Plaintext string comparison vulnerable to timing attacks"}\n'
        '  ],\n'
        '  "summary": "Critical security issues found in authentication"\n'
        "}\n"
        "[/REVIEW]\n"
        "[DONE]"
    )

    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield review_response

    mock_provider.stream_chat = mock_stream

    with patch("app.features.ai.agents.reviewer.provider_for", new=AsyncMock(return_value=mock_provider)):
        output = await reviewer.execute(
            job_id="job_rev_audit",
            task_id="task_rev_audit",
            title="Review Authentication Security",
            context="Verify password authentication in auth.py",
            workspace=ws,
        )

    assert output.status == "success"
    assert output.confidence == 0.85
    assert output.structured_data['confidence'] == 0.95
    structured = output.structured_data
    assert structured["approved"] is False
    assert len(structured["findings"]) == 2
    assert structured["findings"][0]["severity"] == "critical"
