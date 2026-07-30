import logging

from fastapi import HTTPException
from git import GitCommandError, Repo

from ...core.paths import normalize_path

logger = logging.getLogger(__name__)


def repo_for(workspace: str) -> Repo:
    logger.info("git.repo detect workspace=%s", workspace)
    try:
        repo = Repo(normalize_path(workspace), search_parent_directories=True)
        logger.info("git.repo detected git_dir=%s worktree=%s", repo.git_dir, repo.working_tree_dir)
        return repo
    except Exception as exc:
        logger.warning("git.repo not found workspace=%s reason=%s", workspace, exc)
        raise HTTPException(status_code=404, detail="Git repository not found") from exc


def status(workspace: str) -> dict[str, object]:
    repo = repo_for(workspace)
    has_head = repo.head.is_valid()
    staged = [item.a_path for item in repo.index.diff("HEAD")] if has_head else []
    unstaged = [item.a_path for item in repo.index.diff(None)]
    untracked = repo.untracked_files
    branch = repo.active_branch.name if not repo.head.is_detached else "DETACHED"
    branches = [head.name for head in repo.heads]
    if branch != "DETACHED" and branch not in branches:
        branches.insert(0, branch)
    return {
        "branch": branch,
        "dirty": repo.is_dirty(untracked_files=True),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "branches": branches,
    }


def diff(workspace: str, path: str | None = None) -> str:
    repo = repo_for(workspace)
    args = ["--", path] if path else []
    return repo.git.diff(*args)


import fnmatch
from pathlib import Path

DANGEROUS_PATTERNS = [
    ".env*", "*.pem", "*.key", "*secret*", "*credential*", "*credentials*", "id_rsa*", "id_ed25519*"
]



def is_dangerous_file(filepath: str) -> bool:
    path_obj = Path(filepath)
    name = path_obj.name.lower()
    for pat in DANGEROUS_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return True
        for part in path_obj.parts:
            if fnmatch.fnmatch(part.lower(), pat):
                return True
    return False


def commit(workspace: str, message: str, files: list[str] | None = None) -> str:
    if not message.strip():
        raise HTTPException(status_code=400, detail="Commit message is required")
    repo = repo_for(workspace)
    from ...core.paths import ensure_within_workspace, normalize_workspace
    norm_workspace = str(normalize_workspace(workspace))

    try:
        if files:
            # Stage ONLY specific valid, non-dangerous files inside workspace
            for f in files:
                valid_path = ensure_within_workspace(norm_workspace, f)
                rel_path = str(valid_path.relative_to(norm_workspace))

                if is_dangerous_file(rel_path):
                    logger.warning("Refusing to stage dangerous file: %s", rel_path)
                    continue

                repo.git.add(rel_path)
        else:
            # Stage ONLY tracked modifications (git add -u), NOT untracked files
            repo.git.add(u=True)

        # Safety Check: Unstage any file matching secret patterns before committing
        staged_items = [item.a_path for item in repo.index.diff("HEAD")] if repo.head.is_valid() else []
        for item_path in staged_items:
            if is_dangerous_file(item_path):
                logger.warning("Unstaging dangerous secret file from commit: %s", item_path)
                try:
                    repo.git.restore("--staged", item_path)
                except Exception:
                    repo.git.reset("HEAD", "--", item_path)

        commit_obj = repo.index.commit(message)
        return commit_obj.hexsha
    except GitCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



def pull(workspace: str) -> str:
    try:
        repo = repo_for(workspace)
        return repo.git.pull()
    except GitCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def push(workspace: str) -> str:
    try:
        repo = repo_for(workspace)
        branch = repo.active_branch.name if not repo.head.is_detached else None
        if branch:
            try:
                return repo.git.push()
            except GitCommandError as exc:
                if "no upstream branch" in str(exc).lower() or "has no upstream" in str(exc).lower():
                    return repo.git.push("--set-upstream", "origin", branch)
                raise
        return repo.git.push()
    except GitCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def switch_branch(workspace: str, branch: str) -> str:
    try:
        repo = repo_for(workspace)
        repo.git.checkout(branch)
        return branch
    except GitCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_branch(workspace: str, branch: str, checkout: bool = True) -> str:
    if not branch.strip():
        raise HTTPException(status_code=400, detail="Branch name is required")
    try:
        repo = repo_for(workspace)
        repo.create_head(branch)
        if checkout:
            repo.git.checkout(branch)
        return branch
    except GitCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def history(workspace: str, limit: int = 30) -> list[dict[str, str]]:
    repo = repo_for(workspace)
    if not repo.head.is_valid():
        return []
    return [
        {
            "sha": commit.hexsha[:12],
            "message": commit.message.strip().splitlines()[0] if commit.message else "",
            "author": str(commit.author),
            "committed_at": commit.committed_datetime.isoformat(),
        }
        for commit in repo.iter_commits(max_count=limit)
    ]
