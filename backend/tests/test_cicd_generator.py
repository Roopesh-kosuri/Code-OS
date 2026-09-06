"""
test_cicd_generator.py — Test suite for CI/CD Pipeline Generator.
"""

import json
import pytest
from pathlib import Path

from app.features.ai.cicd.stack_analyzer import analyze_stack
from app.features.ai.cicd.yaml_generator import (
    generate_pipeline,
    generate_github_actions_yaml,
    generate_gitlab_ci_yaml,
)
from app.features.ai.cicd.cicd_routes import save_endpoint, SavePipelineRequest


def test_analyze_detects_python_pytest(tmp_path: Path):
    """Verify stack analyzer correctly identifies Python and pytest."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("fastapi==0.100.0\npytest==8.0.0\nuvicorn==0.23.0\n", encoding="utf-8")

    config = analyze_stack(str(tmp_path))

    assert "python" in config["languages"]
    assert "fastapi" in config["frameworks"]
    assert "pytest" in config["test_runners"]
    assert "pip" in config["package_managers"]
    assert config["test_command"] == "pytest"


def test_analyze_detects_node_jest(tmp_path: Path):
    """Verify stack analyzer correctly identifies Node, React, and Jest."""
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text(
        json.dumps({
            "name": "my-react-app",
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0"
            },
            "devDependencies": {
                "jest": "^29.5.0",
                "typescript": "^5.0.0"
            },
            "scripts": {
                "test": "jest",
                "build": "vite build"
            }
        }),
        encoding="utf-8"
    )

    config = analyze_stack(str(tmp_path))

    assert "javascript" in config["languages"]
    assert "typescript" in config["languages"]
    assert "react" in config["frameworks"]
    assert "jest" in config["test_runners"]
    assert "npm" in config["package_managers"]
    assert config["build_command"] == "npm run build"


def test_generate_github_actions_valid_yaml():
    """Verify GitHub Actions output has valid structure and triggers."""
    stack_config = {
        "languages": ["python"],
        "frameworks": ["fastapi"],
        "test_runners": ["pytest"],
        "package_managers": ["pip"],
        "python_version": "3.11",
        "test_command": "pytest",
        "build_command": "",
    }

    res = generate_pipeline(stack_config, provider="github")

    assert res["file_path"] == ".github/workflows/ci.yml"
    yaml_text = res["yaml_content"]

    assert "name: CI Pipeline" in yaml_text
    assert "on:" in yaml_text
    assert "push:" in yaml_text
    assert "pull_request:" in yaml_text
    assert "actions/checkout@v4" in yaml_text
    assert "actions/setup-python@v5" in yaml_text
    assert "pytest" in yaml_text


def test_generate_gitlab_ci_valid_yaml():
    """Verify GitLab CI output contains stages, scripts, and caching."""
    stack_config = {
        "languages": ["javascript", "typescript"],
        "frameworks": ["react"],
        "test_runners": ["vitest"],
        "package_managers": ["npm"],
        "node_version": "20",
        "test_command": "npm test -- --run",
        "build_command": "npm run build",
    }

    res = generate_pipeline(stack_config, provider="gitlab")

    assert res["file_path"] == ".gitlab-ci.yml"
    yaml_text = res["yaml_content"]

    assert "stages:" in yaml_text
    assert "test" in yaml_text
    assert "build" in yaml_text
    assert "cache:" in yaml_text
    assert "npm test -- --run" in yaml_text
    assert "npm run build" in yaml_text


def test_yaml_includes_caching_and_test_steps():
    """Verify caching keys and test steps are properly configured for both Python and Node."""
    stack_config = {
        "languages": ["python", "typescript"],
        "frameworks": ["fastapi", "react"],
        "test_runners": ["pytest"],
        "package_managers": ["pip", "npm"],
        "python_version": "3.11",
        "node_version": "20",
        "test_command": "pytest && npm test",
        "build_command": "npm run build",
    }

    yaml_text = generate_github_actions_yaml(stack_config)

    # Caching assertions
    assert "cache: 'pip'" in yaml_text
    assert "cache: 'npm'" in yaml_text
    assert "pytest && npm test" in yaml_text
    assert "Build Project" in yaml_text


@pytest.mark.asyncio
async def test_save_writes_yaml_to_disk(tmp_path: Path):
    """Verify save endpoint writes YAML file to appropriate destination."""
    yaml_content = "name: Test\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
    target_rel = ".github/workflows/ci.yml"

    req = SavePipelineRequest(
        workspace=str(tmp_path),
        yaml_content=yaml_content,
        file_path=target_rel,
    )

    result = await save_endpoint(req)
    assert result["success"] is True

    written_file = tmp_path / ".github" / "workflows" / "ci.yml"
    assert written_file.exists()
    assert written_file.read_text(encoding="utf-8") == yaml_content
