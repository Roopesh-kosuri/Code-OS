import asyncio
import logging
from pathlib import Path
from threading import Lock

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ...core.paths import IGNORED_DIRS
from ..indexing.service import index_manager

logger = logging.getLogger(__name__)


class LoggingEventHandler(FileSystemEventHandler):
    def __init__(self, workspace: str, loop: asyncio.AbstractEventLoop | None) -> None:
        self.workspace = workspace
        self.loop = loop

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path).replace("\\", "/")
        parts = [p.lower() for p in Path(src).parts]
        lowered_ignored = {d.lower() for d in IGNORED_DIRS} | {
            "resources", "site-packages", "lib", "venv", ".venv", "env",
            ".code_os", "uploads", ".git", "node_modules", ".pytest_cache",
            "dist", "release", "build", "coverage", ".next", ".turbo",
        }
        if (
            any(part in lowered_ignored for part in parts)
            or ".code_os" in src
            or "/uploads/" in src
            or src.endswith("/uploads")
            or "/resources/" in src
            or "/site-packages/" in src
        ):
            return

        logger.info("workspace file event: %s %s", event.event_type, event.src_path)
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(index_manager.schedule_file_change(self.workspace, event.src_path), self.loop)
            try:
                from ..ai.rag import schedule_rag_reindex
                schedule_rag_reindex(self.workspace, event.src_path, event.event_type, loop=self.loop)
            except Exception:
                pass


class WorkspaceWatcher:
    def __init__(self) -> None:
        self._observer = Observer()
        self._observer.daemon = True
        self._watched: set[str] = set()
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def watch(self, path: Path) -> None:
        resolved = str(path)
        with self._lock:
            if resolved in self._watched:
                logger.info("workspace.watch already active path=%s", resolved)
                return
            if not self._observer.is_alive():
                self._observer.daemon = True
                self._observer.start()
            self._observer.schedule(LoggingEventHandler(resolved, self._loop), resolved, recursive=True)
            self._watched.add(resolved)
            logger.info("workspace.watch started path=%s watched_count=%s", resolved, len(self._watched))
            if self._loop and self._loop.is_running():
                try:
                    from ..ai.rag import reconcile_workspace_index
                    asyncio.run_coroutine_threadsafe(reconcile_workspace_index(resolved, loop=self._loop), self._loop)
                except Exception as exc:
                    logger.debug("workspace.watch: failed to trigger initial RAG reconciliation: %s", exc)

    def stop(self) -> None:
        with self._lock:
            if self._observer.is_alive():
                try:
                    logger.info("Stopping workspace file watcher observer...")
                except Exception:
                    pass
                self._observer.stop()
                self._observer.join(timeout=1.0)
            self._watched.clear()
            self._observer = Observer()
            self._observer.daemon = True
            try:
                logger.info("Workspace file watcher stopped.")
            except Exception:
                pass

    def status(self) -> dict[str, object]:
        return {"running": self._observer.is_alive(), "watched": sorted(self._watched)}


watcher = WorkspaceWatcher()
