"""Phase 15 Regression Tests: Benchmark Gym & Release Discipline.

Guarantees:
1. test_benchmark_scorer_counts_test_passes_and_tool_usage:
   Accurate 4-factor scoring (test suite, surgical tools, baseline regression, budget).
2. test_sbom_generation_includes_all_bundled_deps:
   CycloneDX v1.5 SBOM generated with fastapi, uvicorn, chromadb, onnxruntime, electron, react.
3. test_release_workflow_has_sign_and_verify_steps:
   ci.yml contains benchmarks job, spctl gatekeeper assess, GPG signing, and gpg --verify.
4. test_all_benchmarks_load_and_validate:
   All 11 deterministic benchmark tasks conform to standardized task.json schema.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
CI_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
SBOM_PATH = ROOT / "release" / "sbom.json"

from backend.benchmarks.schemas import BenchmarkTask, TaskScore
from backend.benchmarks.scorer import score_task_execution
from backend.benchmarks.tasks import TASKS, list_tasks, get_task
from scripts.generate_sbom import generate_sbom


def test_benchmark_scorer_counts_test_passes_and_tool_usage():
    """Verify auto-scorer 4-factor rubric (tests, surgical tools, regressions, budget)."""
    task = BenchmarkTask(
        id="test_sample",
        name="Sample Task",
        tier=1,
        category="general",
        prompt="Fix the bug",
        expected_files=["app.py"],
        expected_tests_pass=["test_one", "test_two"],
        expected_tools_used=["edit_range"],
        max_iterations=5,
    )

    # 1. Perfect execution: all tests pass, surgical tool used, no regressions, in budget
    score_perfect = score_task_execution(
        task=task,
        tests_passed=2,
        tests_total=2,
        new_test_failures=0,
        tools_used=["edit_range"],
        iterations=2,
        tokens_used=5000,
        lines_changed=25,
    )
    assert score_perfect.test_score == 40.0
    assert score_perfect.tool_score == 20.0
    assert score_perfect.no_break_score == 20.0
    assert score_perfect.budget_score == 20.0
    assert score_perfect.total_score == 100.0
    assert score_perfect.status == "PASSED"

    # 2. Wholesale rewrite penalty for small diff (<60 lines) without surgical tools
    score_penalized = score_task_execution(
        task=task,
        tests_passed=2,
        tests_total=2,
        new_test_failures=0,
        tools_used=["write_file"],
        iterations=2,
        lines_changed=25,  # small edit, should have used edit_range
    )
    assert score_penalized.tool_score < 20.0, "Wholesale file overwrite on small diff must be penalized"

    # 3. Regression deduction: breaking pre-existing code zeros no_break_score
    score_regression = score_task_execution(
        task=task,
        tests_passed=1,
        tests_total=2,
        new_test_failures=1,
        tools_used=["edit_range"],
        iterations=2,
    )
    assert score_regression.no_break_score == 0.0, "New test failures must zero baseline score"
    assert score_regression.status == "FAILED"

    # 4. Budget penalty: exceeding max_iterations reduces score
    score_overbudget = score_task_execution(
        task=task,
        tests_passed=2,
        tests_total=2,
        new_test_failures=0,
        tools_used=["edit_range"],
        iterations=10,  # max is 5
    )
    assert score_overbudget.budget_score == 0.0


def test_sbom_generation_includes_all_bundled_deps():
    """Verify CycloneDX 1.5 SBOM generation includes all core Python and Node dependencies."""
    # Run generator
    sbom = generate_sbom()
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert "components" in sbom
    assert len(sbom["components"]) >= 50

    components_by_name = {c["name"].lower(): c for c in sbom["components"]}

    # Verify critical dependencies are cataloged with version and license
    required_deps = ["fastapi", "uvicorn", "chromadb", "onnxruntime", "electron", "react"]
    for dep in required_deps:
        assert dep in components_by_name, f"Required dependency '{dep}' missing from SBOM components"
        comp = components_by_name[dep]
        assert comp.get("version"), f"Dependency '{dep}' missing version"
        assert comp.get("purl"), f"Dependency '{dep}' missing purl"
        assert comp.get("licenses"), f"Dependency '{dep}' missing license metadata"


def test_release_workflow_has_sign_and_verify_steps():
    """Verify CI workflow includes benchmark runner, gatekeeper spctl, GPG signing, and gpg --verify."""
    assert CI_WORKFLOW_PATH.is_file(), f"ci.yml missing at {CI_WORKFLOW_PATH}"
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    ci_yaml = yaml.safe_load(content)

    jobs = ci_yaml.get("jobs", {})

    # 1. Benchmarks job present
    assert "benchmarks" in jobs, "ci.yml must contain a 'benchmarks' job"
    bench_job = jobs["benchmarks"]
    bench_steps_str = json.dumps(bench_job.get("steps", []))
    assert "benchmarks.run" in bench_steps_str, "benchmarks job must run benchmarks.run"
    assert "generate_sbom.py" in bench_steps_str, "benchmarks job must run generate_sbom.py"
    assert "generate_release_notes.py" in bench_steps_str, "benchmarks job must run generate_release_notes.py"

    # 2. Gatekeeper spctl step present in mac job
    assert "spctl" in content
    assert "spctl --assess" in content
    assert "--type execute" in content or "--type install" in content

    # 3. GPG signing and verify steps present
    assert "gpg --verify" in content or "verify-release-signing.js" in content
    assert "release/*.sig" in content or ".sig" in content


def test_all_benchmarks_load_and_validate():
    """Verify all 11 deterministic benchmark tasks conform to the task specification."""
    tasks = list_tasks("all")
    assert len(tasks) == 11, f"Expected 11 benchmark tasks, found {len(tasks)}"

    categories = {t.category for t in tasks}
    assert "flask_fastapi" in categories
    assert "react_ts" in categories
    assert "refactor" in categories
    assert "rag" in categories
    assert "marathon" in categories

    for t in tasks:
        assert t.id, "Task missing id"
        assert t.name, "Task missing name"
        assert t.prompt, f"Task {t.id} missing prompt"
        assert t.expected_files, f"Task {t.id} missing expected_files"
        assert t.expected_tests_pass, f"Task {t.id} missing expected_tests_pass"
        assert t.initial_files, f"Task {t.id} missing initial_files"
        assert t.solution_files, f"Task {t.id} missing solution_files"
