import shutil
import logging
from pathlib import Path

from fastapi import HTTPException

from backend.app.core.paths import IGNORED_DIRS, ensure_file, ensure_within_workspace, normalize_path
from backend.app.features.files.schemas import FileNode

logger = logging.getLogger(__name__)

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".yml": "yaml",
    ".yaml": "yaml",
}


def _node(path: Path, depth: int, max_depth: int) -> FileNode:
    if path.is_dir():
        children: list[FileNode] = []
        if depth < max_depth:
            for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                if child.name in IGNORED_DIRS or child.name.startswith(".DS_Store"):
                    continue
                children.append(_node(child, depth + 1, max_depth))
        return FileNode(name=path.name, path=str(path), type="directory", children=children)
    return FileNode(name=path.name, path=str(path), type="file")


def build_tree(workspace: str, max_depth: int = 4) -> FileNode:
    logger.info("files.tree requested workspace=%s max_depth=%s", workspace, max_depth)
    workspace_path = normalize_path(workspace)
    if not workspace_path.is_dir():
        logger.error("files.tree workspace not found path=%s exists=%s", workspace_path, workspace_path.exists())
        raise HTTPException(status_code=404, detail="Workspace not found")
    root = _node(workspace_path, 0, max_depth)
    logger.info("files.tree loaded workspace=%s child_count=%s", workspace_path, len(root.children))
    return root


def read_file(workspace: str, path: str) -> tuple[str, str]:
    logger.info("files.read workspace=%s path=%s", workspace, path)
    target = ensure_within_workspace(workspace, path)
    ensure_file(target)
    if target.stat().st_size > 2_000_000:
        raise HTTPException(status_code=413, detail="File is too large to open")
    return target.read_text(encoding="utf-8", errors="replace"), LANGUAGE_BY_SUFFIX.get(target.suffix.lower(), "plaintext")


def create_entry(workspace: str, path: str, entry_type: str) -> None:
    target = ensure_within_workspace(workspace, path)
    if target.exists():
        raise HTTPException(status_code=409, detail="Path already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    if entry_type == "directory":
        target.mkdir()
    elif entry_type == "file":
        target.write_text("", encoding="utf-8")
    else:
        raise HTTPException(status_code=400, detail="type must be file or directory")


def delete_entry(workspace: str, path: str) -> None:
    target = ensure_within_workspace(workspace, path)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.is_file():
        target.unlink()
    else:
        raise HTTPException(status_code=404, detail="Path not found")


def rename_entry(workspace: str, path: str, new_name: str) -> Path:
    if any(part in new_name for part in ("/", "\\")) or new_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid name")
    source = ensure_within_workspace(workspace, path)
    destination = source.with_name(new_name)
    ensure_within_workspace(workspace, str(destination))
    if destination.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    source.rename(destination)
    return destination


def move_entry(workspace: str, source: str, destination: str) -> Path:
    source_path = ensure_within_workspace(workspace, source)
    destination_path = ensure_within_workspace(workspace, destination)
    if destination_path.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(destination_path))
    return destination_path


def duplicate_entry(workspace: str, path: str, destination: str | None = None) -> Path:
    source = ensure_within_workspace(workspace, path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    target = ensure_within_workspace(workspace, destination) if destination else _next_copy_path(source)
    if target.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return target


def _next_copy_path(source: Path) -> Path:
    stem = source.stem if source.is_file() else source.name
    suffix = source.suffix if source.is_file() else ""
    for index in range(1, 1000):
        label = " copy" if index == 1 else f" copy {index}"
        candidate = source.with_name(f"{stem}{label}{suffix}")
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail="Unable to create duplicate path")


def write_file(workspace: str, path: str, content: str) -> None:
    logger.info("files.write workspace=%s path=%s bytes=%s", workspace, path, len(content.encode("utf-8")))
    target = ensure_within_workspace(workspace, path)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot write to a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
