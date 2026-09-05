import os
import shutil
import logging
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import HTTPException
from ...core.errors import AppError, ErrorCode

from ...core.paths import IGNORED_DIRS, ensure_file, ensure_within_workspace, normalize_path
from .schemas import FileNode

logger = logging.getLogger(__name__)

INVALID_FILENAME_CHARS = {'*', '?', '"', '<', '>', '|', '\0'}

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rs": "rust",
    ".go": "go",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".bat": "bat",
    ".cmd": "bat",
    ".ps1": "powershell",
    ".php": "php",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".xml": "xml",
    ".svg": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "ini",
    ".ini": "ini",
    ".dockerfile": "dockerfile",
}


# ── LRU Directory Cache (Max 10,000 directories) ──────────────────────────────

class DirectoryCache:
    def __init__(self, max_size: int = 10000) -> None:
        self.max_size = max_size
        self._cache: OrderedDict[tuple[str, str], list[FileNode]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, workspace: str, path: str) -> list[FileNode] | None:
        key = (workspace, path)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def set(self, workspace: str, path: str, nodes: list[FileNode]) -> None:
        key = (workspace, path)
        with self._lock:
            self._cache[key] = nodes
            self._cache.move_to_end(key)
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def invalidate(self, workspace: str, path: str | None = None) -> None:
        with self._lock:
            if path is None:
                keys_to_del = [k for k in self._cache if k[0] == workspace]
                for k in keys_to_del:
                    del self._cache[k]
            else:
                key = (workspace, path)
                self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)


directory_cache = DirectoryCache(max_size=10000)


def invalidate_directory_cache(workspace: str, path: str | None = None) -> None:
    directory_cache.invalidate(workspace, path)


def _dir_has_children(dir_path: Path) -> bool:
    """Fast O(1) check if a directory has any non-ignored children."""
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                if entry.name not in IGNORED_DIRS and not entry.name.startswith(".DS_Store"):
                    return True
    except OSError:
        pass
    return False


def get_directory_children(workspace: str, dir_rel_path: str = "") -> list[FileNode]:
    """Return immediate children of dir_rel_path with hasChildren flag and size."""
    cached = directory_cache.get(workspace, dir_rel_path)
    if cached is not None:
        return cached

    target = ensure_within_workspace(workspace, dir_rel_path) if dir_rel_path else normalize_path(workspace)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    ws_norm = normalize_path(workspace)
    children: list[FileNode] = []
    try:
        with os.scandir(target) as it:
            entries = []
            for entry in it:
                if entry.name in IGNORED_DIRS or entry.name.startswith(".DS_Store"):
                    continue
                entries.append(entry)

        # Sort: directories first, then alphabetically
        entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

        for entry in entries:
            entry_path = Path(entry.path)
            try:
                rel = str(entry_path.relative_to(ws_norm)).replace("\\", "/")
            except ValueError:
                rel = str(entry_path).replace("\\", "/")

            if entry.is_dir():
                has_sub = _dir_has_children(entry_path)
                children.append(FileNode(
                    name=entry.name,
                    path=rel,
                    type="directory",
                    children=[],
                    hasChildren=has_sub,
                ))
            else:
                try:
                    f_size = entry.stat().st_size
                except OSError:
                    f_size = 0
                children.append(FileNode(
                    name=entry.name,
                    path=rel,
                    type="file",
                    children=[],
                    hasChildren=False,
                    size=f_size,
                ))
    except OSError as exc:
        logger.warning("Error reading directory %s: %s", target, exc)

    directory_cache.set(workspace, dir_rel_path, children)
    return children


def _node(path: Path, depth: int, max_depth: int, ws_path: Path | None = None) -> FileNode:
    if ws_path is None:
        ws_path = path

    try:
        rel = str(path.relative_to(ws_path)).replace("\\", "/") if path != ws_path else ""
    except ValueError:
        rel = str(path).replace("\\", "/")

    if path.is_dir():
        children: list[FileNode] = []
        has_sub = False
        if depth < max_depth:
            try:
                for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                    if child.name in IGNORED_DIRS or child.name.startswith(".DS_Store"):
                        continue
                    children.append(_node(child, depth + 1, max_depth, ws_path))
                has_sub = len(children) > 0
            except OSError:
                pass
        else:
            has_sub = _dir_has_children(path)

        return FileNode(
            name=path.name,
            path=str(path),
            type="directory",
            children=children,
            hasChildren=has_sub,
        )
    else:
        try:
            f_size = path.stat().st_size
        except OSError:
            f_size = 0
        return FileNode(
            name=path.name,
            path=str(path),
            type="file",
            children=[],
            hasChildren=False,
            size=f_size,
        )


