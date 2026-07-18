import asyncio
import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.paths import IGNORED_DIRS, normalize_path
from backend.app.db.database import get_connection
from backend.app.features.indexing.language import detect_language
from backend.app.features.indexing.parsers import ParsedSymbol, parse_package_json, parse_requirements, parse_source

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 1_500_000


@dataclass
class FileIndexResult:
    path: str
    relative_path: str
    language: str
    size: int
    mtime_ns: int
    content_hash: str
    imports: list[str]
    symbols: list[ParsedSymbol]
    changed: bool


@dataclass
class WorkspaceIndexResult:
    workspace: str
    files: list[FileIndexResult] = field(default_factory=list)
    dependencies: list[tuple[str, str | None, str]] = field(default_factory=list)
    folders: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    project_type: str = "unknown"
    frameworks: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    language_summary: dict[str, int] = field(default_factory=dict)
    changed_files: int = 0


class RepositoryIndexManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def schedule(self, workspace: str, reason: str = "workspace-open") -> None:
        workspace_path = str(normalize_path(workspace))
        async with self._lock:
            existing = self._tasks.get(workspace_path)
            if existing and not existing.done():
                logger.info("index.schedule skipped workspace=%s reason=%s existing_task=true", workspace_path, reason)
                return
            await _mark_status(workspace_path, "queued", f"Queued: {reason}")
            task = asyncio.create_task(self._run(workspace_path, reason), name=f"index:{workspace_path}")
            self._tasks[workspace_path] = task
            logger.info("index.schedule workspace=%s reason=%s", workspace_path, reason)

    async def schedule_file_change(self, workspace: str, changed_path: str) -> None:
        logger.info("index.file_change workspace=%s changed_path=%s", workspace, changed_path)
        await self.schedule(workspace, reason=f"file-change:{changed_path}")

    async def _run(self, workspace: str, reason: str) -> None:
        try:
            await _mark_status(workspace, "indexing", f"Indexing: {reason}", started=True)
            previous = await _load_previous_file_state(workspace)
            result = await asyncio.to_thread(_scan_workspace, workspace, previous)
            await _store_index(result)
            await _mark_status(
                workspace,
                "ready",
                "Index ready",
                completed=True,
                total_files=len(result.files),
                indexed_files=len(result.files),
                changed_files=result.changed_files,
                project_type=result.project_type,
                language_summary=result.language_summary,
                frameworks=result.frameworks,
                entry_points=result.entry_points,
            )
            logger.info("index.ready workspace=%s files=%s changed=%s", workspace, len(result.files), result.changed_files)
        except Exception as exc:
            logger.exception("index.failed workspace=%s", workspace)
            await _mark_status(workspace, "failed", str(exc), completed=True)


index_manager = RepositoryIndexManager()


def _scan_workspace(workspace: str, previous: dict[str, tuple[int, int, str]]) -> WorkspaceIndexResult:
    root = normalize_path(workspace)
    result = WorkspaceIndexResult(workspace=str(root))
    language_counter: Counter[str] = Counter()
    folder_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    all_files = []

    for path in root.rglob("*"):
        if _is_ignored(path):
            continue
        if path.is_dir():
            rel = _relative(root, path)
            folder_counts[str(path)][1] += len([child for child in _safe_iterdir(path) if child.is_dir() and not _is_ignored(child)])
            result.folders[str(path)] = (rel, folder_counts[str(path)][0], folder_counts[str(path)][1])
            continue
        if not path.is_file():
            continue
        parent = str(path.parent)
        folder_counts[parent][0] += 1
        all_files.append(path)

    dependencies = _detect_dependencies(root)
    result.dependencies.extend(dependencies)
    result.project_type, result.frameworks = _detect_project(root, dependencies)
    result.entry_points = _detect_entry_points(root)

    for path in all_files:
        language = detect_language(path)
        if not language:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > MAX_FILE_BYTES:
            continue
        previous_state = previous.get(str(path))
        if previous_state and previous_state[0] == stat.st_mtime_ns and previous_state[1] == stat.st_size:
            content_hash = previous_state[2]
            changed = False
        else:
            content_hash = _hash_file(path)
            changed = previous_state != (stat.st_mtime_ns, stat.st_size, content_hash)
        if changed:
            result.changed_files += 1
        parsed = None
        if changed:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            parsed = parse_source(path, language, content)
        result.files.append(
            FileIndexResult(
                path=str(path),
                relative_path=_relative(root, path),
                language=language,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                content_hash=content_hash,
                imports=sorted(set(parsed.imports)) if parsed else [],
                symbols=parsed.symbols if parsed else [],
                changed=changed,
            )
        )
        language_counter[language] += 1

    for folder_path, (file_count, folder_count) in folder_counts.items():
        result.folders[folder_path] = (_relative(root, Path(folder_path)), file_count, folder_count)
    result.language_summary = dict(language_counter)
    return result


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 256), b""):
                hasher.update(chunk)
    except OSError:
        return ""
    return hasher.hexdigest()


