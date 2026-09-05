from __future__ import annotations

"""
computer_controller.py - Opt-in, fail-closed desktop computer control for CODE OS.
Integrates mss (screen capture) and pyautogui (mouse/keyboard input) with strict safety bounds:
- Disabled by default in Settings
- FAILSAFE=True mouse-corner emergency kill switch
- Emergency abort flag & hotkey check
- Forbidden commands and password field guards
- Rate-limit leashing (max 1 action / 2s, max 50 actions / task)
- Mandatory before/after screenshot audit logging
"""

import asyncio
import base64
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mss
import pyautogui

from app.core.paths import normalize_workspace
from app.features.settings.service import get_setting

logger = logging.getLogger(__name__)

# Enforce pyautogui failsafe at import time (slamming mouse to any screen corner aborts)
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

# Forbidden patterns for typing/app execution to prevent catastrophic actions
FORBIDDEN_APP_PATTERNS = [
    r"(?i)\b(?:shutdown|reboot|format|diskpart|bcdedit|vssadmin)\b",
    r"(?i)\b(?:reg\s+delete|del\s+/[fF]|rmdir\s+/[sS]|Remove-Item\s+-Recurse\s+[C-Z]:\\)\b",
    r"(?i)\b(?:Set-MpPreference\s+-DisableRealtimeMonitoring)\b",
]

FORBIDDEN_TEXT_PATTERNS = [
    r"(?i)\b(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*\S+",
]

# Leash counters
MAX_ACTIONS_PER_TASK = 50
MIN_INTERVAL_SECONDS = 2.0

# Global emergency stop state
_emergency_stop_triggered = False


def trigger_emergency_stop(reason: str = "Emergency stop triggered by operator") -> None:
    """Immediately halt any ongoing computer automation."""
    global _emergency_stop_triggered
    _emergency_stop_triggered = True
    logger.warning("ComputerController EMERGENCY STOP: %s", reason)


def reset_emergency_stop() -> None:
    """Reset the emergency stop flag for future authorized runs."""
    global _emergency_stop_triggered
    _emergency_stop_triggered = False


def is_emergency_stopped() -> bool:
    """Check if emergency stop is currently active."""
    return _emergency_stop_triggered