def build_tree(workspace: str, max_depth: int = 4, path: str | None = None, depth: int | None = None) -> FileNode:
    logger.info("files.tree requested workspace=%s max_depth=%s path=%s depth=%s", workspace, max_depth, path, depth)
    workspace_path = normalize_path(workspace)
    if not workspace_path.is_dir():
        logger.error("files.tree workspace not found path=%s exists=%s", workspace_path, workspace_path.exists())
        raise AppError(ErrorCode.WORKSPACE_NOT_FOUND, "Workspace not found", status_code=404)

    if depth == 1 or path is not None:
        rel_target = path.strip("/") if path else ""
        target_full = ensure_within_workspace(workspace, rel_target) if rel_target else workspace_path
        children = get_directory_children(workspace, rel_target)
        node_name = target_full.name if target_full != workspace_path else ""
        return FileNode(
            name=node_name,
            path=str(target_full),
            type="directory",
            children=children,
            hasChildren=len(children) > 0,
        )

    root = _node(workspace_path, 0, max_depth, workspace_path)
    logger.info("files.tree loaded workspace=%s child_count=%s", workspace_path, len(root.children))
    return root


def read_file(workspace: str, path: str) -> tuple[str, str]:
    logger.info("files.read workspace=%s path=%s", workspace, path)
    target = ensure_within_workspace(workspace, path)
    ensure_file(target)
    if target.stat().st_size > 2_000_000:
        raise HTTPException(status_code=413, detail="File is too large to open")
    return target.read_text(encoding="utf-8", errors="replace"), LANGUAGE_BY_SUFFIX.get(target.suffix.lower(), "plaintext")


def create_entry(workspace: str, path: str, entry_type: str) -> Path:
    if not path or not str(path).strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    target = ensure_within_workspace(workspace, path)
    if not target.name or target.name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid name")
    if any(c in INVALID_FILENAME_CHARS for c in target.name) or ":" in target.name:
        raise HTTPException(status_code=400, detail=f"Invalid characters in filename: {target.name}")
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Path already exists: {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if entry_type == "directory":
        target.mkdir()
    elif entry_type == "file":
        target.write_text("", encoding="utf-8")
    else:
        raise HTTPException(status_code=400, detail="type must be file or directory")
    
    directory_cache.invalidate(workspace)
    return target


def delete_entry(workspace: str, path: str) -> None:
    target = ensure_within_workspace(workspace, path)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.is_file():
        target.unlink()
    else:
        raise HTTPException(status_code=404, detail="Path not found")
    directory_cache.invalidate(workspace)


def rename_entry(workspace: str, path: str, new_name: str) -> Path:
    if any(part in new_name for part in ("/", "\\")) or new_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid name")
    source = ensure_within_workspace(workspace, path)
    destination = source.with_name(new_name)
    ensure_within_workspace(workspace, str(destination))
    if destination.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    source.rename(destination)
    directory_cache.invalidate(workspace)
    return destination


def move_entry(workspace: str, source: str, destination: str) -> Path:
    source_path = ensure_within_workspace(workspace, source)
    destination_path = ensure_within_workspace(workspace, destination)
    if destination_path.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(destination_path))
    directory_cache.invalidate(workspace)
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
    directory_cache.invalidate(workspace)
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
    directory_cache.invalidate(workspace)


def reveal_entry(workspace: str, path: str) -> None:
    import platform
    import subprocess
    logger.info("files.reveal workspace=%s path=%s", workspace, path)
    target = ensure_within_workspace(workspace, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    
    current_os = platform.system()
    try:
        if current_os == "Windows":
            if target.is_file():
                subprocess.Popen(["explorer", f"/select,{str(target)}"])
            else:
                subprocess.Popen(["explorer", str(target)])
        elif current_os == "Darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            if target.is_dir():
                subprocess.Popen(["xdg-open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target.parent)])
    except Exception as e:
        logger.error("files.reveal failed for path=%s: %s", target, e)
        raise HTTPException(status_code=500, detail=f"Failed to open system file explorer: {e}")
