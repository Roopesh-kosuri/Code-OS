from __future__ import annotations

import ast
import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

from .handoff import (
    create_review_notes_handoff,
    create_test_output_handoff,
)
from .roles import ReviewerRole, TesterRole
from .team_schemas import (
    HandoffArtifact,
    HandoffType,
    TeamConfig,
    TeamRole,
    TeamTask,
)

logger = logging.getLogger(__name__)


def parse_test_output(output: str, exit_code: int = 0) -> dict[str, Any]:
    """Parse output from pytest, npm test, or jest to extract test metrics and failed test names."""
    passed = 0
    failed = 0
    errors = 0
    failed_tests: list[str] = []

    # 1. Pytest regexes: e.g. "5 passed", "2 failed, 5 passed", "1 error"
    m_pass = re.search(r"(\d+)\s+passed", output, re.IGNORECASE)
    if m_pass:
        passed = int(m_pass.group(1))

    m_fail = re.search(r"(\d+)\s+failed", output, re.IGNORECASE)
    if m_fail:
        failed = int(m_fail.group(1))

    m_err = re.search(r"(\d+)\s+errors?", output, re.IGNORECASE)
    if m_err:
        errors = int(m_err.group(1))

    # 2. Jest/npm test regexes: e.g. "Tests: 1 failed, 4 passed, 5 total"
    m_jest_fail = re.search(r"Tests:\s+(\d+)\s+failed", output, re.IGNORECASE)
    if m_jest_fail:
        failed = int(m_jest_fail.group(1))
    m_jest_pass = re.search(r"Tests:.*,\s*(\d+)\s+passed", output, re.IGNORECASE)
    if m_jest_pass:
        passed = int(m_jest_pass.group(1))

    # 3. Extract failure lines/names
    for line in output.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("FAILED ") or trimmed.startswith("FAIL "):
            parts = trimmed.split(None, 1)
            if len(parts) > 1:
                failed_tests.append(parts[1])

    # Fallback if exit_code is non-zero or failure keywords exist
    if "collected 0 items" in output or "no tests ran" in output:
        return {
            "success": True,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "failed_tests": [],
            "output": output,
        }

    if (exit_code != 0 or "FAIL" in output or "FAILED" in output) and (failed == 0 and errors == 0):
        failed = 1
        if not failed_tests:
            failed_tests.append("Test suite failed")

    success = (failed == 0 and errors == 0 and exit_code == 0)
    return {
        "success": success,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "failed_tests": failed_tests,
        "output": output,
    }


