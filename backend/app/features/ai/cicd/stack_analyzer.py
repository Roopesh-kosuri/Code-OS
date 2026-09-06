"""
stack_analyzer.py — Detects languages, frameworks, test runners, and tooling in a workspace.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def analyze_stack(workspace: str) -> Dict[str, Any]:
    """
    Analyzes the workspace root to identify technology stack details:
    languages, frameworks, test runners, package managers, and recommended commands.
    """
    ws = Path(workspace)
    if not ws.is_dir():
        return {
            "languages": [],
            "frameworks": [],
            "test_runners": [],
            "package_managers": [],
            "python_version": "3.11",
            "node_version": "20",
            "test_command": "",
            "build_command": "",
            "has_docker": False,
        }

    languages: List[str] = []
    frameworks: List[str] = []
    test_runners: List[str] = []
    package_managers: List[str] = []

    python_version = "3.11"
    node_version = "20"
    test_command = ""
    build_command = ""
    has_docker = False

    # 1. Docker check
    if (ws / "Dockerfile").exists() or (ws / "docker-compose.yml").exists() or (ws / "docker-compose.yaml").exists():
        has_docker = True

    # 2. Python Detection
    py_indicators = [
        ws / "requirements.txt",
        ws / "backend" / "requirements.txt",
        ws / "pyproject.toml",
        ws / "Pipfile",
        ws / "setup.py",
    ]
    py_found = any(p.exists() for p in py_indicators) or len(list(ws.glob("*.py"))) > 0 or (ws / "backend").is_dir()

    if py_found:
        languages.append("python")
        package_managers.append("pip")

        # Read requirements / config content for deep analysis
        req_content = ""
        for p in [ws / "requirements.txt", ws / "backend" / "requirements.txt", ws / "pyproject.toml"]:
            if p.exists():
                try:
                    req_content += "\n" + p.read_text(encoding="utf-8", errors="ignore").lower()
                except Exception:
                    pass

        # Frameworks
        if "fastapi" in req_content:
            frameworks.append("fastapi")
        if "django" in req_content:
            frameworks.append("django")
        if "flask" in req_content:
            frameworks.append("flask")

        # Test runners
        if "pytest" in req_content or (ws / "pytest.ini").exists() or (ws / "tests").is_dir() or (ws / "backend" / "tests").is_dir():
            test_runners.append("pytest")
            test_command = "pytest"
        else:
            test_runners.append("unittest")
            test_command = "python -m unittest discover"

    # 3. Node/JS/TS Detection
    pkg_json_paths = [ws / "package.json", ws / "frontend" / "package.json"]
    pkg_json_file = next((p for p in pkg_json_paths if p.exists()), None)

    if pkg_json_file:
        languages.append("javascript")
        if (ws / "pnpm-lock.yaml").exists():
            package_managers.append("pnpm")
            pm_run = "pnpm"
        elif (ws / "yarn.lock").exists():
            package_managers.append("yarn")
            pm_run = "yarn"
        else:
            package_managers.append("npm")
            pm_run = "npm"

        try:
            pkg_data = json.loads(pkg_json_file.read_text(encoding="utf-8", errors="ignore"))
            deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
            scripts = pkg_data.get("scripts", {})

            if "typescript" in deps or (ws / "tsconfig.json").exists() or (pkg_json_file.parent / "tsconfig.json").exists():
                languages.append("typescript")

            # Frameworks
            if "next" in deps:
                frameworks.append("nextjs")
            elif "react" in deps:
                frameworks.append("react")
            if "express" in deps:
                frameworks.append("express")
            if "vue" in deps:
                frameworks.append("vue")

            # Test runners
            if "vitest" in deps:
                test_runners.append("vitest")
                test_command = f"{pm_run} test -- --run" if not test_command else test_command
            elif "jest" in deps:
                test_runners.append("jest")
                test_command = f"{pm_run} test" if not test_command else test_command
            elif "mocha" in deps:
                test_runners.append("mocha")
                test_command = f"{pm_run} test" if not test_command else test_command

            # Build command
            if "build" in scripts:
                build_command = f"{pm_run} run build"
        except Exception as exc:
            logger.debug("Failed parsing package.json: %s", exc)

    # 4. Go Detection
    if (ws / "go.mod").exists():
        languages.append("go")
        test_runners.append("go test")
        if not test_command:
            test_command = "go test ./..."
        if not build_command:
            build_command = "go build -v ./..."

    # 5. Rust Detection
    if (ws / "Cargo.toml").exists():
        languages.append("rust")
        package_managers.append("cargo")
        test_runners.append("cargo test")
        if not test_command:
            test_command = "cargo test"
        if not build_command:
            build_command = "cargo build --release"

    # Deduplicate lists
    languages = list(dict.fromkeys(languages))
    frameworks = list(dict.fromkeys(frameworks))
    test_runners = list(dict.fromkeys(test_runners))
    package_managers = list(dict.fromkeys(package_managers))

    return {
        "languages": languages,
        "frameworks": frameworks,
        "test_runners": test_runners,
        "package_managers": package_managers,
        "python_version": python_version,
        "node_version": node_version,
        "test_command": test_command or "pytest",
        "build_command": build_command,
        "has_docker": has_docker,
    }
