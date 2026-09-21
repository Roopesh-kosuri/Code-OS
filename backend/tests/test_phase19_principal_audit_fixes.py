"""
Phase 19: Principal Engineer Audit Remediation Regression Suite
Tests for findings S-001 through S-006:
- S-001: test_token_endpoint_removed_or_secured
- S-002: test_pty_spawn_uses_scrubbed_environment
- S-003: test_startup_cleanup_ignores_legitimate_substring_paths
- S-004: test_safe_write_file_blocks_symlink_parent
- S-005: test_readback_hash_detects_content_mismatch
- S-006: test_baseline_overlay_preserves_large_files
"""

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import _UNAUTHENTICATED_PATHS, get_token, TOKEN_TTL_SECONDS
from app.core.paths import safe_write_file
from app.features.ai.harness.mutation_pipeline import (
    Mutation,
    MutationKind,
    MutationResult,
    apply_mutations,
)
from app.features.ai.harness.verify_runners import (
    cleanup_verify_temp_dir,
    create_baseline_overlay,
)
from app.features.terminal import service as terminal_service
from app.main import app, cleanup_temporary_workspaces


# ── S-001: Unauthenticated Token Endpoint ──────────────────────────────────────


def test_token_endpoint_removed_or_secured():
    """Verify /api/auth/token is NOT in unauthenticated allowlist and never exposes raw token."""
    assert "/api/auth/token" not in _UNAUTHENTICATED_PATHS, (
        "/api/auth/token must NOT be in _UNAUTHENTICATED_PATHS"
    )

    client = TestClient(app)

    # 1. Unauthenticated request must be rejected by AuthMiddleware
    unauth_resp = client.get("/api/auth/token")
    assert unauth_resp.status_code == 401, (
        "Unauthenticated access to /api/auth/token must return 401 Unauthorized"
    )

    # 2. Authenticated request returns metadata only, never the session token
    valid_token = get_token()
    auth_resp = client.get(
        "/api/auth/token",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert auth_resp.status_code == 200
    data = auth_resp.json()

    assert "token" not in data or data.get("token") is None, (
        "Endpoint must not expose the session token string"
    )
    assert data.get("active") is True
    assert data.get("expires_in") == int(TOKEN_TTL_SECONDS)


# ── S-002: PTY Environment Leak ───────────────────────────────────────────────


def test_pty_spawn_uses_scrubbed_environment(tmp_path, monkeypatch):
    """Verify create_pty_session passes scrubbed environment and does not leak API keys."""
    fake_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "OPENAI_API_KEY": "sk-secret-leak-test-12345",
        "ANTHROPIC_API_KEY": "sk-ant-leak-test-67890",
        "AWS_SECRET_ACCESS_KEY": "supersecretkey",
    }
    monkeypatch.setattr(os, "environ", fake_env)

    mock_spawn = MagicMock()
    mock_proc = MagicMock()
    mock_proc.isalive.return_value = False
    mock_spawn.return_value = mock_proc

    monkeypatch.setattr(terminal_service, "PtyProcessClass", MagicMock(spawn=mock_spawn))

    session_id = "test-session-pty-env"
    session = terminal_service.create_pty_session(str(tmp_path), session_id)

    try:
        assert mock_spawn.called, "PtyProcessClass.spawn must be called"
        _, kwargs = mock_spawn.call_args
        assert "env" in kwargs, "PtyProcessClass.spawn must be called with env kwarg"
        passed_env = kwargs["env"]

        assert isinstance(passed_env, dict)
        assert "OPENAI_API_KEY" not in passed_env
        assert "ANTHROPIC_API_KEY" not in passed_env
        assert "AWS_SECRET_ACCESS_KEY" not in passed_env
        assert "PATH" in passed_env
    finally:
        terminal_service.kill_pty_session(session_id)


# ── S-003: Startup Cleanup Substring Match ─────────────────────────────────────


