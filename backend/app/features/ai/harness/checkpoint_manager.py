from __future__ import annotations
"""
checkpoint_manager.py - Git-based surgical workspace checkpoint and undo management.
"""

import fnmatch
import logging
import subprocess
from pathlib import Path
from typing import Any, List, Set, Tuple

logger = logging.getLogger(__name__)

SENSITIVE_FILE_PATTERNS = (
    ".env", ".env.*", "*.env",
    "*.pem", "id_rsa", "id_rsa*", "*.key",
    ".aws", ".aws/*", ".ssh", ".ssh/*",
    "credentials.json", "serviceAccountKey.json",
    "*.sqlite", "*.sqlite3", "*.db"
)


def _is_sensitive_filename(path_str: str) -> tuple[bool, str]:
    p = Path(path_str)
    name = p.name.lower()
    norm_path = str(p).replace("\\", "/").lower().lstrip("/")
    for pattern in SENSITIVE_FILE_PATTERNS:
        pat = pattern.lower()
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(norm_path, pat) or fnmatch.fnmatch(norm_path, f"*/{pat}"):
            return True, name
    return False, ""


def _ensure_git_checkpoint(
    workspace: str,
    turn_num: int,
    touched_files: list[str] | set[str] | None = None,
) -> tuple[bool, str, str]:
    """Ensure workspace is a git repo, and create a pre-turn checkpoint commit rony-turn-{N}-pre."""
    if not workspace:
        return False, "", "No workspace provided"
    
    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return False, "", "Workspace directory does not exist"

    if touched_files:
        for tf in touched_files:
            is_sens, matched_name = _is_sensitive_filename(str(tf))
            if is_sens:
                err_msg = f"Agent touched sensitive file: {matched_name}. Add it to .gitignore or exclude it from the workspace."
                logger.error("chat_harness: %s", err_msg)
                return False, "", err_msg

    new_repo_initialized = False

    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if res.returncode != 0:
            init_res = subprocess.run(
                ["git", "init"],
                cwd=str(ws_path),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if init_res.returncode == 0:
                new_repo_initialized = True
                gitignore = ws_path / ".gitignore"
                if not gitignore.exists():
                    gitignore_content = (
                        ".venv/\n"
                        "__pycache__/\n"
                        "node_modules/\n"
                        "*.pyc\n"
                        ".DS_Store\n"
                        ".code_os/\n"
                        ".env\n"
                        ".env.*\n"
                        "*.pem\n"
                        "id_rsa\n"
                        "id_rsa.pub\n"
                        ".aws/\n"
                        ".ssh/\n"
                        "*.key\n"
                        "credentials.json\n"
                        "serviceAccountKey.json\n"
                        "*.sqlite\n"
                        "*.sqlite3\n"
                        "*.db\n"
                    )
                    gitignore.write_text(gitignore_content, encoding="utf-8")
    except Exception as exc:
        logger.warning("chat_harness: git repo check/init failed: %s", exc)
        return False, "", str(exc)

    commit_hash = ""
    try:
        if touched_files:
            rel_paths = []
            for f in touched_files:
                p = Path(f)
                try:
                    rel = p.relative_to(ws_path)
                    rel_paths.append(str(rel).replace("\\", "/"))
                except ValueError:
                    rel_paths.append(str(f).replace("\\", "/"))
            
            if rel_paths:
                subprocess.run(
                    ["git", "add", "--"] + rel_paths,
                    cwd=str(ws_path),
                    capture_output=True,
                    text=True,
                    timeout=10.0,
                )

        commit_msg = f"rony-turn-{turn_num}-pre"
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", commit_msg],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        hash_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if hash_res.returncode == 0:
            commit_hash = hash_res.stdout.strip()
    except Exception as exc:
        logger.warning("chat_harness: git checkpoint commit failed: %s", exc)
        return new_repo_initialized, "", str(exc)

    return new_repo_initialized, commit_hash, ""


def undo_turn_files(workspace: str, commit_hash: str, touched_files: list[str]) -> tuple[bool, str, list[str]]:
    """Restores ONLY the agent-touched files from the pre-turn commit hash."""
    if not workspace or not commit_hash or not touched_files:
        return False, "Missing workspace, commit_hash, or touched_files", []
    
    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return False, f"Workspace not found: {workspace}", []

    rel_paths = []
    for f in touched_files:
        p = Path(f)
        try:
            rel = p.relative_to(ws_path)
            rel_paths.append(str(rel).replace("\\", "/"))
        except ValueError:
            rel_paths.append(f.replace("\\", "/"))

    if not rel_paths:
        return False, "No valid files to restore", []

    try:
        cmd = ["git", "checkout", commit_hash, "--"] + rel_paths
        res = subprocess.run(
            cmd,
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=15.0,
        )
        if res.returncode == 0:
            restored = []
            for rf in rel_paths:
                fp = ws_path / rf
                if fp.exists():
                    restored.append(rf)
            return True, f"Successfully restored {len(restored)} file(s) to checkpoint {commit_hash[:7]}", restored
        else:
            return False, f"Git checkout error: {res.stderr.strip()}", []
    except Exception as exc:
        return False, f"Undo operation failed: {exc}", []


def _create_checkpoint(workspace: str, touched_files: list[str], turn_number: int) -> str:
    _, commit_hash, _ = _ensure_git_checkpoint(workspace, turn_number, touched_files)
    return commit_hash


def _restore_checkpoint(workspace: str, commit_hash: str, touched_files: list[str] | None = None) -> tuple[bool, str, list[str]]:
    return undo_turn_files(workspace, commit_hash, touched_files or [])
