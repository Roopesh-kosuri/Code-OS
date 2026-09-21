"""Schemas and data contracts for CODE OS Benchmark Gym."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class BenchmarkTask:
    """Definition and constraints for an individual benchmark task."""
    id: str
    name: str
    tier: int
    category: str  # flask_fastapi, react_ts, refactor, rag, marathon
    prompt: str
    expected_files: List[str]
    expected_tests_pass: List[str]
    expected_tools_used: List[str] = field(default_factory=list)
    max_iterations: int = 5
    timeout_seconds: int = 60
    initial_files: Dict[str, str] = field(default_factory=dict)
    solution_files: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "category": self.category,
            "prompt": self.prompt,
            "expected_files": self.expected_files,
            "expected_tests_pass": self.expected_tests_pass,
            "expected_tools_used": self.expected_tools_used,
            "max_iterations": self.max_iterations,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BenchmarkTask:
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            tier=data.get("tier", 1),
            category=data.get("category", "general"),
            prompt=data["prompt"],
            expected_files=data.get("expected_files", []),
            expected_tests_pass=data.get("expected_tests_pass", []),
            expected_tools_used=data.get("expected_tools_used", []),
            max_iterations=data.get("max_iterations", 5),
            timeout_seconds=data.get("timeout_seconds", 60),
            initial_files=data.get("initial_files", {}),
            solution_files=data.get("solution_files", {}),
        )


@dataclass
class TaskScore:
    """Scoring breakdown for a benchmark task execution (0-100)."""
    task_id: str
    tier: int
    category: str
    test_score: float  # 0 to 40
    tool_score: float  # 0 to 20
    no_break_score: float  # 0 to 20
    budget_score: float  # 0 to 20
    total_score: float  # 0 to 100
    status: str  # PASSED or FAILED
    tests_passed: int = 0
    tests_total: int = 0
    tools_used: List[str] = field(default_factory=list)
    iterations: int = 0
    tokens_used: int = 0
    duration_ms: float = 0.0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tier": self.tier,
            "category": self.category,
            "test_score": round(self.test_score, 1),
            "tool_score": round(self.tool_score, 1),
            "no_break_score": round(self.no_break_score, 1),
            "budget_score": round(self.budget_score, 1),
            "total_score": round(self.total_score, 1),
            "status": self.status,
            "tests_passed": self.tests_passed,
            "tests_total": self.tests_total,
            "tools_used": self.tools_used,
            "iterations": self.iterations,
            "tokens_used": self.tokens_used,
            "duration_ms": round(self.duration_ms, 1),
            "summary": self.summary,
        }


@dataclass
class SuiteReport:
    """Aggregated benchmark suite results and reporting."""
    suite: str
    model: str
    task_scores: List[TaskScore] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def tasks_total(self) -> int:
        return len(self.task_scores)

    @property
    def tasks_passed(self) -> int:
        return sum(1 for s in self.task_scores if s.status == "PASSED")

    @property
    def aggregate_score(self) -> float:
        if not self.task_scores:
            return 0.0
        return sum(s.total_score for s in self.task_scores) / len(self.task_scores)

    @property
    def simple_score(self) -> float:
        simple = [s for s in self.task_scores if s.category in ("flask_fastapi", "react_ts")]
        if not simple:
            return 0.0
        return sum(s.total_score for s in simple) / len(simple)

    @property
    def refactor_score(self) -> float:
        refactor = [s for s in self.task_scores if s.category == "refactor"]
        if not refactor:
            return 0.0
        return sum(s.total_score for s in refactor) / len(refactor)

    def to_markdown_table(self) -> str:
        lines = [
            f"# Benchmark Gym Report: `{self.suite}`",
            f"**Model**: `{self.model}` | **Timestamp**: `{self.timestamp}`",
            f"**Aggregate Score**: `{self.aggregate_score:.1f}/100` | **Pass Rate**: `{self.tasks_passed}/{self.tasks_total}`",
            f"**Simple Apps Avg**: `{self.simple_score:.1f}/100` | **Refactor Avg**: `{self.refactor_score:.1f}/100`",
            "",
            "| Task ID | Tier | Category | Tests (40) | Tools (20) | Baseline (20) | Budget (20) | Total (100) | Status |",
            "|:---|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|",
        ]
        for s in self.task_scores:
            lines.append(
                f"| `{s.task_id}` | T{s.tier} | {s.category} | "
                f"{s.test_score:.1f} ({s.tests_passed}/{s.tests_total}) | "
                f"{s.tool_score:.1f} | {s.no_break_score:.1f} | {s.budget_score:.1f} | "
                f"**{s.total_score:.1f}** | {s.status} |"
            )
        lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite": self.suite,
            "model": self.model,
            "timestamp": self.timestamp,
            "tasks_total": self.tasks_total,
            "tasks_passed": self.tasks_passed,
            "aggregate_score": round(self.aggregate_score, 1),
            "simple_score": round(self.simple_score, 1),
            "refactor_score": round(self.refactor_score, 1),
            "task_scores": [s.to_dict() for s in self.task_scores],
        }
