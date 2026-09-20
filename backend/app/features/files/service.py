import os
import re
import shutil
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from ...core.errors import AppError, ErrorCode

from ...core.paths import IGNORED_DIRS, ensure_file, ensure_within_workspace, normalize_path, normalize_workspace
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


def _on_pipeline_invalidate(workspace: str, applied_paths: list[str]) -> None:
    directory_cache.invalidate(workspace)


from ..ai.harness.mutation_pipeline import Mutation, MutationKind, apply_mutations, register_invalidation_hook
register_invalidation_hook(_on_pipeline_invalidate)


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
    raw = target.read_bytes().decode("utf-8", errors="replace")
    return _normalize_eol(raw), LANGUAGE_BY_SUFFIX.get(target.suffix.lower(), "plaintext")


def _raise_rejection(res: Any) -> None:
    rej = res.rejection
    reason = rej.reason_text if rej else "Operation failed"
    code = rej.code if rej else ""
    if code in ("path_outside_workspace", "symlink_escape", "security_error", "protected_path"):
        raise HTTPException(status_code=403, detail=reason)
    if code in ("destination_exists",):
        raise HTTPException(status_code=409, detail=reason)
    if code in ("path_not_found",):
        raise HTTPException(status_code=404, detail=reason)
    raise HTTPException(status_code=400, detail=reason)


def create_entry(workspace: str, path: str, entry_type: str) -> Path:
    if not path or not str(path).strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    target = ensure_within_workspace(workspace, path)
    if not target.name or target.name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid name")
    if any(c in INVALID_FILENAME_CHARS for c in target.name) or ":" in target.name:
        raise HTTPException(status_code=400, detail=f"Invalid characters in filename: {target.name}")
    if entry_type not in ("directory", "file"):
        raise HTTPException(status_code=400, detail="type must be file or directory")
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Path already exists: {target.name}")
    
    ws_norm = normalize_workspace(workspace)
    try:
        rel = str(target.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel = str(target).replace("\\", "/")

    if entry_type == "directory":
        mut = Mutation(kind=MutationKind.MKDIR, path=rel)
    else:
        mut = Mutation(kind=MutationKind.CREATE, path=rel, new_content="")
    
    res = apply_mutations(workspace, [mut], mode="FS_OP")
    if not res.success:
        _raise_rejection(res)
    return target


def delete_entry(workspace: str, path: str) -> None:
    target = ensure_within_workspace(workspace, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    
    ws_norm = normalize_workspace(workspace)
    try:
        rel = str(target.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel = str(target).replace("\\", "/")

    mut = Mutation(kind=MutationKind.DELETE, path=rel)
    res = apply_mutations(workspace, [mut], mode="FS_OP")
    if not res.success:
        _raise_rejection(res)


def rename_entry(workspace: str, path: str, new_name: str) -> Path:
    if any(part in new_name for part in ("/", "\\")) or new_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid name")
    source = ensure_within_workspace(workspace, path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    destination = source.with_name(new_name)
    ensure_within_workspace(workspace, str(destination))
    if destination.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    
    ws_norm = normalize_workspace(workspace)
    try:
        rel_src = str(source.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel_src = str(source).replace("\\", "/")
    try:
        rel_dst = str(destination.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel_dst = str(destination).replace("\\", "/")

    mut = Mutation(kind=MutationKind.RENAME_MOVE, old_path=rel_src, new_path=rel_dst, overwrite=False)
    res = apply_mutations(workspace, [mut], mode="FS_OP")
    if not res.success:
        _raise_rejection(res)
    return destination


def move_entry(workspace: str, source: str, destination: str) -> Path:
    source_path = ensure_within_workspace(workspace, source)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    destination_path = ensure_within_workspace(workspace, destination)
    if destination_path.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    
    ws_norm = normalize_workspace(workspace)
    try:
        rel_src = str(source_path.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel_src = str(source_path).replace("\\", "/")
    try:
        rel_dst = str(destination_path.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel_dst = str(destination_path).replace("\\", "/")

    mut = Mutation(kind=MutationKind.RENAME_MOVE, old_path=rel_src, new_path=rel_dst, overwrite=False)
    res = apply_mutations(workspace, [mut], mode="FS_OP")
    if not res.success:
        _raise_rejection(res)
    return destination_path


def duplicate_entry(workspace: str, path: str, destination: str | None = None) -> Path:
    source = ensure_within_workspace(workspace, path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    target = ensure_within_workspace(workspace, destination) if destination else _next_copy_path(source)
    if target.exists():
        raise HTTPException(status_code=409, detail="Destination exists")
    
    ws_norm = normalize_workspace(workspace)
    try:
        rel_src = str(source.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel_src = str(source).replace("\\", "/")
    try:
        rel_dst = str(target.relative_to(ws_norm)).replace("\\", "/")
    except ValueError:
        rel_dst = str(target).replace("\\", "/")

    mut = Mutation(kind=MutationKind.COPY, src_path=rel_src, dst_path=rel_dst)
    res = apply_mutations(workspace, [mut], mode="FS_OP")
    if not res.success:
        _raise_rejection(res)
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


def _normalize_eol(content: str) -> str:
    """Normalize CRLF (\\r\\n), bare CR (\\r), and corrupted (\\r\\r\\n) to LF (\\n).

    On Windows, Path.write_text() uses text mode and converts every \\n to \\r\\n.
    If *content* already contains \\r\\n (e.g. from an LLM or copy-paste), text mode
    produces \\r\\r\\n on disk. A subsequent read_text() in universal-newlines mode turns
    each \\r\\r\\n into \\n\\n — two newlines per original line — which Monaco
    renders as a blank line between every line of code.

    Collapsing any sequence of \\r followed by \\n into a single \\n, and replacing
    any remaining bare \\r with \\n, ensures clean LF content on both read and write.
    """
    if not content:
        return ""
    content = re.sub(r"\r+\n", "\n", content)
    return content.replace("\r", "\n")


def write_file(workspace: str, path: str, content: str) -> None:
    logger.info("files.write workspace=%s path=%s bytes=%s", workspace, path, len(content.encode("utf-8")))
    target = ensure_within_workspace(workspace, path)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot write to a directory")
    
    # Route through mutation pipeline in USER_SAVE mode (skips syntax gate, enforces safety + atomic write + invalidation)
    mut = Mutation(kind=MutationKind.WRITE_FULL, path=path, new_content=_normalize_eol(content))
    res = apply_mutations(workspace, [mut], mode="USER_SAVE")
    if not res.success:
        _raise_rejection(res)


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
