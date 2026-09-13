"""
backend/tests/test_aud_010_authenticated_sse.py — Regression tests for AUD-010.

Verifies:
1. test_sse_stream_authorized_via_token (ASGI, real middleware) for all 3 streams:
   - /api/team/jobs/{job_id}/events
   - /api/marathon/{marathon_id}/stream
   - /api/terminal/stream/{terminal_id}
2. test_sse_stream_rejects_missing_invalid_expired_token:
   - Missing token -> 401
   - Malformed / bad signature token -> 401
   - Expired token -> 401
   - Route scope mismatch -> 401
   - Stream token on non-SSE route -> 401
   - Stream token request for non-SSE route -> 400
"""

import base64
import hashlib
import hmac
import json
import time
import httpx
from httpx import ASGITransport
import pytest

from app.main import app
from app.core.auth import get_token, mint_stream_token
from app.features.ai.terminal.agentic_terminal_service import create_session, close_session


@pytest.mark.asyncio
async def test_sse_stream_authorized_via_token(temp_db):
    """
    Test that each of the three SSE streams is successfully authorized
    via a minted stream token in the ?token= query parameter.
    Tested with real ASGI AuthMiddleware.
    """
    session_token = get_token()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Team stream: /api/team/jobs/{job_id}/events
        team_job_id = "test_team_sse_job_123"
        team_route = f"/api/team/jobs/{team_job_id}/events"

        resp = await client.post(
            "/api/auth/stream-token",
            json={"route": team_route},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 200
        team_token = resp.json()["token"]

        async with client.stream("GET", f"{team_route}?snapshot_only=true&token={team_token}") as sse_res:
            assert sse_res.status_code == 200
            async for line in sse_res.aiter_lines():
                if "team_snapshot" in line:
                    break

        # 2. Marathon stream: /api/marathon/{marathon_id}/stream
        marathon_id = "mrn_test_sse_456"
        marathon_route = f"/api/marathon/{marathon_id}/stream"

        resp = await client.post(
            "/api/auth/stream-token",
            json={"route": marathon_route},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 200
        marathon_token = resp.json()["token"]

        async with client.stream("GET", f"{marathon_route}?workspace=/test/ws&snapshot_only=true&token={marathon_token}") as sse_res:
            assert sse_res.status_code == 200
            async for line in sse_res.aiter_lines():
                if ": connected" in line:
                    break

        # 3. Terminal stream: /api/terminal/stream/{terminal_id}
        term_id = create_session("test_job", "/test/ws")
        try:
            terminal_route = f"/api/terminal/stream/{term_id}"

            resp = await client.post(
                "/api/auth/stream-token",
                json={"route": terminal_route},
                headers={"Authorization": f"Bearer {session_token}"},
            )
            assert resp.status_code == 200
            term_token = resp.json()["token"]

            async with client.stream("GET", f"{terminal_route}?snapshot_only=true&token={term_token}") as sse_res:
                assert sse_res.status_code == 200
                async for line in sse_res.aiter_lines():
                    if "connected" in line:
                        break
        finally:
            await close_session(term_id)



@pytest.mark.asyncio
async def test_sse_stream_rejects_missing_invalid_expired_token(temp_db):
    """
    Test that real AuthMiddleware strictly rejects unauthorized access to SSE routes
    and non-SSE routes when using stream tokens.
    """
    session_token = get_token()
    team_route = "/api/team/jobs/job_reject_test/events"
    marathon_route = "/api/marathon/mrn_reject_test/stream"
    transport = ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing token on SSE route -> 401
        res = await client.get(team_route)
        assert res.status_code == 401
        assert "Missing or malformed Authorization" in res.json().get("detail", "")

        # 2. Invalid / malformed token on SSE route -> 401
        res = await client.get(f"{team_route}?token=invalid.token.structure")
        assert res.status_code == 401
        assert "Invalid or expired stream token" in res.json().get("detail", "")

        # Tampered signature -> 401
        valid_token = mint_stream_token(team_route)
        parts = valid_token.split(".")
        tampered_token = f"{parts[0]}.badsignature123"
        res = await client.get(f"{team_route}?token={tampered_token}")
        assert res.status_code == 401
        assert "Invalid stream token signature" in res.json().get("detail", "")

        # 3. Expired token -> 401
        p = {"route": team_route, "exp": time.time() - 10, "nonce": "abc"}
        p_b64 = base64.urlsafe_b64encode(json.dumps(p, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
        sig = hmac.new(session_token.encode(), p_b64.encode(), hashlib.sha256).hexdigest()
        exp_token = f"{p_b64}.{sig}"
        res = await client.get(f"{team_route}?token={exp_token}")
        assert res.status_code == 401
        assert "Stream token expired" in res.json().get("detail", "")

        # 4. Route scope mismatch -> 401
        res = await client.get(f"{marathon_route}?workspace=/test&token={valid_token}")
        assert res.status_code == 401
        assert "Stream token scope mismatch" in res.json().get("detail", "")

        # 5. Stream token query param on NON-SSE route -> 401
        res = await client.get(f"/api/workspaces?token={valid_token}")
        assert res.status_code == 401
        assert "Stream token query parameter is only permitted on SSE stream routes" in res.json().get("detail", "")

        # 6. /api/auth/stream-token rejects non-SSE routes -> 400
        res = await client.post(
            "/api/auth/stream-token",
            json={"route": "/api/workspaces"},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert res.status_code == 400
        assert "Invalid SSE stream route" in res.json().get("detail", "")
