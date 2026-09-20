from __future__ import annotations
"""
checkpoint_manager.py - Git-based surgical workspace checkpoint and undo management.
"""

import fnmatch
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any, List, Set, Tuple

logger = logging.getLogger(__name__)

from .symbol_index import invalidate_file

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
    """Restore and hash-verify each touched path from a pre-turn commit.

    Paths absent from the checkpoint are proposal-created paths and must be
    removed. This makes rollback a complete workspace transaction instead of
    only checking out files Git already knows about.
    """
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

    restored: list[str] = []
    failures: list[str] = []
    try:
        for rf in rel_paths:
            fp = ws_path / rf
            snapshot = subprocess.run(
                ["git", "show", f"{commit_hash}:{rf}"],
                cwd=str(ws_path),
                capture_output=True,
                timeout=15.0,
            )
            if snapshot.returncode == 0:
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_bytes(snapshot.stdout)
                if not fp.is_file() or hashlib.sha256(fp.read_bytes()).digest() != hashlib.sha256(snapshot.stdout).digest():
                    failures.append(f"{rf}: restored bytes do not match checkpoint")
                else:
                    restored.append(rf)
                    try:
                        invalidate_file(fp)
                    except Exception as inv_err:
                        logger.warning("Failed to invalidate %s after restore: %s", rf, inv_err)
                continue

            snapshot_error = snapshot.stderr.decode("utf-8", errors="replace")
            if "does not exist in" not in snapshot_error and "not in '" not in snapshot_error:
                failures.append(f"{rf}: unable to read checkpoint snapshot")
                continue

            # git show exits non-zero when this path did not exist in the
            # checkpoint. Remove the post-apply file and its empty parents.
            if fp.exists():
                if fp.is_dir():
                    failures.append(f"{rf}: expected file path is a directory")
                    continue
                fp.unlink()
            parent = fp.parent
            while parent != ws_path:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
            if fp.exists():
                failures.append(f"{rf}: created path still exists after rollback")
            else:
                restored.append(rf)
                try:
                    invalidate_file(fp)
                except Exception as inv_err:
                    logger.warning("Failed to invalidate %s after unlink: %s", rf, inv_err)
    except Exception as exc:
        return False, f"Undo operation failed: {exc}", restored

    if failures:
        return False, "Rollback verification failed: " + "; ".join(failures), restored
    return True, f"Successfully restored {len(restored)} path(s) to checkpoint {commit_hash[:7]}", restored


def _create_checkpoint(workspace: str, touched_files: list[str], turn_number: int) -> str:
    _, commit_hash, _ = _ensure_git_checkpoint(workspace, turn_number, touched_files)
    return commit_hash


def _restore_checkpoint(workspace: str, commit_hash: str, touched_files: list[str] | None = None) -> tuple[bool, str, list[str]]:
    return undo_turn_files(workspace, commit_hash, touched_files or [])