def _detect_dependencies(root: Path) -> list[tuple[str, str | None, str]]:
    dependencies: list[tuple[str, str | None, str]] = []
    package_json = root / "package.json"
    if package_json.exists():
        dependencies.extend(parse_package_json(package_json))
    for req in root.glob("requirements*.txt"):
        dependencies.extend(parse_requirements(req))
    return dependencies


def _detect_project(root: Path, dependencies: list[tuple[str, str | None, str]]) -> tuple[str, list[str]]:
    dep_names = {name.lower() for name, _, _ in dependencies}
    frameworks: set[str] = set()
    project_type = "unknown"
    if (root / "package.json").exists():
        project_type = "node"
        for name in dep_names:
            if name in {"react", "vue", "svelte", "next", "vite", "express", "fastify", "electron"}:
                frameworks.add(name)
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        project_type = "python" if project_type == "unknown" else f"{project_type}+python"
        for name in dep_names:
            if name in {"fastapi", "flask", "django", "pytest"}:
                frameworks.add(name)
    if (root / "CMakeLists.txt").exists():
        project_type = "cmake" if project_type == "unknown" else f"{project_type}+cmake"
    if (root / "pom.xml").exists() or (root / "build.gradle").exists():
        project_type = "java" if project_type == "unknown" else f"{project_type}+java"
    return project_type, sorted(frameworks)


def _detect_entry_points(root: Path) -> list[str]:
    candidates = [
        "src/main.tsx",
        "src/main.ts",
        "src/main.jsx",
        "src/main.js",
        "src/App.tsx",
        "main.py",
        "app.py",
        "backend/app/main.py",
        "src/main.c",
        "src/main.cpp",
        "src/main/java",
    ]
    return [candidate for candidate in candidates if (root / candidate).exists()]


async def _load_previous_file_state(workspace: str) -> dict[str, tuple[int, int, str]]:
    db = await get_connection()
    try:
        rows = await db.execute_fetchall("SELECT path, mtime_ns, size, content_hash FROM repo_index_files WHERE workspace = ?", (workspace,))
        return {row["path"]: (row["mtime_ns"], row["size"], row["content_hash"]) for row in rows}
    finally:
        await db.close()


