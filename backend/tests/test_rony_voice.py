"""test_rony_voice.py — Backend test suite for Rony Voice system automation, browsing, and safety."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.auth import get_token
from app.features.ai.rony_voice import system_controller, web_browser, ai_reasoning


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_token()}"}


# ── Test 1: System controller moves mouse & clicks ────────────────────────────
def test_system_controller_moves_mouse():
    """Verify system_controller smoothly moves cursor and clicks with mocked pyautogui."""
    mock_pyautogui = MagicMock()
    with patch.object(system_controller, "pyautogui", mock_pyautogui):
        res_move = system_controller.move_mouse(350, 450, duration=0.1)
        assert res_move["action"] == "move_mouse"
        assert res_move["x"] == 350
        assert res_move["y"] == 450
        mock_pyautogui.moveTo.assert_called_once_with(350, 450, duration=0.1)

        res_click = system_controller.click(350, 450, button="right")
        assert res_click["action"] == "click"
        assert res_click["button"] == "right"
        mock_pyautogui.click.assert_called_once_with(350, 450, button="right")


# ── Test 2: Web browser navigates and clicks ──────────────────────────────────
def test_web_browser_navigates_and_clicks():
    """Verify web_browser initializes driver, navigates to URL, and interacts with elements."""
    mock_driver = MagicMock()
    mock_driver.title = "Test Tech Portal"
    mock_driver.current_url = "https://techportal.org"
    mock_element = MagicMock()

    with patch.object(web_browser, "init_browser", return_value=mock_driver), \
         patch.object(web_browser, "WebDriverWait") as mock_wait:
        mock_wait.return_value.until.return_value = mock_element

        nav_res = web_browser.navigate("https://techportal.org")
        assert nav_res["action"] == "navigate"
        assert nav_res["url"] == "https://techportal.org"
        mock_driver.get.assert_called_once_with("https://techportal.org")

        click_res = web_browser.click_element("button#explore")
        assert click_res["action"] == "click_element"
        assert click_res["status"] == "clicked"
        mock_element.click.assert_called_once()


# ── Test 3: Research summarizes results ───────────────────────────────────────
def test_research_summarizes_results():
    """Verify search_and_summarize queries web, synthesizes takeaways, and returns sources."""
    query = "Autonomous Multi-Agent AI Systems"
    res = web_browser.search_and_summarize(query, num_results=3)

    assert res["query"] == query
    assert "summary" in res
    assert len(res["summary"]) > 20
    assert "sources" in res
    assert len(res["sources"]) == 3

    for src in res["sources"]:
        assert "title" in src
        assert "url" in src
        assert "snippet" in src
        assert src["url"].startswith("http")


# ── Test 4: Booking stops at payment screen ───────────────────────────────────
def test_booking_stops_at_payment():
    """Verify booking flow fills fields, stops at payment screen, and mandates explicit approval."""
    details = {
        "origin": "New York (JFK)",
        "destination": "London Heathrow (LHR)",
        "date": "2026-10-15",
        "passengers": 2,
    }
    booking_res = web_browser.book_ticket("flight", details)

    assert booking_res["service"] == "flight"
    assert booking_res["confirmation_pending"] is True
    assert booking_res["payment_screen_reached"] is True
    assert booking_res["total_cost"] == 970.00  # 485.0 * 2
    assert "SAFETY STOP: Payment approval required" in booking_res["message"]
    assert "checkout" in booking_res["booking_url"]


# ── Test 5: Emergency stop kills automation immediately ───────────────────────
@pytest.mark.asyncio
async def test_emergency_stop_kills_automation():
    """Verify emergency stop sets the kill flag, rejects further automation, and resets cleanly."""
    try:
        # Trigger emergency stop
        stop_res = system_controller.trigger_emergency_stop()
        assert stop_res["status"] == "emergency_stopped"
        assert system_controller.is_emergency_stopped() is True

        # System action should be blocked
        with pytest.raises(RuntimeError, match="Emergency Stop is currently active"):
            system_controller.move_mouse(10, 20)

        # REST API endpoint should reject with 400 while emergency stop is active
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/rony/system-action",
                json={"action": "move_mouse", "params": {"x": 10, "y": 20}},
                headers=_auth_headers(),
            )
            assert res.status_code == 400
            assert "Emergency Stop is active" in res.json()["detail"]

            # Reset emergency stop via API
            reset_res = await client.post("/api/rony/reset-emergency-stop", headers=_auth_headers())
            assert reset_res.status_code == 200
            assert reset_res.json()["emergency_stopped"] is False
            assert system_controller.is_emergency_stopped() is False

    finally:
        system_controller.reset_emergency_stop()


# ── Test 6: Approval required for destructive actions ─────────────────────────
@pytest.mark.asyncio
async def test_approval_required_for_destructive_action():
    """Verify destructive actions (delete, kill, format) require explicit user approval."""
    system_controller.reset_emergency_stop()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Unapproved destructive action
        unapproved_res = await client.post(
            "/api/rony/system-action",
            json={
                "action": "close_application",
                "params": {"app_name": "delete_all_files.exe"},
                "approved": False,
            },
            headers=_auth_headers(),
        )
        assert unapproved_res.status_code == 200
        data = unapproved_res.json()
        assert data["status"] == "approval_required"
        assert data["approval_required"] is True
        assert "requires explicit user approval" in data["message"]

        # Approved destructive action
        with patch.object(system_controller, "close_application") as mock_close:
            mock_close.return_value = {"action": "close_application", "status": "closed"}
            approved_res = await client.post(
                "/api/rony/system-action",
                json={
                    "action": "close_application",
                    "params": {"app_name": "delete_all_files.exe"},
                    "approved": True,
                },
                headers=_auth_headers(),
            )
            assert approved_res.status_code == 200
            assert approved_res.json()["status"] == "closed"
