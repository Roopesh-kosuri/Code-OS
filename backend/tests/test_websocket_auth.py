"""
test_websocket_auth.py - Phase 1A FIX 2 tests for WebSocket authentication.
Verifies terminal WebSocket rejects connections without a valid session token.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ws_terminal_rejects_no_token(tmp_path):
    """Terminal WebSocket must close with 4401 when no token is supplied."""
    from app.features.terminal import routes as _rt

    ws_mock = MagicMock()
    ws_mock.query_params = {"cwd": str(tmp_path)}  # no token key
    ws_mock.close = AsyncMock()

    with patch("app.core.auth.get_token", return_value="correct-token-abc123"):
        await _rt.terminal_websocket(ws_mock)

    ws_mock.close.assert_called_once()
    call_args = ws_mock.close.call_args
    code = call_args.kwargs.get("code") if call_args.kwargs else (call_args.args[0] if call_args.args else None)
    assert code == 4401, f"Expected 4401 (Unauthorized), got {code}"


@pytest.mark.asyncio
async def test_ws_terminal_rejects_wrong_token(tmp_path):
    """Terminal WebSocket must close with 4401 when a wrong token is supplied."""
    from app.features.terminal import routes as _rt

    ws_mock = MagicMock()
    ws_mock.query_params = {"cwd": str(tmp_path), "token": "wrong-token-xyz"}
    ws_mock.close = AsyncMock()

    with patch("app.core.auth.get_token", return_value="correct-token-abc123"):
        await _rt.terminal_websocket(ws_mock)

    ws_mock.close.assert_called_once()
    call_args = ws_mock.close.call_args
    code = call_args.kwargs.get("code") if call_args.kwargs else (call_args.args[0] if call_args.args else None)
    assert code == 4401, f"Expected 4401 (Unauthorized), got {code}"


@pytest.mark.asyncio
async def test_ws_terminal_valid_token_not_rejected(tmp_path):
    """Terminal WebSocket must NOT close with 4401 when a correct token is supplied."""
    from app.features.terminal import routes as _rt
    from app.features.workspaces import trust_service as _ts

    ws_mock = MagicMock()
    ws_mock.query_params = {"cwd": str(tmp_path), "token": "correct-token-abc123"}
    ws_mock.close = AsyncMock()
    ws_mock.accept = AsyncMock()
    ws_mock.send_text = AsyncMock()

    with patch("app.core.auth.get_token", return_value="correct-token-abc123"), \
         patch.object(_ts, "get_workspace_trust", new=AsyncMock(return_value={"trusted": False})):
        await _rt.terminal_websocket(ws_mock)

    # Any close that happened must NOT be 4401
    for c in ws_mock.close.call_args_list:
        code = c.kwargs.get("code") if c.kwargs else (c.args[0] if c.args else None)
        assert code != 4401, f"Valid token incorrectly got 4401 close"

@pytest.mark.asyncio
async def test_ws_rejects_no_token(tmp_path):
    """Alias matching Phase 4 specification for websocket token rejection."""
    await test_ws_terminal_rejects_no_token(tmp_path)
