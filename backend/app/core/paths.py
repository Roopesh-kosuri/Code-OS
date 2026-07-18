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


def normalize_path(raw_path: str) -> Path:
    try:
        return Path(raw_path).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Invalid path") from exc


def ensure_within_workspace(workspace: str, target: str) -> Path:
    workspace_path = normalize_path(workspace)
    target_p = Path(target)
    if not target_p.is_absolute():
        target_path = normalize_path(str(Path(workspace) / target_p))
    else:
        target_path = normalize_path(target)
        
    if workspace_path != target_path and workspace_path not in target_path.parents:
        raise HTTPException(status_code=403, detail="Path is outside workspace")
    return target_path


def ensure_directory(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")


def ensure_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
