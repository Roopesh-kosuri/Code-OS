import pytest
from unittest.mock import AsyncMock, patch
from app.main import app
from app.features.ai.coder_mode_service import execute_coder_mode, CoderModeRequest
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.mark.asyncio
async def test_execute_coder_mode_fast_path(tmp_path, temp_db):
    # Create mock workspace file
    calc_file = tmp_path / "calculator.py"
    calc_file.write_text("def divide(a, b):\n    return a / b\n")

    mock_raw_llm_output = (
        "[PROPOSAL: calculator.py]\n"
        "<<<< ORIGINAL\n"
        "def divide(a, b):\n"
        "    return a / b\n"
        "====\n"
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError('Cannot divide by zero')\n"
        "    if a < 0 or b < 0:\n"
        "        # Handle negative numbers gracefully\n"
        "        pass\n"
        "    return a / b\n"
        ">>>>\n"
    )

    class MockProvider:
        model = "test-coder-model"
        async def stream_chat(self, *args, **kwargs):
            yield mock_raw_llm_output

    req = CoderModeRequest(
        workspace=str(tmp_path),
        user_request="add input validation to calculator divide function and handle negative numbers gracefully",
        target_file="calculator.py"
    )

    with patch("app.features.ai.coder_mode_service.provider_for", new=AsyncMock(return_value=MockProvider())):
        res = await execute_coder_mode(req)

    assert res["status"] == "completed"
    assert "duration" in res
    assert res["proposal"]["id"] is not None
    assert res["proposal"]["changes"][0]["path"].endswith("calculator.py")
    assert "ValueError" in res["proposal"]["diff"]
    assert "test_result" in res


def test_coder_mode_api_endpoint(tmp_path, auth_headers, temp_db):
    mock_raw_llm_output = (
        "[PROPOSAL: app.py]\n"
        "<<<< ORIGINAL\n"
        "====\n"
        "print('coder agent test')\n"
        ">>>>\n"
    )

    class MockProvider:
        model = "test-coder-model"
        async def stream_chat(self, *args, **kwargs):
            yield mock_raw_llm_output

    with patch("app.features.ai.coder_mode_service.provider_for", new=AsyncMock(return_value=MockProvider())):
        response = client.post(
            "/api/agents/coder-mode/execute",
            json={
                "workspace": str(tmp_path),
                "user_request": "Create a new app.py file with print statement",
            },
            headers=auth_headers
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["proposal"]["id"] is not None
