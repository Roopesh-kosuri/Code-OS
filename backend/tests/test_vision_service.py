import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from app.features.ai.vision_service import (
    resolve_default_vision_model,
    capture_screenshot,
    analyze_image_with_vlm,
    DEFAULT_VISION_MODELS,
)
from app.features.ai.chat_harness import (
    _parse_tool_calls_extended,
    _extract_heuristic_tool_calls,
)


def test_resolve_default_vision_model():
    assert resolve_default_vision_model("groq") == "meta/llama-3.2-11b-vision-instruct"
    assert resolve_default_vision_model("openai") == "gpt-4o-mini"
    assert resolve_default_vision_model("anthropic") == "claude-3-5-haiku-latest"
    assert resolve_default_vision_model("gemini") == "gemini-2.5-flash"
    assert resolve_default_vision_model("nvidia-nim") == "meta/llama-3.2-11b-vision-instruct"
    assert resolve_default_vision_model("ollama") == "llama3.2-vision"
    assert resolve_default_vision_model("unknown") == "meta/llama-3.2-11b-vision-instruct"


@pytest.mark.asyncio
async def test_capture_screenshot_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "format": "image/jpeg",
        "width": 1280,
        "height": 900,
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        success, img_data, fmt = await capture_screenshot(
            mode="preview",
            target="hello.html",
            workspace="D:/workspace",
        )

        assert success is True
        assert fmt == "image/jpeg"
        assert len(img_data) > 20


@pytest.mark.asyncio
async def test_capture_screenshot_connection_failure():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Connection refused")
        success, err_msg, fmt = await capture_screenshot(
            mode="preview",
            target="hello.html",
            workspace="D:/workspace",
        )

        assert success is False
        assert "not running on port" in err_msg


@pytest.mark.asyncio
async def test_analyze_image_with_vlm_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "The header renders with a dark gradient and white text. Navigation items are aligned to the right. No overlapping text is detected.",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        success, findings = await analyze_image_with_vlm(
            image_base64="fake_base64_data",
            format_type="image/jpeg",
            question="Are navigation links visible and is anything overlapping?",
            target="index.html",
            mode="preview",
            provider="groq",
            model="llama-3.2-11b-vision-preview",
            api_key="gsk_test",
        )

        assert success is True
        assert "Navigation items are aligned" in findings
        assert "No overlapping text is detected" in findings


def test_parse_tool_calls_extended_take_screenshot():
    response = """I will visually inspect the rendered page.
[TOOL_CALL: take_screenshot]
{"mode": "preview", "target": "hello.html", "question": "Does the hero title overlap the navbar?"}
[/TOOL_CALL]
"""
    calls = _parse_tool_calls_extended(response)
    assert len(calls) == 1
    assert calls[0].name == "take_screenshot"
    assert calls[0].arguments["mode"] == "preview"
    assert calls[0].arguments["target"] == "hello.html"
    assert "overlap" in calls[0].arguments["question"]


def test_extract_heuristic_tool_calls_vision():
    response = "Let me look at the page hello.html to tell me what's broken visually."
    calls = _extract_heuristic_tool_calls(response, user_query="look at hello.html and tell me what is broken visually")
    assert len(calls) >= 1
    assert calls[0].name == "take_screenshot"
    assert calls[0].arguments["target"] == "hello.html"
