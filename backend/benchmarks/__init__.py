"""CODE OS Benchmark Gym.

Deterministic OSS task suite, auto-scorer, and evaluation harness.
"""

from backend.benchmarks.schemas import BenchmarkTask, TaskScore, SuiteReport
from backend.benchmarks.scorer import score_task_execution
from backend.benchmarks.tasks import list_tasks, get_task, TASKS
from backend.benchmarks.run import run_task, run_benchmark_suite

__all__ = [
    "BenchmarkTask",
    "TaskScore",
    "SuiteReport",
    "score_task_execution",
    "list_tasks",
    "get_task",
    "TASKS",
    "run_task",
    "run_benchmark_suite",
]
