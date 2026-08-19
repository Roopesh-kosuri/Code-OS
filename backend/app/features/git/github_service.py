"""Manual GitHub operations, isolated from CODE OS checkpoint automation."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException
from git import GitCommandError, Repo

from ...core.paths import ensure_within_workspace, normalize_workspace
from .github_auth import get_stored_token
from .service import repo_for


_BLOCKED_NAMES = {".env", "id_rsa", "credentials.json"}


def _relative_workspace_file(workspace: str, file_path: str) -> str:
    root = normalize_workspace(workspace)
    resolved = ensure_within_workspace(str(root), file_path)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="File is outside the workspace") from exc


def _is_blocked(repo: Repo, relative_path: str) -> bool:
    name = Path(relative_path).name.lower()
    if name in _BLOCKED_NAMES or name.endswith(".pem"):
        return True
    try:
        repo.git.check_ignore("-q", "--", relative_path)
        return True
    except GitCommandError:
        return False


def commit_selected_files(workspace: str, message: str, files: list[str]) -> str:
    """Commit only user-selected, non-ignored files; never stage implicitly."""
    if not message.strip():
        raise HTTPException(status_code=400, detail="Commit message is required")
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one file to commit")

    repo = repo_for(workspace)
    selected = [_relative_workspace_file(workspace, file_path) for file_path in files]
    blocked = [file_path for file_path in selected if _is_blocked(repo, file_path)]
    if blocked:
        raise HTTPException(status_code=400, detail=f"Refusing to commit protected or ignored file: {blocked[0]}")

    try:
        repo.git.add("--", *selected)
        return repo.index.commit(message).hexsha
    except GitCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def remotes(workspace: str) -> list[dict[str, str]]:
    repo = repo_for(workspace)
    return [{"name": remote.name, "url": next(iter(remote.urls), "")} for remote in repo.remotes]


def push_current_branch(workspace: str) -> str:
    """Push with an existing Git credential or the encrypted local PAT."""
    repo = repo_for(workspace)
    token = get_stored_token()
    branch = repo.active_branch.name if not repo.head.is_detached else None
    if not branch:
        raise HTTPException(status_code=400, detail="Cannot push while HEAD is detached")

    if not token:
        try:
            return repo.git.push()
        except GitCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Git reads the PAT only from this short-lived child-process environment.
    askpass_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as askpass:
            askpass.write("import os, sys\nprint('x-access-token' if 'Username' in sys.argv[-1] else os.environ['CODE_OS_GIT_PAT'])\n")
            askpass_path = askpass.name
        env = {
            **os.environ,
            "GIT_ASKPASS": f'"{sys.executable}" "{askpass_path}"',
            "GIT_TERMINAL_PROMPT": "0",
            "CODE_OS_GIT_PAT": token,
        }
        if repo.active_branch.tracking_branch():
            command = ["git", "push"]
        else:
            remote_names = {remote.name for remote in repo.remotes}
            remote = "origin" if "origin" in remote_names else next(iter(remote_names), None)
            if not remote:
                raise HTTPException(status_code=400, detail="No Git remote is configured")
            command = ["git", "push", "--set-upstream", remote, branch]
        return repo.git.execute(command, env=env)
    except GitCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)
