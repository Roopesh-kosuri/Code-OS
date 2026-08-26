import fnmatch
import logging
import os
import re
import subprocess
from pathlib import Path

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


def parse_porcelain_blame(output: str) -> list[dict[str, object]]:
    """Parse git blame --line-porcelain output into structured line annotations."""
    lines_blame = []
    lines = output.splitlines()
    i = 0
    while i < len(lines):
        header_match = re.match(r"^([0-9a-f]{40})\s+(\d+)\s+(\d+)", lines[i])
        if not header_match:
            i += 1
            continue
        commit_sha = header_match.group(1)
        orig_line = int(header_match.group(2))
        final_line = int(header_match.group(3))
        author = "Unknown"
        author_mail = ""
        author_time = 0
        summary = ""
        i += 1
        while i < len(lines):
            line = lines[i]
            if line.startswith("\t"):
                # End of porcelain block for this line
                i += 1
                break
            if line.startswith("author "):
                author = line[7:]
            elif line.startswith("author-mail "):
                author_mail = line[12:].strip("<>")
            elif line.startswith("author-time "):
                try:
                    author_time = int(line[12:])
                except ValueError:
                    pass
            elif line.startswith("summary "):
                summary = line[8:]
            i += 1
        lines_blame.append({
            "line": final_line,
            "commit": commit_sha,
            "commit_short": commit_sha[:7],
            "author": author,
            "author_mail": author_mail,
            "author_time": author_time,
            "summary": summary,
        })
    return lines_blame


_BLAME_CACHE: dict[tuple[str, str, int, str], dict[str, object]] = {}


def blame(workspace: str, file_path: str) -> dict[str, object]:
    """Execute git blame --line-porcelain with path validation and mtime+head caching."""
    norm_ws = Path(normalize_path(workspace)).resolve()

    # Strict path escape validation: target must be inside workspace
    try:
        if os.path.isabs(file_path):
            target = Path(normalize_path(file_path)).resolve()
        else:
            target = (norm_ws / file_path).resolve()
        target.relative_to(norm_ws)
    except (ValueError, Exception) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Path escape rejected: {file_path} is outside workspace"
        ) from exc

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Target file not found")

    # Check if workspace is a valid git repository
    try:
        repo = Repo(norm_ws, search_parent_directories=True)
        if not repo.head.is_valid():
            return {"git": False, "lines": []}
        head_commit = repo.head.commit.hexsha
    except Exception:
        # Non-git workspace -> silently return without crashing
        return {"git": False, "lines": []}

    try:
        mtime = int(target.stat().st_mtime)
    except OSError:
        mtime = 0

    cache_key = (str(norm_ws), str(target), mtime, head_commit)
    if cache_key in _BLAME_CACHE:
        return _BLAME_CACHE[cache_key]

    # Run git blame --line-porcelain with arguments as a safe list (NO shell=True)
    try:
        rel_target = str(target.relative_to(norm_ws))
        proc = subprocess.run(
            ["git", "blame", "--line-porcelain", rel_target],
            cwd=str(norm_ws),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return {"git": True, "lines": []}

        parsed_lines = parse_porcelain_blame(proc.stdout)
        result = {"git": True, "lines": parsed_lines}

        # LRU cache cap
        if len(_BLAME_CACHE) > 500:
            _BLAME_CACHE.clear()
        _BLAME_CACHE[cache_key] = result
        return result
    except Exception as exc:
        logger.warning("git.blame error: %s", exc)
        return {"git": False, "lines": []}
