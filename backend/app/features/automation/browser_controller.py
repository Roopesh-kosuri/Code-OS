from __future__ import annotations

"""
browser_controller.py - Playwright-powered autonomous browser automation for CODE OS.
Provides isolated, headed (default) browser instances per workspace with process tracking,
dedicated profile directories, console/network log inspection, and DOM interaction.
"""

import asyncio
import base64
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.process_tracker import track_spawned_process, untrack_process
from app.features.settings.service import get_setting

logger = logging.getLogger(__name__)

# Global registry of active workspace browser controllers
_active_controllers: dict[str, BrowserController] = {}
_IDLE_TIMEOUT_SECONDS = 600.0  # 10 minutes


def _detect_browser_channel() -> str | None:
    """Auto-detect installed system browser channel (msedge or chrome) on Windows/OS."""
    # Check Edge first on Windows
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for ep in edge_paths:
        if os.path.isfile(ep):
            return "msedge"
    if shutil.which("msedge") or shutil.which("microsoft-edge"):
        return "msedge"

    # Check Chrome
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for cp in chrome_paths:
        if os.path.isfile(cp):
            return "chrome"
    if shutil.which("chrome") or shutil.which("google-chrome"):
        return "chrome"

    return None


class BrowserController:
    """Manages an isolated, persistent Playwright browser context for a workspace."""

    def __init__(self, workspace: str) -> None:
        self.workspace = str(normalize_workspace(workspace))
        self._playwright = None
        self._context = None
        self._page = None
        self._browser_pid: int | None = None
        self._console_logs: list[dict[str, Any]] = []
        self._network_errors: list[dict[str, Any]] = []
        self._last_active: float = time.time()
        self._lock = asyncio.Lock()

    @property
    def profile_path(self) -> Path:
        """Isolated dedicated user data directory inside workspace."""
        try:
            path = Path(self.workspace) / ".code_os" / "browser-profile"
            path.mkdir(parents=True, exist_ok=True)
            return path
        except (PermissionError, OSError):
            import hashlib
            from app.core.config import get_settings
            safe_name = hashlib.md5(str(self.workspace).encode()).hexdigest()[:12]
            path = get_settings().data_dir / "browser-profiles" / safe_name
            path.mkdir(parents=True, exist_ok=True)
            return path

    @property
    def profile_dir(self) -> Path:
        """Alias for profile_path."""
        return self.profile_path

    @property
    def screenshots_dir(self) -> Path:
        """Screenshots storage directory inside workspace."""
        try:
            path = Path(self.workspace) / ".code_os" / "screenshots"
            path.mkdir(parents=True, exist_ok=True)
            return path
        except (PermissionError, OSError):
            import hashlib
            from app.core.config import get_settings
            safe_name = hashlib.md5(str(self.workspace).encode()).hexdigest()[:12]
            path = get_settings().data_dir / "screenshots" / safe_name
            path.mkdir(parents=True, exist_ok=True)
            return path

    async def _ensure_initialized(self) -> None:
        """Launch persistent Playwright browser context if not already active."""
        async with self._lock:
            self._last_active = time.time()
            if self._context is not None and self._page is not None:
                # Test if context/page is still alive
                try:
                    if not self._page.is_closed():
                        return
                except Exception:
                    pass

            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            # Read user settings
            headless_setting = await get_setting("automation.browser_headless")
            is_headless = str(headless_setting).lower() == "true"

            channel_setting = await get_setting("automation.browser_channel")
            channel = channel_setting if channel_setting and channel_setting != "auto" else _detect_browser_channel()

            # Launch persistent context with strictly isolated profile directory
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(self.profile_path),
                "headless": is_headless,
                "viewport": {"width": 1280, "height": 800},
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }
            if channel:
                launch_kwargs["channel"] = channel

            try:
                self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as exc:
                logger.warning("BrowserController: failed to launch with channel '%s': %s. Falling back to bundled chromium.", channel, exc)
                launch_kwargs.pop("channel", None)
                self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)

            # Track browser process PID in process tracker so orphaned browsers are reaped on restart
            try:
                pid = getattr(getattr(self._context, "_browser_process", None), "pid", None)
                if pid:
                    self._browser_pid = pid
                    await track_spawned_process(pid, "browser", self.workspace)
                    logger.info("BrowserController: launched browser PID %d for %s", pid, self.workspace)
            except Exception as pid_exc:
                logger.warning("BrowserController: could not record browser PID: %s", pid_exc)

            # Setup page & event listeners
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
            self._setup_page_listeners(self._page)

    def _setup_page_listeners(self, page: Any) -> None:
        """Register listeners for console messages and network errors."""
        def _on_console(msg: Any) -> None:
            entry = {
                "type": msg.type,
                "text": msg.text,
                "location": msg.location,
                "timestamp": time.time(),
            }
            self._console_logs.append(entry)
            if len(self._console_logs) > 200:
                self._console_logs.pop(0)

        def _on_request_failed(request: Any) -> None:
            fail_text = request.failure
            entry = {
                "url": request.url,
                "method": request.method,
                "error": fail_text if isinstance(fail_text, str) else (fail_text.get("errorText") if isinstance(fail_text, dict) else str(fail_text)),
                "timestamp": time.time(),
            }
            self._network_errors.append(entry)
            if len(self._network_errors) > 100:
                self._network_errors.pop(0)

        def _on_response(response: Any) -> None:
            if response.status >= 400:
                entry = {
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                    "timestamp": time.time(),
                }
                self._network_errors.append(entry)
                if len(self._network_errors) > 100:
                    self._network_errors.pop(0)

        page.on("console", _on_console)
        page.on("requestfailed", _on_request_failed)
        page.on("response", _on_response)

    async def open(self, url: str) -> dict[str, Any]:
        """Navigate to URL, returns page title, status, and URL."""
        await self._ensure_initialized()
        assert self._page is not None
        self._last_active = time.time()

        resp = await self._page.goto(url, timeout=30000, wait_until="domcontentloaded")
        title = await self._page.title()
        status_code = resp.status if resp else 200
        return {
            "success": status_code < 400,
            "url": self._page.url,
            "title": title,
            "status": status_code,
        }

    async def screenshot(self, filename: str | None = None) -> dict[str, Any]:
        """Capture screenshot of the active page, saving to PNG and returning base64."""
        await self._ensure_initialized()
        assert self._page is not None
        self._last_active = time.time()

        name = filename or f"browser_{int(time.time() * 1000)}.png"
        out_path = self.screenshots_dir / name
        await self._page.screenshot(path=str(out_path), full_page=False)

        raw_bytes = out_path.read_bytes()
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        return {
            "success": True,
            "path": str(out_path),
            "filename": name,
            "base64": b64,
            "mime_type": "image/png",
            "size_bytes": len(raw_bytes),
        }

    async def console_logs(self, level: str = "error") -> list[dict[str, Any]]:
        """Return captured console logs matching the level filter (all, error, warning, info)."""
        self._last_active = time.time()
        lvl = level.lower().strip()
        if lvl == "all":
            return list(self._console_logs)
        elif lvl == "warning":
            return [l for l in self._console_logs if l.get("type") in ("warning", "error")]
        # default to error
        return [l for l in self._console_logs if l.get("type") == "error"]

    async def network_errors(self) -> list[dict[str, Any]]:
        """Return captured failed HTTP requests and error responses."""
        self._last_active = time.time()
        return list(self._network_errors)

    async def click(self, selector: str) -> dict[str, Any]:
        """Click element matching DOM selector."""
        await self._ensure_initialized()
        assert self._page is not None
        self._last_active = time.time()
        await self._page.click(selector, timeout=10000)
        return {"success": True, "selector": selector}

    async def type(self, selector: str, text: str) -> dict[str, Any]:
        """Fill or type text into element matching DOM selector."""
        await self._ensure_initialized()
        assert self._page is not None
        self._last_active = time.time()
        await self._page.fill(selector, text, timeout=10000)
        return {"success": True, "selector": selector, "length": len(text)}

    async def wait_for(self, selector: str, timeout: float = 10.0) -> dict[str, Any]:
        """Wait for selector to appear in DOM."""
        await self._ensure_initialized()
        assert self._page is not None
        self._last_active = time.time()
        await self._page.wait_for_selector(selector, timeout=int(timeout * 1000))
        return {"success": True, "selector": selector}

    async def scroll(self, direction: str = "down") -> dict[str, Any]:
        """Scroll viewport up or down."""
        await self._ensure_initialized()
        assert self._page is not None
        self._last_active = time.time()
        delta = 500 if direction.lower() == "down" else -500
        await self._page.mouse.wheel(0, delta)
        return {"success": True, "direction": direction}

    async def close(self) -> None:
        """Cleanly close page, context, playwright instance, and untrack PID."""
        async with self._lock:
            try:
                if self._page and not self._page.is_closed():
                    await self._page.close()
            except Exception:
                pass
            self._page = None

            try:
                if self._context:
                    await self._context.close()
            except Exception:
                pass
            self._context = None

            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

            if self._browser_pid:
                await untrack_process(self._browser_pid)
                self._browser_pid = None