@pytest.mark.asyncio
async def test_startup_cleanup_ignores_legitimate_substring_paths(tmp_path):
    """Verify workspace cleanup only removes paths inside system tempdir matching test prefixes."""
    db_file = tmp_path / "test_cleanup.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE workspaces (
            path TEXT PRIMARY KEY,
            name TEXT,
            last_opened_at TEXT
        )
    """)

    sys_temp = os.path.realpath(tempfile.gettempdir())
    legitimate_paths = [
        r"D:\projects\code_os_test_suite_workspace",
        r"D:\repos\pytest_of_production_repo",
        r"D:\projects\code_os_test_helper",
        r"C:\Users\Developer\repos\pytest_of_shared",
    ]
    ephemeral_temp_paths = [
        os.path.join(sys_temp, "code_os_test_sandbox_1"),
        os.path.join(sys_temp, "pytest_of_runner_test0"),
    ]

    for p in legitimate_paths + ephemeral_temp_paths:
        cur.execute("INSERT INTO workspaces (path, name) VALUES (?, ?)", (p, Path(p).name))
    conn.commit()

    deleted = await cleanup_temporary_workspaces(conn)

    cur.execute("SELECT path FROM workspaces")
    surviving = {row[0] for row in cur.fetchall()}
    conn.close()

    for p in legitimate_paths:
        assert p in surviving, (
            f"Legitimate path '{p}' was incorrectly deleted by startup cleanup!"
        )

    for p in ephemeral_temp_paths:
        assert p not in surviving, (
            f"Ephemeral temp path '{p}' was not deleted by startup cleanup!"
        )


# ── S-004: safe_write_file TOCTOU ─────────────────────────────────────────────


def test_safe_write_file_blocks_symlink_parent(tmp_path, monkeypatch):
    """Verify safe_write_file denies write when parent directory is a symlink."""
    ws = tmp_path / "ws"
    ws.mkdir()
    child_dir = ws / "sub_dir"
    child_dir.mkdir()

    orig_is_symlink = Path.is_symlink

    def mock_is_symlink(self):
        if self.name == "sub_dir":
            return True
        return orig_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", mock_is_symlink)

    with pytest.raises(Exception) as exc_info:
        safe_write_file(str(ws), "sub_dir/secret.txt", "payload")

    assert "Symlinked parent directories not permitted" in str(exc_info.value) or "403" in str(exc_info.value)


# ── S-005: Readback Hash Detection ────────────────────────────────────────────


def test_readback_hash_detects_content_mismatch(tmp_path, monkeypatch):
    """Verify S7 readback stage computes SHA-256 and detects content mismatch."""
    ws_file = tmp_path / "file.py"
    ws_file.write_text("initial = True\n", encoding="utf-8")

    mutations = [
        Mutation(
            path="file.py",
            kind=MutationKind.WRITE_FULL,
            new_content="initial = False\n",
        )
    ]

    # First: normal apply succeeds and readback passes
    res_ok = apply_mutations(tmp_path, mutations, mode="USER_SAVE")
    assert res_ok.success is True
    assert res_ok.readback_status.get("file.py") == "passed"

    # Second: simulate disk tampering or disk divergence during readback
    original_read_bytes = Path.read_bytes

    def tampered_read_bytes(self):
        if self.name == "file.py":
            return b"malicious_divergence = 1\n"
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", tampered_read_bytes)

    res_tampered = apply_mutations(tmp_path, mutations, mode="USER_SAVE")
    assert res_tampered.success is True
    status = res_tampered.readback_status.get("file.py", "")
    assert "failed: sha256 mismatch" in status, f"Expected sha256 mismatch failure, got: {status}"


# ── S-006: >5MB Baseline Overlay Preservation ─────────────────────────────────


def test_baseline_overlay_preserves_large_files(tmp_path):
    """Verify files larger than 5MB are written to baseline overlay without truncation."""
    ws_path = tmp_path / "ws"
    ws_path.mkdir()

    large_size = 6 * 1024 * 1024  # 6 MB
    large_bytes = b"X" * large_size

    large_file = ws_path / "dataset.bin"
    large_file.write_bytes(b"modified_after_turn")

    pre_images = {"dataset.bin": large_bytes}

    base_dir, err = create_baseline_overlay(ws_path, ["dataset.bin"], pre_images, max_mb=50)
    try:
        assert err is None
        assert base_dir is not None
        restored = base_dir / "dataset.bin"
        assert restored.exists()
        restored_bytes = restored.read_bytes()
        assert len(restored_bytes) == large_size, (
            f"Expected {large_size} bytes in baseline, got {len(restored_bytes)} (was truncated!)"
        )
        assert hashlib.sha256(restored_bytes).hexdigest() == hashlib.sha256(large_bytes).hexdigest()
    finally:
        if base_dir:
            cleanup_verify_temp_dir(base_dir)

    # Also verify MutationResult evidence_payload truncates for frontend/logs
    res = MutationResult(
        success=True,
        applied_paths=["dataset.bin"],
        pre_images=pre_images,
    )
    ev = res.evidence_payload
    assert "dataset.bin" in ev
    assert "[TRUNCATED]" in ev["dataset.bin"]
    assert len(ev["dataset.bin"]) <= (5 * 1024 * 1024 + 100)