def audit_code_files(workspace: str, file_paths: list[str]) -> list[str]:
    """Audit modified files for stubs, security issues, and syntax errors."""
    blockers: list[str] = []
    ws_path = Path(workspace).resolve()

    for rel_path in file_paths:
        file_path = ws_path / rel_path if not Path(rel_path).is_absolute() else Path(rel_path)
        if not file_path.exists() or not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            blockers.append(f"{rel_path}: Failed to read file for audit: {exc}")
            continue

        lines = content.splitlines()

        # 1. Check for stubs (TODO, FIXME, NotImplementedError)
        for idx, line in enumerate(lines, start=1):
            if re.search(r"\b(TODO|FIXME)\b", line):
                blockers.append(f"{rel_path}:{idx}: Stub detected in code: {line.strip()[:60]}")
            elif re.search(r"raise\s+NotImplementedError", line):
                blockers.append(f"{rel_path}:{idx}: NotImplementedError stub detected")

        # 2. Check for security issues (hardcoded secrets, SQL injection)
        for idx, line in enumerate(lines, start=1):
            if re.search(r"(?:api[_-]?key|secret[_-]?key|auth[_-]?token|password)\s*=\s*['\"][A-Za-z0-9_\-]{8,}['\"]", line, re.IGNORECASE):
                blockers.append(f"{rel_path}:{idx}: Potential hardcoded credential or secret detected")
            if re.search(r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+.*(?:f['\"].*\{|\.format\(|\s%\s)", line, re.IGNORECASE):
                blockers.append(f"{rel_path}:{idx}: Potential SQL injection via unparameterized query detected")

        # 3. Code quality / Syntax check for Python files
        if file_path.suffix.lower() == ".py":
            try:
                ast.parse(content, filename=str(file_path))
            except SyntaxError as syn_err:
                blockers.append(f"{rel_path}:{syn_err.lineno}: Syntax error: {syn_err.msg}")

    return blockers


class VerificationGate:
    """Autonomous Verification Gate and Self-Healing Repair Loop.

    After DAG execution finishes, VerificationGate runs full test suites (Tester role),
    triggers targeted repair loops to the Coder role on failures, and performs
    automated code audits (Reviewer role) before granting final sign-off.
    """

    def __init__(
        self,
        event_emitter: Optional[Callable[[str, dict[str, Any]], None]] = None,
        task_executor: Optional[
            Callable[[TeamTask, list[HandoffArtifact]], Coroutine[Any, Any, dict[str, Any]]]
        ] = None,
        test_runner: Optional[Callable[[str], Coroutine[Any, Any, dict[str, Any]]]] = None,
        code_auditor: Optional[Callable[[str, list[str]], Coroutine[Any, Any, list[str]]]] = None,
        orchestrator: Optional[Any] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.event_emitter = event_emitter or (orchestrator.emit_event if orchestrator else None)
        self.task_executor = task_executor or (orchestrator.task_executor if orchestrator else None)
        self.test_runner = test_runner
        self.code_auditor = code_auditor
        self.repair_history: list[dict[str, Any]] = []

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self.event_emitter:
            try:
                self.event_emitter(event, data)
            except Exception as exc:
                logger.warning("VerificationGate event emitter error: %s", exc)

    async def verify_job(
        self,
        job_id: str,
        workspace: str,
        team_config: Optional[TeamConfig] = None,
        round_num: int = 1,
        prior_handoffs: Optional[list[HandoffArtifact]] = None,
        modified_files: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Execute verification gate, repair loops, and final sign-off audit."""
        config = team_config or (self.orchestrator.team_config if self.orchestrator else TeamConfig(workspace=workspace))
        max_repair_rounds = max(1, config.max_repair_rounds)
        files = list(modified_files or [])

        # Emit verification in progress status
        self._emit("team_status", {
            "job_id": job_id,
            "status": "verifying",
            "round": round_num,
            "max_rounds": max_repair_rounds,
        })

        # ── Step 1: Tester Role runs full test suite ──────────────────────────
        test_res: dict[str, Any]
        if self.test_runner:
            res = self.test_runner(workspace)
            if asyncio.iscoroutine(res):
                test_res = await res
            else:
                test_res = res
        else:
            # Default Tester execution
            tester = TesterRole()
            test_cmd = "python -m pytest"
            ws_p = Path(workspace)
            if (ws_p / "package.json").exists() and not (ws_p / "pytest.ini").exists() and not (ws_p / "pyproject.toml").exists():
                test_cmd = "npm test"
            tool_res = tester.execute_tool("run_test", {"command": test_cmd}, workspace=workspace)
            test_res = parse_test_output(tool_res.output or tool_res.error, exit_code=0 if tool_res.success else 1)

        tests_passed = test_res.get("passed", 0)
        tests_failed = test_res.get("failed", 0)
        test_success = test_res.get("success", tests_failed == 0)
        failures = test_res.get("failed_tests") or ([f"{tests_failed} test(s) failed"] if not test_success else [])

        # ── Step 2: If tests failed, trigger repair loop ─────────────────────
        if not test_success or tests_failed > 0:
            test_handoff = create_test_output_handoff(
                from_role=TeamRole.TESTER,
                to_role=TeamRole.CODER,
                test_output=test_res.get("output", "Test suite execution failed"),
                passed=False,
                summary=f"Tester found {tests_failed} test failure(s): {', '.join(failures[:2])}",
                task_id=f"verify_{job_id}_r{round_num}_test",
            )
            test_handoff.payload["stack_traces"] = test_res.get("output", "")
            test_handoff.payload["failed_tests"] = failures

            if round_num < max_repair_rounds:
                # Emit repair event
                repair_payload = {
                    "job_id": job_id,
                    "round": round_num,
                    "max_rounds": max_repair_rounds,
                    "failures": failures,
                    "reason": f"Test failures detected in round {round_num}",
                    "test_counts": {"passed": tests_passed, "failed": tests_failed},
                }
                self.repair_history.append(repair_payload)
                self._emit("team_repair", repair_payload)

                # Emit team message warning banner
                self._emit("team_message", {
                    "job_id": job_id,
                    "sender_role": TeamRole.TESTER.value,
                    "recipient_role": TeamRole.CODER.value,
                    "message_type": "repair",
                    "content": f"🔄 Repair Round {round_num}/{max_repair_rounds}: Coder fixing {len(failures)} test failure(s)",
                    "details": repair_payload,
                })

                # Create repair task assigned to Coder role
                repair_task = TeamTask(
                    task_id=f"{job_id}_repair_r{round_num}",
                    job_id=job_id,
                    title=f"Repair Round {round_num}: Fix {len(failures)} Test Failure(s)",
                    role=TeamRole.CODER,
                    dependencies=[],
                    context={"repair_round": round_num, "failures": failures},
                    metadata={"repair_round": round_num, "failures": failures},
                )

                # Persist repair task in database if available
                await self._persist_repair_task(repair_task, round_num, failures)

                # Coder receives test_output handoff and fixes bugs
                if self.task_executor:
                    await self.task_executor(repair_task, [test_handoff])
                elif self.orchestrator and hasattr(self.orchestrator, "_run_task_with_semaphore"):
                    await self.orchestrator._run_task_with_semaphore(repair_task, [test_handoff])

                # Re-run verification recursively
                return await self.verify_job(
                    job_id=job_id,
                    workspace=workspace,
                    team_config=config,
                    round_num=round_num + 1,
                    modified_files=files,
                )
            else:
                # Exceeded max repair rounds
                reason = f"Verification failed: {tests_failed} test failure(s) remain after {round_num} round(s)."
                report = self._build_report(files, tests_passed, tests_failed, 0, round_num)
                return {
                    "verified": False,
                    "rounds_used": round_num,
                    "reason": reason,
                    "failures": failures,
                    "metrics": report,
                    "final_report": report,
                }

        # ── Step 3: Tests passed -> Reviewer Role audits modified files ───────
        blockers: list[str] = []
        if self.code_auditor:
            aud_res = self.code_auditor(workspace, files)
            if asyncio.iscoroutine(aud_res):
                blockers = await aud_res
            else:
                blockers = aud_res
        else:
            blockers = audit_code_files(workspace, files)

        if blockers:
            review_handoff = create_review_notes_handoff(
                from_role=TeamRole.REVIEWER,
                to_role=TeamRole.CODER,
                notes="\n".join(blockers),
                approved=False,
                summary=f"Reviewer found {len(blockers)} blocker(s): {', '.join(blockers[:2])}",
                task_id=f"verify_{job_id}_r{round_num}_review",
            )

            if round_num < max_repair_rounds:
                repair_payload = {
                    "job_id": job_id,
                    "round": round_num,
                    "max_rounds": max_repair_rounds,
                    "failures": blockers,
                    "reason": f"Review blockers detected in round {round_num}",
                }
                self.repair_history.append(repair_payload)
                self._emit("team_repair", repair_payload)

                self._emit("team_message", {
                    "job_id": job_id,
                    "sender_role": TeamRole.REVIEWER.value,
                    "recipient_role": TeamRole.CODER.value,
                    "message_type": "repair",
                    "content": f"🔄 Repair Round {round_num}/{max_repair_rounds}: Coder fixing {len(blockers)} review blocker(s)",
                    "details": repair_payload,
                })

                repair_task = TeamTask(
                    task_id=f"{job_id}_repair_r{round_num}",
                    job_id=job_id,
                    title=f"Repair Round {round_num}: Fix {len(blockers)} Review Blocker(s)",
                    role=TeamRole.CODER,
                    dependencies=[],
                    context={"repair_round": round_num, "blockers": blockers},
                    metadata={"repair_round": round_num, "blockers": blockers},
                )

                await self._persist_repair_task(repair_task, round_num, blockers)

                if self.task_executor:
                    await self.task_executor(repair_task, [review_handoff])
                elif self.orchestrator and hasattr(self.orchestrator, "_run_task_with_semaphore"):
                    await self.orchestrator._run_task_with_semaphore(repair_task, [review_handoff])

                return await self.verify_job(
                    job_id=job_id,
                    workspace=workspace,
                    team_config=config,
                    round_num=round_num + 1,
                    modified_files=files,
                )
            else:
                reason = f"Verification blocked: {len(blockers)} review blocker(s) remain after {round_num} round(s)."
                report = self._build_report(files, tests_passed, 0, len(blockers), round_num)
                return {
                    "verified": False,
                    "rounds_used": round_num,
                    "reason": reason,
                    "blockers": blockers,
                    "metrics": report,
                    "final_report": report,
                }

        # ── Sign-off: All tests green and zero review blockers ────────────────
        report = self._build_report(files, tests_passed, 0, 0, round_num)

        self._emit("team_status", {
            "job_id": job_id,
            "status": "verified",
            "rounds_used": round_num,
            "final_report": report,
            "metrics": report,
        })

        return {
            "verified": True,
            "rounds_used": round_num,
            "reason": "All tests passed and code review clean with zero blockers.",
            "metrics": report,
            "final_report": report,
        }

    def _build_report(
        self,
        files: list[str],
        passed: int,
        failed: int,
        blockers: int,
        rounds: int,
    ) -> dict[str, Any]:
        """Compile structured metrics for the final report card."""
        total_cost = 0.0
        if self.orchestrator and hasattr(self.orchestrator, "agent_metrics"):
            for m in self.orchestrator.agent_metrics.values():
                if isinstance(m, dict):
                    total_cost += float(m.get("total_cost", 0.0))

        return {
            "files_changed": len(files),
            "tests_run": passed + failed,
            "tests_passed": passed,
            "tests_failed": failed,
            "review_notes": blockers,
            "repair_rounds": rounds,
            "total_cost": round(total_cost, 4),
        }

    async def _persist_repair_task(
        self,
        task: TeamTask,
        round_num: int,
        failures: list[str],
    ) -> None:
        """Record the repair task and metadata durably in the database."""
        try:
            import json
            from ..job_service import create_task
            await create_task(
                task_id=task.task_id,
                job_id=task.job_id,
                title=task.title,
                agent_role=task.role.value,
                dependencies=task.dependencies,
            )
            from ....db.database import get_pool
            pool = await get_pool()
            meta_str = json.dumps({"repair_round": round_num, "failures": failures})
            await pool.write_execute(
                "UPDATE agent_tasks SET structured_data = ? WHERE id = ?",
                (meta_str, task.task_id),
            )
        except Exception as exc:
            logger.debug("Repair task db persistence skipped: %s", exc)