def get_browser_controller(workspace: str) -> BrowserController:
    """Retrieve or create singleton BrowserController for the specified workspace."""
    norm_ws = str(normalize_workspace(workspace))
    if norm_ws not in _active_controllers:
        _active_controllers[norm_ws] = BrowserController(norm_ws)
    return _active_controllers[norm_ws]


async def close_browser_controller(workspace: str) -> None:
    """Close and remove the browser controller for the specified workspace."""
    norm_ws = str(normalize_workspace(workspace))
    ctrl = _active_controllers.pop(norm_ws, None)
    if ctrl:
        await ctrl.close()


def is_browser_trusted(workspace: str) -> bool:
    """Check if browser control has been approved with 'always allow' for this workspace."""
    try:
        norm_ws = Path(normalize_workspace(workspace))
        trust_file = norm_ws / ".code_os" / "automation_trust.json"
        if trust_file.is_file():
            data = json.loads(trust_file.read_text(encoding="utf-8"))
            return bool(data.get("browser_trusted", False))
    except Exception as exc:
        logger.warning("BrowserController: failed to read automation_trust.json: %s", exc)
    return False


def trust_browser(workspace: str) -> None:
    """Save persistent trust for browser control in this workspace."""
    try:
        norm_ws = Path(normalize_workspace(workspace))
        os_dir = norm_ws / ".code_os"
        os_dir.mkdir(parents=True, exist_ok=True)
        trust_file = os_dir / "automation_trust.json"
        data = {}
        if trust_file.is_file():
            try:
                data = json.loads(trust_file.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data["browser_trusted"] = True
        trust_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("BrowserController: failed to write automation_trust.json: %s", exc)
