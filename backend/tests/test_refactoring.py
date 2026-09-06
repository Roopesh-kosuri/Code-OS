"""test_refactoring.py — Automated test suite for Refactoring Assistant."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.features.ai.refactoring.analyze_service import (
    analyze_complexity,
    detect_code_smells,
    find_duplicates,
)
from app.features.ai.refactoring.pattern_applier import apply_refactor
from app.features.ai.refactoring.verify_service import verify_refactor_safety


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(prefix="test_refactor_ws_") as tmp_dir:
        yield Path(tmp_dir)


def test_detect_long_function(temp_workspace: Path):
    """1. Verify that long_function smell (> 30 lines) is accurately identified via AST."""
    target_file = temp_workspace / "service.py"
    # Create a function with 38 lines
    lines = ["def process_large_dataset(items):", "    results = []"]
    for i in range(35):
        lines.append(f"    item_{i} = items.get('key_{i}', {i}) * 2")
    lines.append("    return results")
    target_file.write_text("\n".join(lines), encoding="utf-8")

    smells = detect_code_smells(str(temp_workspace))
    long_fn_smells = [s for s in smells if s["type"] == "long_function"]

    assert len(long_fn_smells) >= 1
    assert long_fn_smells[0]["location"]["file"] == "service.py"
    assert "process_large_dataset" in long_fn_smells[0]["description"]
    assert long_fn_smells[0]["severity"] in ("Warning", "Critical")


def test_find_duplicated_code(temp_workspace: Path):
    """2. Verify that duplicate code blocks across files are detected with locations."""
    file_a = temp_workspace / "module_a.py"
    file_b = temp_workspace / "module_b.py"

    duplicate_block = """
def authenticate_user(token: str):
    if not token:
        raise ValueError("Missing token")
    decoded = token.strip()
    return {"token": decoded, "valid": True}
"""
    file_a.write_text(f"# Module A\n{duplicate_block}\n", encoding="utf-8")
    file_b.write_text(f"# Module B\n{duplicate_block}\n", encoding="utf-8")

    duplicates = find_duplicates(str(temp_workspace))
    assert len(duplicates) >= 1
    dup_entry = duplicates[0]
    assert len(dup_entry["occurrences"]) == 2
    assert dup_entry["line_count"] >= 5
    files = [occ["file"] for occ in dup_entry["occurrences"]]
    assert "module_a.py" in files
    assert "module_b.py" in files


def test_extract_function_refactor(temp_workspace: Path):
    """3. Verify extract_function extracts logic into helper and generates diff preview."""
    target_file = temp_workspace / "calculator.py"
    content = """def calculate_metrics(values):
    cleaned = [v for v in values if v > 0]
    total = sum(cleaned)
    avg = total / max(len(cleaned), 1)
    variance = sum((x - avg) ** 2 for x in cleaned)
    std_dev = variance ** 0.5
    return {"avg": avg, "std_dev": std_dev}
"""
    target_file.write_text(content, encoding="utf-8")

    req = {
        "refactor_type": "extract_function",
        "file": "calculator.py",
        "params": {"extracted_name": "compute_variance_and_dev"},
    }
    result = apply_refactor(req, str(temp_workspace))
    assert "changes" in result
    assert "preview" in result
    assert len(result["changes"]) == 1

    updated = result["changes"][0]["updated_content"]
    assert "def compute_variance_and_dev():" in updated
    assert "compute_variance_and_dev()" in updated
    assert result["preview"]["lines_added"] >= 0
    assert "diff" in result["preview"]
    assert "-    variance" in result["preview"]["diff"] or "+def compute_variance_and_dev" in result["preview"]["diff"]


def test_rename_symbol_preserves_context(temp_workspace: Path):
    """4. Verify rename_symbol renames target symbol while preserving surrounding identifier context."""
    target_file = temp_workspace / "model.py"
    content = """# Config
user_token = "abc123xyz"
active_user_token_flag = True
def get_auth():
    print(f"Token: {user_token}")
    return user_token
"""
    target_file.write_text(content, encoding="utf-8")

    req = {
        "refactor_type": "rename_symbol",
        "file": "model.py",
        "params": {
            "old_name": "user_token",
            "new_name": "auth_token",
        },
    }
    result = apply_refactor(req, str(temp_workspace))
    updated = result["changes"][0]["updated_content"]

    # user_token replaced by auth_token
    assert "auth_token = \"abc123xyz\"" in updated
    assert "return auth_token" in updated
    # active_user_token_flag MUST remain intact due to word boundary checks
    assert "active_user_token_flag = True" in updated


def test_apply_strategy_pattern(temp_workspace: Path):
    """5. Verify apply_strategy_pattern converts complex conditional chains into strategy tables."""
    target_file = temp_workspace / "dispatcher.py"
    content = """def handle_event(event_type: str, payload: dict):
    if event_type == "login":
        return {"action": "user_logged_in", "data": payload}
    elif event_type == "logout":
        return {"action": "user_logged_out", "data": payload}
    elif event_type == "ping":
        return {"action": "pong", "data": payload}
    else:
        return {"action": "unknown"}
"""
    target_file.write_text(content, encoding="utf-8")

    req = {
        "refactor_type": "apply_strategy_pattern",
        "file": "dispatcher.py",
        "params": {},
    }
    result = apply_refactor(req, str(temp_workspace))
    updated = result["changes"][0]["updated_content"]

    assert "HANDLE_EVENT_STRATEGIES = {" in updated
    assert "execute_strategy" in updated
    assert result["preview"]["complexity_reduction"] >= 1


def test_verify_refactor_runs_tests(temp_workspace: Path):
    """6. Verify verify_refactor_safety runs tests in sandbox and confirms safety for passing changes."""
    # Write module and test in workspace
    mod_file = temp_workspace / "math_utils.py"
    mod_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    test_file = temp_workspace / "test_math.py"
    test_file.write_text(
        "from math_utils import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    safe_change = [
        {
            "file": "math_utils.py",
            "updated_content": "def add(a, b):\n    \"\"\"Add two numbers.\"\"\"\n    return int(a) + int(b)\n",
        }
    ]

    res = verify_refactor_safety(safe_change, str(temp_workspace))
    assert res["safe"] is True
    assert res["test_results"]["passed"] is True
    assert res["test_results"]["exit_code"] == 0


def test_refactor_blocked_if_tests_fail(temp_workspace: Path):
    """7. Verify refactor is marked unsafe and blocked from applying when sandbox tests fail."""
    mod_file = temp_workspace / "math_utils.py"
    mod_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    test_file = temp_workspace / "test_math.py"
    test_file.write_text(
        "from math_utils import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    breaking_change = [
        {
            "file": "math_utils.py",
            "updated_content": "def add(a, b):\n    return a - b  # Bug introduced!\n",
        }
    ]

    # Verify safety check reports unsafe
    res = verify_refactor_safety(breaking_change, str(temp_workspace))
    assert res["safe"] is False
    assert res["test_results"]["passed"] is False
    assert len(res["test_results"]["failed_tests"]) > 0

    # Verify /api/refactor/apply blocks application when not verified and tests fail
    from app.core.auth import get_token
    token = get_token()
    client = TestClient(app)
    response = client.post(
        "/api/refactor/apply",
        json={
            "workspace": str(temp_workspace),
            "changes": breaking_change,
            "verified": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "verification failed" in response.json()["detail"]["error"].lower()

    # Verify file was NOT modified in the actual workspace!
    assert "return a + b" in mod_file.read_text(encoding="utf-8")
