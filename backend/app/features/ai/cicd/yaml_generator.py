"""
yaml_generator.py — Generates production-ready CI/CD configuration files (GitHub Actions / GitLab CI).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def generate_github_actions_yaml(config: Dict[str, Any]) -> str:
    """Generate GitHub Actions CI workflow YAML with caching, test, and build stages."""
    languages = config.get("languages", ["python"])
    has_python = "python" in languages
    has_node = any(l in languages for l in ("javascript", "typescript"))
    py_ver = config.get("python_version", "3.11")
    node_ver = config.get("node_version", "20")
    test_cmd = config.get("test_command", "pytest")
    build_cmd = config.get("build_command", "")
    node_pms = [p for p in config.get("package_managers", []) if p in ("npm", "yarn", "pnpm")]
    node_pm = node_pms[0] if node_pms else "npm"

    steps: list[str] = [
        "      - name: Checkout code\n        uses: actions/checkout@v4"
    ]

    if has_python:
        steps.append(
            f"      - name: Set up Python {py_ver}\n"
            f"        uses: actions/setup-python@v5\n"
            f"        with:\n"
            f"          python-version: '{py_ver}'\n"
            f"          cache: 'pip'"
        )
        steps.append(
            "      - name: Install Python dependencies\n"
            "        run: |\n"
            "          python -m pip install --upgrade pip\n"
            "          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi\n"
            "          if [ -f backend/requirements.txt ]; then pip install -r backend/requirements.txt; fi"
        )

    if has_node:
        cache_key = "npm" if node_pm == "npm" else ("yarn" if node_pm == "yarn" else "pnpm")
        steps.append(
            f"      - name: Set up Node.js {node_ver}\n"
            f"        uses: actions/setup-node@v4\n"
            f"        with:\n"
            f"          node-version: '{node_ver}'\n"
            f"          cache: '{cache_key}'"
        )
        install_cmd = "npm ci" if node_pm == "npm" else f"{node_pm} install"
        steps.append(
            f"      - name: Install Node dependencies\n"
            f"        run: {install_cmd}"
        )

    # Test step
    steps.append(
        f"      - name: Run Test Suite\n"
        f"        run: {test_cmd}"
    )

    # Build step if applicable
    if build_cmd:
        steps.append(
            f"      - name: Build Project\n"
            f"        run: {build_cmd}"
        )

    rendered_steps = "\n".join(steps)

    yaml_text = (
        "name: CI Pipeline\n\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main, master, develop ]\n"
        "  pull_request:\n"
        "    branches: [ main, master, develop ]\n\n"
        "jobs:\n"
        "  test-and-build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"{rendered_steps}\n"
    )

    return yaml_text


def generate_gitlab_ci_yaml(config: Dict[str, Any]) -> str:
    """Generate GitLab CI configuration YAML with test, build stages, and caching."""
    languages = config.get("languages", ["python"])
    has_python = "python" in languages
    test_cmd = config.get("test_command", "pytest")
    build_cmd = config.get("build_command", "")

    stages = ["test"]
    if build_cmd:
        stages.append("build")

    stages_yaml = "\n".join([f"  - {s}" for s in stages])

    image = "python:3.11-slim" if has_python else "node:20-alpine"

    cache_paths = "    - .cache/pip\n    - venv/" if has_python else "    - node_modules/\n    - .npm/"

    before_script = ""
    if has_python:
        before_script = (
            "  before_script:\n"
            "    - python -V\n"
            "    - python -m pip install --upgrade pip\n"
            "    - if [ -f requirements.txt ]; then pip install -r requirements.txt; fi\n"
            "    - if [ -f backend/requirements.txt ]; then pip install -r backend/requirements.txt; fi"
        )
    else:
        before_script = (
            "  before_script:\n"
            "    - node -v\n"
            "    - npm ci"
        )

    build_job = ""
    if build_cmd:
        build_job = (
            "\nbuild:\n"
            "  stage: build\n"
            "  script:\n"
            f"    - {build_cmd}\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - dist/\n"
            "      - build/\n"
            "    expire_in: 1 week\n"
        )

    yaml_text = (
        f"image: {image}\n\n"
        f"stages:\n"
        f"{stages_yaml}\n\n"
        f"cache:\n"
        f"  key: ${{CI_COMMIT_REF_SLUG}}\n"
        f"  paths:\n"
        f"{cache_paths}\n\n"
        f"test:\n"
        f"  stage: test\n"
        f"{before_script}\n"
        f"  script:\n"
        f"    - {test_cmd}\n"
        f"{build_job}"
    )

    return yaml_text


def generate_pipeline(stack_config: Dict[str, Any], provider: str = "github") -> Dict[str, str]:
    """
    Generates CI/CD pipeline YAML content and target file path based on provider.
    Returns: {
        "yaml_content": str,
        "file_path": str
    }
    """
    prov = provider.lower()
    if prov in ("gitlab", "gitlab-ci", "gitlab_ci"):
        content = generate_gitlab_ci_yaml(stack_config)
        path = ".gitlab-ci.yml"
    else:
        content = generate_github_actions_yaml(stack_config)
        path = ".github/workflows/ci.yml"

    return {
        "yaml_content": content,
        "file_path": path,
    }
