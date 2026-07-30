"""
core/paths.py — Path normalisation and workspace boundary enforcement.

Security rules enforced here:
  * Client-supplied paths are NEVER tilde-expanded (.expanduser() is not called).
  * All paths are resolved with Path.resolve() which follows symlinks; the
    resolved path is then checked to be inside the workspace root, so a symlink
    inside the workspace that points outside is rejected.
  * ".." components are removed by resolve() so path traversal is impossible.
  * The trust-check supports subdirectories: trusting /proj covers /proj/src.
"""

from pathlib import Path

from fastapi import HTTPException

IGNORED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "dist-electron",
    ".next",
    ".turbo",
}


def _reject_tilde(raw_path: str) -> None:
    """Raise 400 if the raw client-supplied path starts with a tilde."""
    stripped = raw_path.strip()
    if stripped.startswith("~"):
        raise HTTPException(status_code=400, detail="Tilde expansion is not allowed in paths")


def normalize_workspace(raw_path: str) -> Path:
    """
    Normalise a *workspace root* path supplied at startup / trust-time.
    Workspace paths come from the local settings file (not from remote clients)
    so tilde expansion is intentionally allowed here.
    """
    try:
        return Path(raw_path).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path") from exc


def normalize_path(raw_path: str) -> Path:
    """
    Normalise a client-supplied path WITHOUT tilde expansion.
    Use this for any path that originates from a network request.
    """
    _reject_tilde(raw_path)
    try:
        return Path(raw_path).resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Invalid path") from exc


def ensure_within_workspace(workspace: str, target: str) -> Path:
    """
    Resolve *target* and verify it is inside *workspace*.

    Both symlinks and ".." traversal are neutralised by Path.resolve().
    If the resolved target escapes the workspace root a 403 is raised.
    """
    _reject_tilde(target)
    workspace_path = normalize_workspace(workspace)

    target_p = Path(target)
    if not target_p.is_absolute():
        # Join relative path to workspace, then resolve (handles .. and symlinks)
        target_path = (workspace_path / target_p).resolve()
    else:
        target_path = target_p.resolve()

    # Boundary check: target must equal workspace root or be a descendant
    try:
        target_path.relative_to(workspace_path)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path is outside workspace")

    return target_path


def is_within_workspace(workspace_path: Path, candidate: Path) -> bool:
    """
    Return True if *candidate* (already resolved) is equal to or a descendant
    of *workspace_path* (already resolved).  No filesystem access.
    """
    try:
        candidate.relative_to(workspace_path)
        return True
    except ValueError:
        return False


def ensure_directory(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")


def ensure_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
