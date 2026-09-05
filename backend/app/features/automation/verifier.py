from __future__ import annotations

"""
verifier.py - Tightened Auto-Repair ("See and Fix") verification engine for CODE OS.
Evaluates whether web tasks qualify for auto-verification, spins up local servers or file targets,
captures browser console/network logs and screenshots, and gates task completion.
"""

import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.ai.schemas import FileChange
from app.features.process_tracker import track_spawned_process, untrack_process
from app.features.settings.service import get_setting
from .browser_controller import get_browser_controller

logger = logging.getLogger(__name__)

WEB_EXTENSIONS = frozenset({".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".vue", ".css", ".scss"})

EXPLICIT_VERIFY_PATTERNS = (
    re.compile(r"\bbuild\s+(?:a\s+)?website\b", re.IGNORECASE),
    re.compile(r"\bcreate\s+(?:a\s+)?website\b", re.IGNORECASE),
    re.compile(r"\blanding\s+page\b", re.IGNORECASE),
    re.compile(r"\bopen\s+(?:it\s+|the\s+)?in\s+browser\b", re.IGNORECASE),
    re.compile(r"\bopen\s+browser\b", re.IGNORECASE),
    re.compile(r"\btest\s+it\b", re.IGNORECASE),
    re.compile(r"\btest\s+in\s+browser\b", re.IGNORECASE),
    re.compile(r"\bsee\s+how\s+(?:it|this)\s+looks\b", re.IGNORECASE),
    re.compile(r"\bhow\s+it\s+looks\b", re.IGNORECASE),
    re.compile(r"\bverify\s+in\s+browser\b", re.IGNORECASE),
    re.compile(r"\blaunch\s+and\s+test\b", re.IGNORECASE),
    re.compile(r"\bpreview\s+in\s+browser\b", re.IGNORECASE),
    re.compile(r"\bshow\s+in\s+browser\b", re.IGNORECASE),
)

SKIP_VERIFY_PATTERNS = (
    re.compile(r"\bskip\s+(?:browser\s+)?verif(?:y|ication)\b", re.IGNORECASE),
    re.compile(r"\bno\s+browser\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+(?:open\s+in\s+)?browser\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+verify\b", re.IGNORECASE),
)


def should_trigger_auto_verify(
    staged_changes: list[FileChange],
    user_query: str = "",
    manual_override: bool = False,
    browser_control_enabled: bool = True,
    auto_verify_enabled: bool = True,
) -> bool:
    """
    TIGHTENED SCOPE FILTER:
    1. DO NOT AUTO-VERIFY ON MINOR EDITS:
       If task only modified existing files (e.g. fixed typo in style.css, console.log in app.js,
       updated package.json), DO NOT launch the browser. Just emit success:true.
    2. AUTO-VERIFY ONLY FOR 'HIGH-STAKES' WEB TASKS:
       a) Task scaffolded a NEW web project (e.g. created package.json + index.html + src/ files,
          or newly created index.html where original == '').
       b) User prompt explicitly requested visual verification (keywords: 'build a website',
          'landing page', 'open in browser', 'test it', 'see how it looks').
    3. MANUAL OVERRIDE & USER SKIP:
       Always allow user to force verification via UI button (manual_override=True).
       Always allow user to skip verification via prompt keywords ('skip verification', etc.).
    """
    # Rule 3: Manual override always forces verification regardless of task size
    if manual_override:
        return True

    # Check if user explicitly asked to skip verification
    if user_query:
        for p in SKIP_VERIFY_PATTERNS:
            if p.search(user_query):
                return False

    # Setting gates
    if not browser_control_enabled or not auto_verify_enabled:
        return False

    if not staged_changes:
        return False

    # Check if any web files were touched
    web_changes = [
        c for c in staged_changes
        if Path(c.path).suffix.lower() in WEB_EXTENSIONS or Path(c.path).name == "package.json"
    ]
    if not web_changes:
        return False

    # Rule 2b: Prompt explicitly requested visual verification
    if user_query:
        for p in EXPLICIT_VERIFY_PATTERNS:
            if p.search(user_query):
                return True

    # Rule 1: If the task only touched existing files, DO NOT auto-verify!
    # (e.g. fixed a typo in style.css, added console.log to app.js, updated package.json)
    all_files_exist = all(getattr(c, "original", None) != "" for c in staged_changes)
    if all_files_exist:
        return False

    # Rule 2a: Task scaffolded a NEW web project:
    # Check for newly created index.html
    new_html_files = [
        c for c in web_changes
        if Path(c.path).name.lower() in ("index.html", "index.htm") and getattr(c, "original", "") == ""
    ]
    if new_html_files:
        return True

    # Check for newly created package.json + at least one new web file
    new_package_json = any(Path(c.path).name == "package.json" and getattr(c, "original", "") == "" for c in web_changes)
    new_web_files = [c for c in web_changes if getattr(c, "original", "") == ""]
    if new_package_json and len(new_web_files) >= 2:
        return True

    # Otherwise: minor edits / non-scaffolded changes -> DO NOT launch browser
    return False


def _find_free_port() -> int:
    """Find an available ephemeral localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


async def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a localhost port is listening."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.5)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def run_browser_verification(
    workspace: str,
    staged_changes: list[FileChange] | None = None,
    user_query: str = "",
    manual_override: bool = False,
) -> dict[str, Any]:
    """
    Execute browser verification:
    1. Identify web entry point.
    2. Start ephemeral static server if not already running.
    3. Open page in isolated BrowserController.
    4. Collect console errors, network errors, and screenshot.
    5. Return structured verification report.
    """
    norm_ws = str(normalize_workspace(workspace))
    ctrl = get_browser_controller(norm_ws)

    # 1. Determine target entry point
    target_html: str | None = None
    if staged_changes:
        for c in staged_changes:
            if Path(c.path).suffix.lower() in (".html", ".htm"):
                target_html = c.path
                break

    if not target_html:
        for candidate in ("index.html", "public/index.html", "dist/index.html", "src/index.html"):
            if (Path(norm_ws) / candidate).is_file():
                target_html = candidate
                break

    # Check common dev server ports first
    dev_ports = [3000, 5173, 5174, 5175, 5176, 8000, 8080]
    live_port: int | None = None
    for p in dev_ports:
        if await _is_port_open(p):
            live_port = p
            break

    server_proc: subprocess.Popen | None = None
    target_url: str

    if live_port is not None:
        target_url = f"http://127.0.0.1:{live_port}"
    elif target_html and (Path(norm_ws) / target_html).is_file():
        # Spin up quick ephemeral python http server
        free_port = _find_free_port()
        try:
            server_proc = subprocess.Popen(
                ["python", "-m", "http.server", str(free_port), "--bind", "127.0.0.1"],
                cwd=norm_ws,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await track_spawned_process(server_proc.pid, "http_server", norm_ws)
            # Wait briefly for server ready
            for _ in range(10):
                if await _is_port_open(free_port):
                    break
                await asyncio.sleep(0.2)

            target_url = f"http://127.0.0.1:{free_port}/{target_html.replace(os.sep, '/')}"
        except Exception as s_err:
            logger.warning("verifier: could not start http.server: %s. Using file URL fallback.", s_err)
            file_abs = (Path(norm_ws) / target_html).resolve().as_uri()
            target_url = file_abs
    else:
        return {
            "success": False,
            "status": "no_web_entry",
            "message": "No HTML entry point or active dev server found to verify in browser.",
            "console_errors": [],
            "network_errors": [],
            "screenshot": None,
        }

    try:
        # 2. Open browser page
        open_res = await ctrl.open(target_url)
        await asyncio.sleep(1.2)  # Allow client JS scripts to run and render DOM

        # 3. Collect errors and screenshot
        console_errs = await ctrl.console_logs(level="error")
        network_errs = await ctrl.network_errors()
        shot_res = await ctrl.screenshot(f"verify_{int(time.time()*1000)}.png")

        has_errors = bool(console_errs or network_errs or not open_res.get("success", True))
        status_code = "failed" if has_errors else "verified"

        return {
            "success": not has_errors,
            "status": status_code,
            "url": target_url,
            "page_title": open_res.get("title", ""),
            "http_status": open_res.get("status", 200),
            "console_errors": console_errs,
            "network_errors": network_errs,
            "screenshot_path": shot_res.get("path"),
            "screenshot_base64": shot_res.get("base64"),
            "message": f"Browser verification {status_code}: {len(console_errs)} console error(s), {len(network_errs)} network error(s).",
        }
    finally:
        # Clean up ephemeral server if we started one
        if server_proc is not None:
            try:
                server_proc.terminate()
                server_proc.wait(timeout=1.0)
            except Exception:
                try:
                    server_proc.kill()
                except Exception:
                    pass
            await untrack_process(server_proc.pid)