async def _store_index(result: WorkspaceIndexResult) -> None:
    db = await get_connection()
    try:
        current_paths = {item.path for item in result.files}
        existing_rows = await db.execute_fetchall("SELECT path FROM repo_index_files WHERE workspace = ?", (result.workspace,))
        removed_paths = [row["path"] for row in existing_rows if row["path"] not in current_paths]
        await db.executemany("DELETE FROM repo_index_files WHERE workspace = ? AND path = ?", [(result.workspace, path) for path in removed_paths])
        await db.executemany("DELETE FROM repo_symbols WHERE workspace = ? AND path = ?", [(result.workspace, path) for path in removed_paths])
        await db.executemany("DELETE FROM repo_import_edges WHERE workspace = ? AND source_path = ?", [(result.workspace, path) for path in removed_paths])
        await db.execute("DELETE FROM repo_dependencies WHERE workspace = ?", (result.workspace,))
        await db.execute("DELETE FROM repo_folders WHERE workspace = ?", (result.workspace,))

        await db.executemany(
            """
            INSERT INTO repo_index_files(workspace, path, relative_path, language, size, mtime_ns, content_hash, symbol_count, imports_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace, path) DO UPDATE SET
                relative_path = excluded.relative_path,
                language = excluded.language,
                size = excluded.size,
                mtime_ns = excluded.mtime_ns,
                content_hash = excluded.content_hash,
                symbol_count = excluded.symbol_count,
                imports_json = excluded.imports_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    result.workspace,
                    item.path,
                    item.relative_path,
                    item.language,
                    item.size,
                    item.mtime_ns,
                    item.content_hash,
                    len(item.symbols),
                    json.dumps(item.imports),
                )
                for item in result.files
                if item.changed
            ],
        )
        symbol_rows = []
        edge_rows = []
        for item in result.files:
            if not item.changed:
                continue
            await db.execute("DELETE FROM repo_symbols WHERE workspace = ? AND path = ?", (result.workspace, item.path))
            await db.execute("DELETE FROM repo_import_edges WHERE workspace = ? AND source_path = ?", (result.workspace, item.path))
            for symbol in item.symbols:
                symbol_rows.append((result.workspace, item.path, symbol.name, symbol.kind, item.language, symbol.line, symbol.column, symbol.signature, symbol.parent))
            for module in item.imports:
                edge_rows.append((result.workspace, item.path, module, _resolve_import(result, item.path, module), "import"))
        await db.executemany(
            """
            INSERT INTO repo_symbols(workspace, path, name, kind, language, line, column, signature, parent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            symbol_rows,
        )
        await db.executemany(
            "INSERT OR REPLACE INTO repo_import_edges(workspace, source_path, module, target_path, kind) VALUES (?, ?, ?, ?, ?)",
            edge_rows,
        )
        await db.executemany(
            "INSERT OR REPLACE INTO repo_dependencies(workspace, name, version, source) VALUES (?, ?, ?, ?)",
            [(result.workspace, name, version, source) for name, version, source in result.dependencies],
        )
        await db.executemany(
            "INSERT OR REPLACE INTO repo_folders(workspace, path, relative_path, file_count, folder_count) VALUES (?, ?, ?, ?, ?)",
            [(result.workspace, path, rel, file_count, folder_count) for path, (rel, file_count, folder_count) in result.folders.items()],
        )
        await db.commit()
    finally:
        await db.close()


def _resolve_import(result: WorkspaceIndexResult, source_path: str, module: str) -> str | None:
    if module.startswith("."):
        base = Path(source_path).parent
        candidate = (base / module.replace(".", "/")).resolve()
    else:
        candidate = Path(result.workspace) / module.replace(".", "/")
    known_paths = {Path(item.path) for item in result.files}
    for suffix in ("", ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".c", ".cpp", ".h", ".hpp"):
        path = Path(f"{candidate}{suffix}")
        if path in known_paths:
            return str(path)
    return None


async def _mark_status(
    workspace: str,
    status: str,
    message: str,
    *,
    started: bool = False,
    completed: bool = False,
    total_files: int | None = None,
    indexed_files: int | None = None,
    changed_files: int | None = None,
    project_type: str | None = None,
    language_summary: dict[str, int] | None = None,
    frameworks: list[str] | None = None,
    entry_points: list[str] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db = await get_connection()
    try:
        await db.execute(
            """
            INSERT INTO repo_index_status(workspace, status, message, started_at, completed_at, total_files, indexed_files, changed_files, project_type, language_summary, frameworks, entry_points)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace) DO UPDATE SET
                status = excluded.status,
                message = excluded.message,
                started_at = COALESCE(excluded.started_at, repo_index_status.started_at),
                completed_at = COALESCE(excluded.completed_at, repo_index_status.completed_at),
                total_files = excluded.total_files,
                indexed_files = excluded.indexed_files,
                changed_files = excluded.changed_files,
                project_type = excluded.project_type,
                language_summary = excluded.language_summary,
                frameworks = excluded.frameworks,
                entry_points = excluded.entry_points
            """,
            (
                workspace,
                status,
                message,
                now if started else None,
                now if completed else None,
                total_files or 0,
                indexed_files or 0,
                changed_files or 0,
                project_type or "unknown",
                json.dumps(language_summary or {}),
                json.dumps(frameworks or []),
                json.dumps(entry_points or []),
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_index_status(workspace: str) -> dict[str, Any] | None:
    normalized = str(normalize_path(workspace))
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT * FROM repo_index_status WHERE workspace = ?", (normalized,))
        row = await cursor.fetchone()
        if not row:
            return None
        return _status_from_row(row)
    finally:
        await db.close()


async def get_index_summary(workspace: str, limit: int = 50) -> dict[str, Any]:
    normalized = str(normalize_path(workspace))
    db = await get_connection()
    try:
        status_cursor = await db.execute("SELECT * FROM repo_index_status WHERE workspace = ?", (normalized,))
        status_row = await status_cursor.fetchone()
        files = await db.execute_fetchall(
            "SELECT * FROM repo_index_files WHERE workspace = ? ORDER BY relative_path LIMIT ?",
            (normalized, limit),
        )
        symbols = await db.execute_fetchall(
            "SELECT path, name, kind, language, line, column, signature, parent FROM repo_symbols WHERE workspace = ? ORDER BY path, line LIMIT ?",
            (normalized, limit),
        )
        dependencies = await db.execute_fetchall(
            "SELECT name, version, source FROM repo_dependencies WHERE workspace = ? ORDER BY source, name LIMIT ?",
            (normalized, limit),
        )
        return {
            "status": _status_from_row(status_row) if status_row else None,
            "files": [
                {
                    "path": row["path"],
                    "relative_path": row["relative_path"],
                    "language": row["language"],
                    "size": row["size"],
                    "symbol_count": row["symbol_count"],
                    "imports": json.loads(row["imports_json"]),
                }
                for row in files
            ],
            "symbols": [dict(row) for row in symbols],
            "dependencies": [dict(row) for row in dependencies],
        }
    finally:
        await db.close()


def _status_from_row(row: Any) -> dict[str, Any]:
    return {
        "workspace": row["workspace"],
        "status": row["status"],
        "message": row["message"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "total_files": row["total_files"],
        "indexed_files": row["indexed_files"],
        "changed_files": row["changed_files"],
        "project_type": row["project_type"],
        "language_summary": json.loads(row["language_summary"]),
        "frameworks": json.loads(row["frameworks"]),
        "entry_points": json.loads(row["entry_points"]),
    }
