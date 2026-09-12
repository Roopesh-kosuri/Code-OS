"""Regression tests for Phase 6.5: Language-aware verifier selection.

Verifies:
1. test_verifier_selection_cpp_never_pytest: C++ file edits never invoke pytest
2. test_verifier_selection_python_with_tests_uses_tests: Python file with test suite selects targeted pytest
3. test_verifier_choice_logged: Selection decision is logged to activity_log.jsonl
"""

import json
from pathlib import Path
import pytest

from app.features.ai.harness.verifier_selector import (
    select_verifier,
    detect_language,
)
from app.features.ai.agents.agent_tools import execute_tool_calls, ToolCall


def test_verifier_selection_cpp_never_pytest(tmp_path: Path):
    """After editing a C++ file, verifier selector must choose diagnostics or compile check, NEVER pytest."""
    ws = str(tmp_path)
    cpp_file = "src/main.cpp"

    # Scenario A: Clean C++ project without test framework
    choice = select_verifier(ws, cpp_file, log_choice=False)
    assert choice["language"] == "cpp"
    assert "pytest" not in str(choice.get("command", "")).lower()
    assert choice["verifier"] in ("diagnostics", "compile_check")
    if choice["verifier"] == "compile_check":
        assert "g++ -fsyntax-only" in choice["command"]
    else:
        assert choice["tool"] == "get_diagnostics"

    # Scenario B: C++ project that happens to have a tests/ directory containing data or non-python files
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_main.cpp").write_text("// c++ test", encoding="utf-8")

    choice_with_tests_dir = select_verifier(ws, cpp_file, log_choice=False)
    assert choice_with_tests_dir["language"] == "cpp"
    assert "pytest" not in str(choice_with_tests_dir.get("command", "")).lower()
    assert choice_with_tests_dir["verifier"] in ("diagnostics", "compile_check")


def test_verifier_selection_python_with_tests_uses_tests(tmp_path: Path):
    """When a Python file has an associated test suite, targeted test runner (pytest) is selected."""
    ws = str(tmp_path)
    py_file = "src/calculator.py"
    
    # Create test file
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / "test_calculator.py"
    test_file.write_text("def test_add(): assert 1 + 1 == 2\n", encoding="utf-8")

    choice = select_verifier(ws, py_file, log_choice=False)
    assert choice["language"] == "python"
    assert choice["verifier"] == "tests"
    assert choice["tool"] == "run_test"
    assert "pytest" in choice["command"]
    assert "tests/test_calculator.py" in choice["command"].replace("\\", "/")


def test_verifier_choice_logged(tmp_path: Path):
    """Every verifier selection must append an action_type='verifier_selection' entry to .code_os/activity_log.jsonl."""
    ws = str(tmp_path)
    file_path = "algorithm.cpp"

    choice = select_verifier(ws, file_path, log_choice=True)
    assert choice["language"] == "cpp"

    log_file = tmp_path / ".code_os" / "activity_log.jsonl"
    assert log_file.is_file(), "activity_log.jsonl was not created"

    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    matching = [entry for entry in lines if entry.get("action_type") == "verifier_selection"]

    assert len(matching) > 0, "No verifier_selection entry found in activity log"
    last_log = matching[-1]
    assert last_log["file"] == file_path
    assert last_log["language"] == "cpp"
    assert last_log["verifier"] == choice["verifier"]
    assert last_log["tool"] == choice["tool"]


def test_edit_file_tool_provides_verifier_guidance(tmp_path: Path):
    """_handle_edit_file outputs guidance for language-appropriate verifier."""
    ws = str(tmp_path)
    staged = []

    call = ToolCall(
        name="edit_file",
        arguments={
            "path": "server.cpp",
            "original": "",
            "updated": "int main() { return 0; }",
        },
    )

    output = execute_tool_calls([call], ws, staged, agent_role="coder")
    assert "✓ Staged create new file: server.cpp" in output
    assert "[Verifier Guidance]:" in output
    assert "cpp" in output.lower()
    assert "pytest" not in output.lower()
