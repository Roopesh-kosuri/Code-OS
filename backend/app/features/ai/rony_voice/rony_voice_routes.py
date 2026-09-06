"""rony_voice_routes.py — REST API endpoints for Rony Voice desktop automation, browsing, and safety."""
from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import system_controller, web_browser, ai_reasoning

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rony", tags=["rony_voice"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SystemActionRequest(BaseModel):
    action: str = Field(..., description="Action name: move_mouse, click, type_text, press_key, open_application, close_application, list_windows, focus_window, minimize_window, maximize_window")
    params: dict[str, Any] = Field(default_factory=dict)
    approved: bool = Field(default=False, description="Whether user explicitly approved destructive action")


class BrowseRequest(BaseModel):
    url: str
    actions: list[dict[str, Any]] = Field(default_factory=list)


class ResearchRequest(BaseModel):
    query: str
    num_results: int = 5


class BookTicketRequest(BaseModel):
    service: str = "flight"
    details: dict[str, Any] = Field(default_factory=dict)


class AnalyzeScreenRequest(BaseModel):
    question: str = "What is on the screen?"


class DecomposeRequest(BaseModel):
    prompt: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/system-action")
async def handle_system_action(req: SystemActionRequest) -> dict[str, Any]:
    """Execute a system controller action with destructive approval checks."""
    if system_controller.is_emergency_stopped():
        raise HTTPException(
            status_code=400,
            detail="Emergency Stop is active. Reset emergency stop before executing actions.",
        )

    # Safety Gate: check for destructive actions
    if system_controller.is_destructive_action(req.action, req.params) and not req.approved:
        return {
            "status": "approval_required",
            "action": req.action,
            "params": req.params,
            "message": f"Destructive action '{req.action}' requires explicit user approval before execution.",
            "approval_required": True,
        }

    act = req.action.lower()
    p = req.params

    try:
        if act == "move_mouse":
            return system_controller.move_mouse(p.get("x", 0), p.get("y", 0), p.get("duration", 0.2))
        elif act == "click":
            return system_controller.click(p.get("x"), p.get("y"), p.get("button", "left"))
        elif act == "type_text":
            return system_controller.type_text(p.get("text", ""), p.get("delay", 0.05))
        elif act == "press_key":
            return system_controller.press_key(p.get("keys", p.get("key_combination", "")))
        elif act == "open_application":
            return system_controller.open_application(p.get("app_name", ""))
        elif act == "close_application":
            return system_controller.close_application(p.get("app_name", ""))
        elif act == "list_windows":
            return {"windows": system_controller.list_windows()}
        elif act == "focus_window":
            return system_controller.focus_window(p.get("title", ""))
        elif act == "minimize_window":
            return system_controller.minimize_window(p.get("title", "all"))
        elif act == "maximize_window":
            return system_controller.maximize_window(p.get("title", ""))
        elif act == "get_active_window":
            return system_controller.get_active_window()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown system action '{req.action}'")
    except Exception as e:
        logger.error(f"Error executing system action {req.action}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/browse")
async def handle_browse(req: BrowseRequest) -> dict[str, Any]:
    """Open a webpage and optionally execute sequence of browser actions."""
    if system_controller.is_emergency_stopped():
        raise HTTPException(status_code=400, detail="Emergency Stop is active.")

    nav_res = web_browser.navigate(req.url)
    results: list[dict[str, Any]] = [nav_res]

    for act in req.actions:
        action_name = act.get("action", "")
        if action_name == "click":
            results.append(web_browser.click_element(act.get("target", "")))
        elif action_name == "type":
            results.append(web_browser.type_into_field(act.get("selector", ""), act.get("text", "")))

    content = web_browser.extract_page_content()
    return {"status": "ok", "url": req.url, "results": results, "page_content": content}


@router.post("/research")
async def handle_research(req: ResearchRequest) -> dict[str, Any]:
    """Automate web search and summarize top findings."""
    return web_browser.search_and_summarize(req.query, req.num_results)


@router.post("/book")
async def handle_booking(req: BookTicketRequest) -> dict[str, Any]:
    """Automate ticket booking up to checkout with pre-payment approval halt."""
    return web_browser.book_ticket(req.service, req.details)


@router.post("/analyze-screen")
async def handle_screen_analysis(req: AnalyzeScreenRequest) -> dict[str, Any]:
    """Capture current screenshot and answer query about screen content."""
    screenshot_bytes = system_controller.take_screenshot()
    return ai_reasoning.analyze_screenshot(screenshot_bytes, req.question)


@router.post("/decompose")
async def handle_decompose(req: DecomposeRequest) -> dict[str, Any]:
    """Break a voice prompt down into sequenced execution steps."""
    steps = ai_reasoning.decompose_task(req.prompt)
    return {"prompt": req.prompt, "steps": steps, "total_steps": len(steps)}


@router.post("/emergency-stop")
async def handle_emergency_stop() -> dict[str, Any]:
    """Immediately halt all running desktop automation and browser processes."""
    res = system_controller.trigger_emergency_stop()
    web_browser.close_browser()
    return res


@router.post("/reset-emergency-stop")
async def handle_reset_emergency_stop() -> dict[str, Any]:
    """Reset emergency stop state after user acknowledgment."""
    system_controller.reset_emergency_stop()
    return {"status": "reset", "emergency_stopped": False}


@router.get("/status")
async def get_rony_status() -> dict[str, Any]:
    """Check current status of system controller, browser, and safety state."""
    active_win = system_controller.get_active_window()
    return {
        "automation_active": False,
        "emergency_stopped": system_controller.is_emergency_stopped(),
        "browser_open": web_browser._active_driver is not None,
        "active_window": active_win,
        "selenium_available": web_browser.SELENIUM_AVAILABLE,
        "system_platform": "win32",
    }
