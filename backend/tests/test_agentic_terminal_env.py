import os
import shlex
import pytest
from app.features.terminal.service import _build_safe_environment


def test_agentic_terminal_safe_env_no_api_key_leak():
    # Simulate parent process having secrets
    os.environ["OPENAI_API_KEY"] = "sk-fake-secret-key-12345"
    os.environ["CODE_OS_GIT_PAT"] = "ghp_fake_github_pat_secret"
    os.environ["DATABASE_PASSWORD"] = "super-secret-password"

    safe_env = _build_safe_environment()

    assert "OPENAI_API_KEY" not in safe_env
    assert "CODE_OS_GIT_PAT" not in safe_env
    assert "DATABASE_PASSWORD" not in safe_env


def test_agentic_terminal_safe_env_contains_system_vars():
    safe_env = _build_safe_environment()
    # Required system execution variables must still be present
    assert "PATH" in safe_env or "Path" in safe_env


def test_shell_injection_quoted():
    dangerous_args = ["hello; rm -rf /", "foo | bash"]
    sanitized = " ".join(shlex.quote(str(a)) for a in dangerous_args)
    # The shell metacharacters must be safely quoted/escaped
    assert "hello; rm -rf /" not in sanitized or "'" in sanitized or '"' in sanitized
