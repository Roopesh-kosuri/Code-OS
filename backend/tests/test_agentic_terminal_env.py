import os
import pytest
from pathlib import Path
from app.features.ai.terminal.agentic_terminal_service import (
    create_session,
    execute_command,
    get_session,
)


@pytest.mark.asyncio
async def test_agentic_terminal_sanitizes_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret-key-12345")
    monkeypatch.setenv("CODE_OS_GIT_PAT", "ghp_dummy_secret_token_abcde")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-access-key")
    monkeypatch.setenv("DB_PASSWORD", "super_secret_password")
    monkeypatch.setenv("AUTH_TOKEN", "token_value")

    term_id = create_session("env_test_job", str(tmp_path))

    # 1. printenv OPENAI_API_KEY -> empty
    res = await execute_command(term_id, "printenv OPENAI_API_KEY")
    assert res["stdout"].strip() == ""

    # 2. printenv CODE_OS_GIT_PAT -> empty
    res = await execute_command(term_id, "printenv CODE_OS_GIT_PAT")
    assert res["stdout"].strip() == ""

    # 3. printenv -> contains no KEY/SECRET/TOKEN/PASS/AUTH vars
    res = await execute_command(term_id, "printenv")
    stdout = res["stdout"]
    for line in stdout.splitlines():
        k = line.split("=")[0].upper()
        if k in ("SSH_AGENT_PID", "SSH_AUTH_SOCK"):
            continue
        assert not any(bad in k for bad in ("KEY", "SECRET", "TOKEN", "PASS", "AUTH")), f"Leaked sensitive env var: {line}"


@pytest.mark.asyncio
async def test_agentic_terminal_prevents_arg_injection(tmp_path: Path):
    term_id = create_session("injection_test_job", str(tmp_path))

    # Create a canary file that would be deleted if "; rm ..." were interpreted
    canary = tmp_path / "canary.txt"
    canary.write_text("safe")

    # Pass malicious argument containing shell separator and dangerous command
    dangerous_arg = f"; rm {canary.name}"
    res = await execute_command(term_id, "echo", [dangerous_arg])

    # The arg must be printed as literal string, NOT executed as a shell command
    assert canary.exists(), "Canary file was deleted! Command injection occurred!"
    assert dangerous_arg in res["stdout"]
