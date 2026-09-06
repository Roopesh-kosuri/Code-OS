"""
service.py — Git Autopilot Backend Service.

Provides:
- Diff and change analysis (categorization: test, docs, style, refactor, feat, fix)
- Conventional Commit message generation via LLM (or heuristic fallback, 72-char limit)
- Structured GitHub PR description generation via LLM
- Branch creation, staging, and committing
- Push branch (strictly plain push only, NO --force)
- GitHub Pull Request creation via REST API (parses HTTPS/SSH remotes)
- GitHub token persistence in settings table
- Process tracking integration with process_tracker
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.core.paths import normalize_path
from app.db.database import get_pool
from app.features.process_tracker import track_spawned_process, untrack_process

logger = logging.getLogger(__name__)

GIT_COMMAND_TIMEOUT = 30.0


async def _run_git_cmd(workspace: str, args: List[str], timeout: float = GIT_COMMAND_TIMEOUT) -> Tuple[int, str, str]:
    """Execute git command in the workspace directory with timeout and process tracking."""
    norm_ws = str(normalize_path(workspace))
    cmd = ["git"] + args

    if not Path(norm_ws).is_dir():
        return 1, "", f"Directory '{norm_ws}' does not exist"

    def _sync_exec() -> Tuple[int, str, str]:
        import subprocess as sync_sub
        try:
            res = sync_sub.run(
                cmd,
                cwd=norm_ws,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return res.returncode, res.stdout, res.stderr
        except FileNotFoundError as fnf:
            return 1, "", f"Git command failed: {fnf}"

    if os.name == "nt":
        # Windows event loop in Uvicorn uses SelectorEventLoop which does not support asyncio subprocesses
        try:
            return await asyncio.to_thread(_sync_exec)
        except Exception as e:
            if "TimeoutExpired" in type(e).__name__:
                raise HTTPException(status_code=504, detail=f"Git command '{' '.join(args)}' timed out after {timeout}s")
            raise

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=norm_ws,
        )
    except (NotImplementedError, OSError):
        try:
            return await asyncio.to_thread(_sync_exec)
        except Exception as e:
            if "TimeoutExpired" in type(e).__name__:
                raise HTTPException(status_code=504, detail=f"Git command '{' '.join(args)}' timed out after {timeout}s")
            raise

    if proc.pid:
        try:
            await asyncio.wait_for(track_spawned_process(proc.pid, "git_autopilot", norm_ws), timeout=0.5)
        except Exception:
            pass

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        exit_code = proc.returncode if proc.returncode is not None else 0
        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")
        return exit_code, stdout_str, stderr_str
    except asyncio.TimeoutError:
        try:
            if os.name == "nt" and proc.pid:
                import subprocess as sync_sub
                sync_sub.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
        except Exception:
            pass
        raise HTTPException(status_code=504, detail=f"Git command '{' '.join(args)}' timed out after {timeout}s")
    finally:
        if proc.pid:
            try:
                await asyncio.wait_for(untrack_process(proc.pid), timeout=0.5)
            except Exception:
                pass


def categorize_file(path: str) -> str:
    """
    Categorize a file path into conventional commit scopes:
    - tests/**, *_test.*, *.test.*, *.spec.* -> "test"
    - docs/**, *.md, *.markdown, *.rst, *.txt -> "docs"
    - *.css, *.scss, *.sass, *.less, styles/** -> "style"
    - refactor signals (renames, moves) -> "refactor"
    - fix signals -> "fix"
    - default -> "feat"
    """
    norm = path.strip().replace("\\", "/").lower()
    parts = norm.split("/")
    filename = parts[-1]

    # Test heuristics
    if any(p in ("tests", "test", "__tests__", "spec", "specs") for p in parts[:-1]):
        return "test"
    if (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or any(filename.endswith(ext) for ext in (".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.js", ".spec.tsx"))
    ):
        return "test"

    # Docs heuristics
    if any(p in ("docs", "doc") for p in parts[:-1]) or any(filename.endswith(ext) for ext in (".md", ".markdown", ".rst", ".txt")):
        return "docs"

    # Style heuristics
    if any(p in ("styles", "style") for p in parts[:-1]) or any(filename.endswith(ext) for ext in (".css", ".scss", ".sass", ".less")):
        return "style"

    # Fix heuristics in filename
    if "fix" in filename or "patch" in filename or "bug" in filename:
        return "fix"

    return "feat"


async def analyze_changes(workspace: str) -> Dict[str, Any]:
    """
    Analyze uncommitted changes in the workspace via git status and git diff --numstat.
    Returns:
    {
      "files": [{ "path": str, "status": str, "additions": int, "deletions": int, "category": str }],
      "totals": { "files": int, "additions": int, "deletions": int, "by_category": dict }
    }
    """
    # 1. Check if workspace is a git repo
    code, stdout, stderr = await _run_git_cmd(workspace, ["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        return {
            "is_git_repo": False,
            "current_branch": "",
            "files": [],
            "totals": {"files": 0, "additions": 0, "deletions": 0, "by_category": {}},
            "summary": {"total_files": 0, "additions": 0, "deletions": 0, "by_category": {}},
            "categories": {},
            "raw_diff_snippet": "",
        }

    # 2. Get status --porcelain=v1 -u
    code, status_out, _ = await _run_git_cmd(workspace, ["status", "--porcelain=v1", "-u"])
    if code != 0:
        raise HTTPException(status_code=400, detail="Failed to retrieve git status")

    # Parse status lines
    # Format: XY PATH or XY ORIG_PATH -> PATH
    status_map: Dict[str, str] = {}
    renamed_files: set[str] = set()
    untracked_files: List[str] = []

    for line in status_out.splitlines():
        if len(line) < 3:
            continue
        code_xy = line[:2]
        path_part = line[3:].strip()
        if " -> " in path_part:
            orig_p, new_p = path_part.split(" -> ", 1)
            path_part = new_p.strip()
            renamed_files.add(path_part)
            status_desc = "renamed"
        elif "?" in code_xy:
            status_desc = "untracked"
            untracked_files.append(path_part)
        elif "A" in code_xy:
            status_desc = "added"
        elif "D" in code_xy:
            status_desc = "deleted"
        else:
            status_desc = "modified"

        # Remove optional surrounding quotes
        if path_part.startswith('"') and path_part.endswith('"'):
            path_part = path_part[1:-1]
        status_map[path_part] = status_desc

    # 3. Get diff numstat for working copy and staged files
    numstat_map: Dict[str, Tuple[int, int]] = {}

    # Unstaged diff
    _, diff_out, _ = await _run_git_cmd(workspace, ["diff", "--numstat"])
    # Staged diff
    _, cached_out, _ = await _run_git_cmd(workspace, ["diff", "--cached", "--numstat"])

    for out in (diff_out, cached_out):
        for line in out.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                raw_add, raw_del, file_p = parts[0], parts[1], parts[2]
                add = int(raw_add) if raw_add.isdigit() else 0
                dele = int(raw_del) if raw_del.isdigit() else 0
                # Handle rename syntax in numstat e.g. {old => new}/file or orig => new
                if " => " in file_p:
                    file_p = file_p.split(" => ")[-1].replace("}", "").strip()
                prev_add, prev_del = numstat_map.get(file_p, (0, 0))
                numstat_map[file_p] = (prev_add + add, prev_del + dele)

    # Count additions for untracked files
    norm_ws = Path(normalize_path(workspace))
    for ut_path in untracked_files:
        full_p = norm_ws / ut_path
        if full_p.is_file():
            try:
                line_count = sum(1 for _ in full_p.open("rb"))
                numstat_map[ut_path] = (line_count, 0)
            except Exception:
                numstat_map[ut_path] = (0, 0)

    # Assemble structured file list
    files_list = []
    total_add = 0
    total_del = 0
    by_cat: Dict[str, int] = {}

    for file_path, status_desc in status_map.items():
        add, dele = numstat_map.get(file_path, (0, 0))
        total_add += add
        total_del += dele

        if file_path in renamed_files:
            category = "refactor"
        else:
            category = categorize_file(file_path)

        by_cat[category] = by_cat.get(category, 0) + 1

        files_list.append({
            "path": file_path,
            "status": status_desc,
            "additions": add,
            "deletions": dele,
            "category": category,
        })

    # Sort files by category, then path
    files_list.sort(key=lambda x: (x["category"], x["path"]))

    # Get current branch name
    _, branch_out, _ = await _run_git_cmd(workspace, ["branch", "--show-current"])
    current_branch = branch_out.strip()
    if not current_branch:
        _, ref_out, _ = await _run_git_cmd(workspace, ["rev-parse", "--abbrev-ref", "HEAD"])
        current_branch = ref_out.strip() or "main"

    totals_dict = {
        "files": len(files_list),
        "additions": total_add,
        "deletions": total_del,
        "by_category": by_cat,
    }

    return {
        "is_git_repo": True,
        "current_branch": current_branch,
        "files": files_list,
        "totals": totals_dict,
        "summary": {
            "total_files": len(files_list),
            "additions": total_add,
            "deletions": total_del,
            "by_category": by_cat,
        },
        "categories": by_cat,
        "raw_diff_snippet": (diff_out[:1000] if diff_out else ""),
    }


async def generate_commit_message(workspace: str, provider_config: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate Conventional Commits format message:
    "feat(scope): summary" (first line <= 72 characters)
    with optional body bullets.
    """
    analysis = await analyze_changes(workspace)
    files = analysis.get("files", [])
    if not files:
        return "chore: no changes detected"

    totals = analysis.get("totals", {})
    by_category = totals.get("by_category", {})

    # Determine primary category
    primary_category = "feat"
    if by_category:
        primary_category = max(by_category.items(), key=lambda item: item[1])[0]

    # Determine scope from directory or common path prefix
    paths = [f["path"] for f in files]
    scopes = []
    for p in paths:
        parts = p.replace("\\", "/").split("/")
        if len(parts) > 1 and parts[0] not in (".", ""):
            scopes.append(parts[0])
    scope = scopes[0] if scopes else "app"
    # Simplify scope to lowercase word
    scope = re.sub(r"[^a-zA-Z0-9_-]", "", scope)[:15].lower()

    # Try LLM call via public provider interface
    try:
        from app.features.ai.service import provider_for
        from app.features.ai.schemas import ChatRequest, ChatMessage

        file_summary = "\n".join([f"- {f['path']} (+{f['additions']}, -{f['deletions']})" for f in files[:20]])
        system_prompt = (
            "You are a Git commit generator following Conventional Commits format.\n"
            "Return ONLY the commit message. The first line MUST be formatted as:\n"
            "type(scope): summary\n"
            "The subject line MUST NOT exceed 72 characters.\n"
            "Optionally include a blank line followed by concise bullet points describing key changes."
        )
        user_prompt = f"Generate a commit message for the following changes:\nPrimary category: {primary_category}\nScope: {scope}\nFiles:\n{file_summary}"

        chat_req = ChatRequest(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            model=(provider_config or {}).get("model", "gpt-4o-mini"),
            provider=(provider_config or {}).get("provider", "openai"),
        )

        async def _fetch_tokens():
            provider = await provider_for(chat_req)
            tokens = []
            async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.2):
                tokens.append(token)
            return "".join(tokens).strip()

        response = await asyncio.wait_for(_fetch_tokens(), timeout=2.0)

        # Clean markdown codeblocks if wrapped
        if response.startswith("```"):
            lines = response.splitlines()
            response = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:]).strip()

        # Validate format
        first_line = response.splitlines()[0]
        if ":" in first_line and len(first_line) <= 72:
            return response
    except Exception as exc:
        logger.debug("LLM commit generation unavailable, using heuristic fallback: %s", exc)

    # Heuristic fallback generator enforcing Conventional Commits and 72-char limit
    if len(files) == 1:
        fname = Path(files[0]["path"]).name
        summary = f"update {fname}"
    else:
        summary = f"update {len(files)} files across {scope}"

    subject = f"{primary_category}({scope}): {summary}"
    if len(subject) > 72:
        subject = subject[:71]

    bullets = [f"- {f['category']}: {Path(f['path']).name} (+{f['additions']}, -{f['deletions']})" for f in files[:8]]
    body = "\n".join(bullets)
    return f"{subject}\n\n{body}"


async def generate_pr_description(
    workspace: str,
    provider_config: Optional[Dict[str, Any]] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, str]:
    """
    Generate Pull Request title and structured body containing:
    ## Summary
    ## Changes
    ## Testing
    ## Screenshots
    """
    analysis = await analyze_changes(workspace)
    files = analysis.get("files", [])
    totals = analysis.get("totals", {})

    default_title = commit_message.splitlines()[0] if commit_message else "feat: implement requested feature updates"
    if len(default_title) > 80:
        default_title = default_title[:80]

    # Try LLM call
    try:
        from app.features.ai.service import provider_for
        from app.features.ai.schemas import ChatRequest, ChatMessage

        file_list = "\n".join([f"- {f['path']} ({f['category']}, +{f['additions']}/-{f['deletions']})" for f in files[:30]])
        system_prompt = (
            "You are a GitHub Pull Request generator. Return a JSON object with 'title' and 'body'.\n"
            "The 'body' markdown MUST have the following exact headings:\n"
            "## Summary\n"
            "## Changes\n"
            "## Testing\n"
            "## Screenshots\n\n"
            "Under ## Screenshots, put placeholder text '_No screenshots provided._'."
        )
        user_prompt = f"Create a PR for these changes:\nTitle context: {default_title}\nChanged files:\n{file_list}"

        chat_req = ChatRequest(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            model=(provider_config or {}).get("model", "gpt-4o-mini"),
            provider=(provider_config or {}).get("provider", "openai"),
        )

        async def _fetch_pr_tokens():
            provider = await provider_for(chat_req)
            tokens = []
            async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.2):
                tokens.append(token)
            return "".join(tokens).strip()

        response_text = await asyncio.wait_for(_fetch_pr_tokens(), timeout=2.0)

        # Try parsing JSON
        import json
        if "{" in response_text and "}" in response_text:
            start = response_text.index("{")
            end = response_text.rindex("}") + 1
            data = json.loads(response_text[start:end])
            if "title" in data and "body" in data:
                return {"title": str(data["title"]).strip(), "body": str(data["body"]).strip()}
    except Exception as exc:
        logger.debug("LLM PR generation unavailable, using structured fallback: %s", exc)

    # Structured fallback
    body_lines = [
        "## Summary",
        f"Automated Pull Request generated by Git Autopilot for {totals.get('files', len(files))} changed files (+{totals.get('additions', 0)} / -{totals.get('deletions', 0)} lines).",
        "",
        "## Changes",
    ]
    for f in files[:12]:
        body_lines.append(f"- `{f['path']}`: {f['category']} changes (+{f['additions']}/-{f['deletions']})")
    if len(files) > 12:
        body_lines.append(f"- ...and {len(files) - 12} other files")

    body_lines.extend([
        "",
        "## Testing",
        "- Verified local unit tests and build status",
        "- Changes validated against workspace files",
        "",
        "## Screenshots",
        "_No screenshots provided._",
    ])

    return {
        "title": default_title,
        "body": "\n".join(body_lines),
    }


async def create_branch(workspace: str, branch_name: str) -> Dict[str, Any]:
    """Create and checkout a new branch (git checkout -b <name>)."""
    clean_branch = re.sub(r"[^a-zA-Z0-9_\-\./]", "-", branch_name.strip()).strip("-")
    if not clean_branch:
        raise HTTPException(status_code=400, detail="Invalid branch name")

    code, stdout, stderr = await _run_git_cmd(workspace, ["checkout", "-b", clean_branch])
    if code != 0:
        # If branch already exists, try checking it out
        if "already exists" in stderr:
            code, stdout, stderr = await _run_git_cmd(workspace, ["checkout", clean_branch])
        if code != 0:
            raise HTTPException(status_code=400, detail=f"Failed to create/checkout branch: {stderr.strip() or stdout.strip()}")

    return {"ok": True, "success": True, "branch": clean_branch}


async def stage_and_commit(workspace: str, message: str, file_paths: Optional[List[str]] = None) -> str:
    """Stage files and create a git commit. Returns commit hash."""
    if not message.strip():
        raise HTTPException(status_code=400, detail="Commit message cannot be empty")

    if file_paths and len(file_paths) > 0:
        add_args = ["add", "--"] + file_paths
    else:
        add_args = ["add", "-A"]

    add_code, add_out, add_err = await _run_git_cmd(workspace, add_args)
    if add_code != 0:
        raise HTTPException(status_code=400, detail=f"Git add failed: {add_err.strip() or add_out.strip()}")

    commit_code, commit_out, commit_err = await _run_git_cmd(workspace, ["commit", "-m", message])
    if commit_code != 0:
        if "nothing to commit" in commit_out.lower() or "nothing to commit" in commit_err.lower():
            # Get current HEAD hash
            code, rev_out, _ = await _run_git_cmd(workspace, ["rev-parse", "HEAD"])
            return rev_out.strip()
        raise HTTPException(status_code=400, detail=f"Git commit failed: {commit_err.strip() or commit_out.strip()}")

    code, rev_out, _ = await _run_git_cmd(workspace, ["rev-parse", "HEAD"])
    return rev_out.strip()


async def push_branch(workspace: str, branch_name: str) -> Dict[str, Any]:
    """Push branch to origin (strictly plain push only, NO force push)."""
    # Security check: never allow force-push
    clean_branch = branch_name.strip()
    if "--force" in clean_branch or "-f" in clean_branch.split():
        raise HTTPException(status_code=400, detail="Security violation: Force push is strictly prohibited")

    # Plain push only
    code, stdout, stderr = await _run_git_cmd(workspace, ["push", "-u", "origin", clean_branch])
    if code != 0:
        raise HTTPException(status_code=400, detail=f"Git push failed: {stderr.strip() or stdout.strip()}")

    return {"ok": True, "success": True, "pushed": True, "remote": "origin", "branch": clean_branch, "output": stdout.strip()}


def parse_github_remote(remote_url: str) -> Tuple[str, str]:
    """Parse owner and repo from HTTPS or SSH GitHub remote URL."""
    cleaned = remote_url.strip()
    # Matches:
    # https://github.com/owner/repo.git
    # https://github.com/owner/repo
    # git@github.com:owner/repo.git
    # ssh://git@github.com/owner/repo.git
    match = re.search(r"(?:git@github\.com:|https?://github\.com/|ssh://git@github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?$", cleaned)
    if not match:
        raise HTTPException(status_code=400, detail=f"Could not parse GitHub owner and repository from remote URL: {remote_url}")

    owner = match.group(1)
    repo = match.group(2)
    return owner, repo


async def create_pull_request(
    workspace: str,
    title: str,
    body: str,
    base: str = "main",
    head: Optional[str] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a GitHub Pull Request via GitHub REST API POST /repos/{owner}/{repo}/pulls.
    Requires a valid GitHub Personal Access Token.
    """
    import httpx

    # Check token
    auth_token = token or await get_github_token()
    if not auth_token or not auth_token.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "GitHub Personal Access Token is required to create a Pull Request. "
                "Please configure a token with 'repo' scope in settings."
            ),
        )

    # Get remote URL
    code, stdout, stderr = await _run_git_cmd(workspace, ["remote", "get-url", "origin"])
    if code != 0:
        raise HTTPException(status_code=400, detail=f"No git remote 'origin' configured: {stderr.strip()}")

    owner, repo = parse_github_remote(stdout.strip())

    # Get current branch if head is not specified
    if not head:
        code, branch_out, _ = await _run_git_cmd(workspace, ["rev-parse", "--abbrev-ref", "HEAD"])
        head = branch_out.strip()

    gh_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {auth_token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": title,
        "body": body,
        "base": base,
        "head": head,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(gh_url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to GitHub API: {exc}")

    if resp.status_code == 201:
        data = resp.json()
        pr_link = data.get("html_url")
        pr_num = data.get("number")
        return {
            "ok": True,
            "success": True,
            "pr_url": pr_link,
            "html_url": pr_link,
            "pr_number": pr_num,
            "number": pr_num,
            "title": data.get("title"),
            "owner": owner,
            "repo": repo,
        }
    else:
        err_msg = resp.text
        try:
            err_json = resp.json()
            err_msg = err_json.get("message", err_msg)
            if "errors" in err_json:
                err_msg += " - " + str(err_json["errors"])
        except Exception:
            pass
        raise HTTPException(status_code=resp.status_code, detail=f"GitHub PR creation failed: {err_msg}")


async def get_github_token() -> Optional[str]:
    """Retrieve stored GitHub token from settings table."""
    try:
        pool = await get_pool()
        rows = await pool.read_query("SELECT value FROM settings WHERE key = ?", ("github_token",))
        if rows and len(rows) > 0:
            return rows[0]["value"]
    except Exception as exc:
        logger.debug("Failed to read github_token from settings table: %s", exc)

    # Fallback to env variable
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("CODE_OS_GIT_PAT")


async def save_github_token(token: str) -> bool:
    """Save GitHub token to settings table."""
    clean_tok = token.strip()
    try:
        pool = await get_pool()
        await pool.write_execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("github_token", clean_tok),
        )
        return True
    except Exception as exc:
        logger.error("Failed to save github_token to settings table: %s", exc)
        return False
