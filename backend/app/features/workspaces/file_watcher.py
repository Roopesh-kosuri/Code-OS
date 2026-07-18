import asyncio
import logging
from pathlib import Path
from threading import Lock

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from backend.app.core.paths import IGNORED_DIRS
from backend.app.features.indexing.service import index_manager

logger = logging.getLogger(__name__)


class LoggingEventHandler(FileSystemEventHandler):
    def __init__(self, workspace: str, loop: asyncio.AbstractEventLoop | None) -> None:
        self.workspace = workspace
        self.loop = loop

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or any(part in IGNORED_DIRS for part in Path(event.src_path).parts):
            return
        logger.info("workspace file event: %s %s", event.event_type, event.src_path)
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(index_manager.schedule_file_change(self.workspace, event.src_path), self.loop)


class WorkspaceWatcher:
    def __init__(self) -> None:
        self._observer = Observer()
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
                self._observer.start()
            self._observer.schedule(LoggingEventHandler(resolved, self._loop), resolved, recursive=True)
            self._watched.add(resolved)
            logger.info("workspace.watch started path=%s watched_count=%s", resolved, len(self._watched))

    def status(self) -> dict[str, object]:
        return {"running": self._observer.is_alive(), "watched": sorted(self._watched)}


watcher = WorkspaceWatcher()
