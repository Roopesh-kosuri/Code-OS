"""Auto-scorer for CODE OS Benchmark Gym tasks.

Evaluates:
1. Test suite pass rate (Phase 14 matrix hook / pytest output) -> 40 pts
2. Tool selection suitability (surgical tool discipline: edit_range for <60 lines) -> 20 pts
3. Regression prevention (did not break existing baseline tests) -> 20 pts
4. Budget compliance (iterations & token limits respected) -> 20 pts

Total score: 0-100 per task.
"""

from __future__ import annotations

from typing import List, Optional
from backend.benchmarks.schemas import BenchmarkTask, TaskScore


SURGICAL_TOOLS = {"edit_range", "multicut", "edit_symbol", "rename_symbol", "patch_hunk"}
WHOLESALE_WRITE_TOOLS = {"write_file", "replace_entire_file", "overwrite_file"}


def score_task_execution(
    task: BenchmarkTask,
    tests_passed: int,
    tests_total: int,
    new_test_failures: int = 0,
    tools_used: Optional[List[str]] = None,
    iterations: int = 1,
    tokens_used: int = 0,
    lines_changed: int = 0,
    duration_ms: float = 0.0,
    error_message: str = "",
) -> TaskScore:
    """Compute deterministic 0-100 score for a benchmark task run."""
    tools = tools_used or []

    # 1. Test Suite Pass Score (0-40)
    if tests_total > 0:
        pass_ratio = max(0.0, min(1.0, tests_passed / tests_total))
        test_score = 40.0 * pass_ratio
    elif tests_passed > 0:
        test_score = 40.0
    else:
        test_score = 0.0

    # 2. Tool Suitability Score (0-20)
    tool_score = 20.0
    # If task specified expected tools, reward matching
    if task.expected_tools_used:
        expected_matched = any(t in tools for t in task.expected_tools_used)
        if not expected_matched and tools:
            tool_score = 10.0

    # Surgical tool discipline: for small diffs (<60 lines), surgical tools must be preferred
    if 0 < lines_changed <= 60 and tools:
        used_surgical = any(t in SURGICAL_TOOLS for t in tools)
        used_wholesale = any(t in WHOLESALE_WRITE_TOOLS for t in tools)
        if used_wholesale and not used_surgical:
            # Penalize wholesale file overwrite on small edits
            tool_score = max(0.0, tool_score - 10.0)
        elif used_surgical:
            tool_score = 20.0

    # 3. No-Break / Baseline Regression Score (0-20)
    if new_test_failures > 0:
        no_break_score = 0.0
    else:
        no_break_score = 20.0

    # 4. Budget Compliance Score (0-20)
    if iterations <= task.max_iterations:
        budget_score = 20.0
    elif iterations <= int(task.max_iterations * 1.5):
        budget_score = 10.0
    else:
        budget_score = 0.0

    # High token penalty if excessive (> 120,000 tokens for simple tasks)
    if tokens_used > 120000 and task.tier <= 1:
        budget_score = max(0.0, budget_score - 10.0)

    total_score = round(test_score + tool_score + no_break_score + budget_score, 1)
    total_score = max(0.0, min(100.0, total_score))

    # Passing threshold: >= 70 points and zero baseline regressions
    passed = total_score >= 70.0 and new_test_failures == 0 and (tests_total == 0 or tests_passed > 0)
    status = "PASSED" if passed else "FAILED"

    summary_parts = [
        f"Tests: {tests_passed}/{tests_total} ({test_score:.1f}pts)",
        f"Tools: {tool_score:.1f}pts",
        f"Baseline: {no_break_score:.1f}pts",
        f"Budget: {budget_score:.1f}pts (iter {iterations}/{task.max_iterations})",
    ]
    if error_message:
        summary_parts.append(f"Error: {error_message}")

    return TaskScore(
        task_id=task.id,
        tier=task.tier,
        category=task.category,
        test_score=test_score,
        tool_score=tool_score,
        no_break_score=no_break_score,
        budget_score=budget_score,
        total_score=total_score,
        status=status,
        tests_passed=tests_passed,
        tests_total=tests_total,
        tools_used=tools,
        iterations=iterations,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        summary="; ".join(summary_parts),
    )