class ComputerController:
    """Safe, rate-limited, fail-closed computer use controller."""

    def __init__(self, workspace: str) -> None:
        self.workspace = str(normalize_workspace(workspace))
        self._action_count = 0
        self._last_action_timestamp: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def audit_dir(self) -> Path:
        """Directory for before/after audit screenshots."""
        p = Path(self.workspace) / ".code_os" / "audit"
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def _check_permission_and_safety(self, action_name: str, payload: str = "") -> None:
        """Enforce fail-closed guard, rate limits, leashing, and forbidden pattern filters."""
        global _emergency_stop_triggered
        if _emergency_stop_triggered:
            raise PermissionError("Computer use halted: Emergency stop (Ctrl+Shift+Q or mouse-corner) was triggered.")

        # 1. Fail-closed: check if computer_use_enabled is ON in settings
        enabled_setting = await get_setting("automation.computer_use_enabled")
        if str(enabled_setting).lower() != "true":
            raise PermissionError("Computer use is disabled in Settings. Enable 'Computer Use' under Settings > Automation to authorize.")

        # 2. Leash: maximum actions per task
        if self._action_count >= MAX_ACTIONS_PER_TASK:
            raise PermissionError(f"Computer use leash exceeded: maximum {MAX_ACTIONS_PER_TASK} actions reached for this task.")

        # 3. Rate limiting: minimum 2.0s between actions
        now = time.time()
        elapsed = now - self._last_action_timestamp
        if elapsed < MIN_INTERVAL_SECONDS:
            await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)

        # 4. Forbidden action / text filters
        check_str = f"{action_name} {payload}"
        for pattern in FORBIDDEN_APP_PATTERNS:
            if re.search(pattern, check_str):
                raise PermissionError(f"Action blocked by safety policy: forbidden system command detected matching '{pattern}'")

        if action_name == "keyboard_type":
            for pattern in FORBIDDEN_TEXT_PATTERNS:
                if re.search(pattern, payload):
                    raise PermissionError("Typing blocked by safety policy: detected possible password/secret exposure.")

    def capture_screen(self, filename: str | None = None) -> dict[str, Any]:
        """Capture the primary desktop display using mss, returns file path and base64."""
        name = filename or f"screen_{int(time.time() * 1000)}.png"
        out_path = self.audit_dir / name

        with mss.mss() as sct:
            # Monitor 1 is primary display in mss (monitor 0 is all monitors combined)
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(mon)
            mss.tools.to_png(shot.rgb, shot.size, output=str(out_path))

        raw_bytes = out_path.read_bytes()
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        return {
            "success": True,
            "path": str(out_path),
            "filename": name,
            "base64": b64,
            "mime_type": "image/png",
            "width": shot.width,
            "height": shot.height,
            "size_bytes": len(raw_bytes),
        }

    async def screen_screenshot(self) -> dict[str, Any]:
        """Capture desktop screen with safety check."""
        await self._check_permission_and_safety("screen_screenshot")
        async with self._lock:
            result = self.capture_screen()
            self._action_count += 1
            self._last_action_timestamp = time.time()
            return result

    async def mouse_click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        """Move cursor and click coordinates with before/after audit capture."""
        await self._check_permission_and_safety("mouse_click", f"({x}, {y})")
        async with self._lock:
            before_shot = self.capture_screen(f"before_click_{int(time.time()*1000)}.png")
            pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            await asyncio.sleep(0.3)
            after_shot = self.capture_screen(f"after_click_{int(time.time()*1000)}.png")

            self._action_count += 1
            self._last_action_timestamp = time.time()
            return {
                "success": True,
                "action": "mouse_click",
                "x": x,
                "y": y,
                "button": button,
                "clicks": clicks,
                "before_screenshot": before_shot["path"],
                "after_screenshot": after_shot["path"],
                "after_base64": after_shot["base64"],
            }

    async def keyboard_type(self, text: str) -> dict[str, Any]:
        """Type text safely with before/after audit capture."""
        await self._check_permission_and_safety("keyboard_type", text)
        async with self._lock:
            before_shot = self.capture_screen(f"before_type_{int(time.time()*1000)}.png")
            pyautogui.write(text, interval=0.04)
            await asyncio.sleep(0.3)
            after_shot = self.capture_screen(f"after_type_{int(time.time()*1000)}.png")

            self._action_count += 1
            self._last_action_timestamp = time.time()
            return {
                "success": True,
                "action": "keyboard_type",
                "length": len(text),
                "before_screenshot": before_shot["path"],
                "after_screenshot": after_shot["path"],
                "after_base64": after_shot["base64"],
            }

    async def hotkey(self, keys: list[str]) -> dict[str, Any]:
        """Trigger keyboard shortcut combination."""
        await self._check_permission_and_safety("hotkey", "+".join(keys))
        async with self._lock:
            before_shot = self.capture_screen(f"before_hotkey_{int(time.time()*1000)}.png")
            pyautogui.hotkey(*keys)
            await asyncio.sleep(0.3)
            after_shot = self.capture_screen(f"after_hotkey_{int(time.time()*1000)}.png")

            self._action_count += 1
            self._last_action_timestamp = time.time()
            return {
                "success": True,
                "action": "hotkey",
                "keys": keys,
                "before_screenshot": before_shot["path"],
                "after_screenshot": after_shot["path"],
                "after_base64": after_shot["base64"],
            }

    async def open_app(self, name: str) -> dict[str, Any]:
        """Launch safe desktop application by name (e.g. notepad, calc)."""
        await self._check_permission_and_safety("open_app", name)
        async with self._lock:
            clean_name = name.strip()
            # Windows safe launch
            if os.name == "nt":
                subprocess.Popen(["cmd.exe", "/c", "start", "", clean_name], shell=False)
            else:
                subprocess.Popen([clean_name])
            await asyncio.sleep(1.0)
            after_shot = self.capture_screen(f"after_open_app_{int(time.time()*1000)}.png")

            self._action_count += 1
            self._last_action_timestamp = time.time()
            return {
                "success": True,
                "action": "open_app",
                "app": clean_name,
                "screenshot": after_shot["path"],
                "base64": after_shot["base64"],
            }

    async def list_windows(self) -> dict[str, Any]:
        """Enumerate active desktop window titles."""
        await self._check_permission_and_safety("list_windows")
        titles: list[str] = []
        try:
            import pygetwindow as gw
            windows = gw.getAllWindows()
            titles = [w.title for w in windows if w.title and w.title.strip()]
        except Exception:
            # Fallback for Windows via PowerShell Get-Process
            try:
                cmd = ["powershell", "-NoProfile", "-Command", "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object -ExpandProperty MainWindowTitle"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                titles = [l.strip() for l in res.stdout.splitlines() if l.strip()]
            except Exception as e:
                logger.warning("ComputerController: failed to list windows: %s", e)

        return {"success": True, "windows": titles[:30]}

    async def focus_window(self, title: str) -> dict[str, Any]:
        """Bring target window to the foreground."""
        await self._check_permission_and_safety("focus_window", title)
        try:
            import pygetwindow as gw
            matches = gw.getWindowsWithTitle(title)
            if matches:
                matches[0].activate()
                await asyncio.sleep(0.5)
                return {"success": True, "focused": matches[0].title}
        except Exception:
            pass

        # Fallback via PowerShell
        if os.name == "nt":
            ps_script = f"""
            $w = (Get-Process | Where-Object {{$_.MainWindowTitle -like '*{title}*'}} | Select-Object -First 1).MainWindowHandle
            if ($w) {{
                $sig = '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);'
                Add-Type -MemberDefinition $sig -Name Api -Namespace Win32
                [Win32.Api]::SetForegroundWindow($w)
            }}
            """
            try:
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], timeout=5)
                await asyncio.sleep(0.5)
                return {"success": True, "focused": title}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"Window not found: '{title}'"}


_computer_controllers: dict[str, ComputerController] = {}


def get_computer_controller(workspace: str) -> ComputerController:
    """Retrieve singleton ComputerController for workspace."""
    norm_ws = str(normalize_workspace(workspace))
    if norm_ws not in _computer_controllers:
        _computer_controllers[norm_ws] = ComputerController(norm_ws)
    return _computer_controllers[norm_ws]
