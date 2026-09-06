"""
test_agentic_terminal.py — Unit and integration tests for Agentic Terminal.

Required Tests:
1. test_create_terminal_session
2. test_execute_command_streams_output
3. test_stream_output_sse_emits_events
4. test_timeout_kills_hung_process
5. test_send_signal_terminates_process
6. test_process_tracker_registers_pid
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.features.ai.terminal.agentic_terminal_service import (
    create_session,
    get_session,
    close_session,
    execute_command,
    send_signal,
    stream_output,
    list_active_sessions,
    clear_all_sessions,
)


@pytest.fixture(autouse=True)
def clean_sessions():
    clear_all_sessions()
    yield
    clear_all_sessions()


def test_create_terminal_session(tmp_path: Path):
    """Verify create_session initializes a new session and get_session retrieves it."""
    job_id = "job_term_123"
    workspace = str(tmp_path)

    terminal_id = create_session(job_id=job_id, workspace=workspace)
    assert terminal_id.startswith("term_")

    session = get_session(terminal_id)
    assert session is not None
    assert session["terminal_id"] == terminal_id
    assert session["job_id"] == job_id
    assert session["status"] == "idle"
    assert session["history"] == []

    active = list_active_sessions()
    assert any(s["terminal_id"] == terminal_id for s in active)


@pytest.mark.asyncio
async def test_execute_command_streams_output(tmp_path: Path):
    """Verify execute_command spawns a subprocess and captures stdout/stderr line-by-line."""
    job_id = "job_exec_test"
    workspace = str(tmp_path)
    terminal_id = create_session(job_id=job_id, workspace=workspace)

    cmd = 'python -c "print(\'line 1\'); print(\'line 2\')"'
    res = await execute_command(terminal_id, cmd)

    assert res["exit_code"] == 0
    assert "line 1" in res["stdout"]
    assert "line 2" in res["stdout"]
    assert res["duration_ms"] > 0

    session = get_session(terminal_id)
    assert len(session["history"]) == 1
    assert session["history"][0]["exit_code"] == 0


@pytest.mark.asyncio
async def test_stream_output_sse_emits_events(tmp_path: Path):
    """Verify stream_output SSE generator emits input, output, and exit events."""
    job_id = "job_sse_test"
    workspace = str(tmp_path)
    terminal_id = create_session(job_id=job_id, workspace=workspace)

    events_received = []

    async def consumer():
        gen = stream_output(terminal_id)
        async for chunk in gen:
            if chunk.startswith("data: "):
                raw_json = chunk[6:].strip()
                data = json.loads(raw_json)
                events_received.append(data)
                if data.get("type") == "exit":
                    break

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)  # Allow consumer to connect

    cmd = 'python -c "print(\'hello from sse\')"'
    await execute_command(terminal_id, cmd)

    await asyncio.wait_for(consumer_task, timeout=5.0)

    event_types = [e.get("type") for e in events_received]
    assert "connected" in event_types
    assert "input" in event_types
    assert "output" in event_types
    assert "exit" in event_types

    output_events = [e for e in events_received if e.get("type") == "output"]
    assert any("hello from sse" in e.get("line", "") for e in output_events)


@pytest.mark.asyncio
async def test_timeout_kills_hung_process(tmp_path: Path):
    """Verify timeout kills a hung process and marks status correctly."""
    job_id = "job_timeout_test"
    workspace = str(tmp_path)
    terminal_id = create_session(job_id=job_id, workspace=workspace)

    # Command that sleeps for 5 seconds, but timeout is 0.2s
    cmd = 'python -c "import time; time.sleep(5)"'
    res = await execute_command(terminal_id, cmd, timeout=0.2)

    assert res["exit_code"] != 0
    assert "timed out" in res["stderr"].lower()


@pytest.mark.asyncio
async def test_send_signal_terminates_process(tmp_path: Path):
    """Verify send_signal terminates an actively running process in the terminal."""
    job_id = "job_signal_test"
    workspace = str(tmp_path)
    terminal_id = create_session(job_id=job_id, workspace=workspace)

    cmd = 'python -c "import time; time.sleep(10)"'
    exec_task = asyncio.create_task(execute_command(terminal_id, cmd))

    # Wait for process to spawn
    await asyncio.sleep(0.25)

    # Send SIGINT signal
    signaled = await send_signal(terminal_id, "SIGINT")
    assert signaled is True

    res = await asyncio.wait_for(exec_task, timeout=5.0)
    assert res["exit_code"] != 0


@pytest.mark.asyncio
async def test_process_tracker_registers_pid(tmp_path: Path):
    """Verify child process PIDs are registered with process_tracker for orphan hygiene."""
    job_id = "job_tracker_test"
    workspace = str(tmp_path)
    terminal_id = create_session(job_id=job_id, workspace=workspace)

    with patch("app.features.ai.terminal.agentic_terminal_service.track_spawned_process", new_callable=AsyncMock) as mock_track, \
         patch("app.features.ai.terminal.agentic_terminal_service.untrack_process", new_callable=AsyncMock) as mock_untrack:

        cmd = 'python -c "print(\'tracked\')"'
        await execute_command(terminal_id, cmd)

        assert mock_track.called
        assert mock_untrack.called
        # Check that PID and process_type were passed
        pid_arg = mock_track.call_args[0][0]
        type_arg = mock_track.call_args[0][1]
        assert isinstance(pid_arg, int)
        assert type_arg == "agentic_terminal"


@pytest.mark.asyncio
async def test_agentic_terminal_routes_api(tmp_path: Path):
    """Verify HTTP endpoints: create, execute, history, signal, close."""
    from app.core.auth import get_token
    headers = {"Authorization": f"Bearer {get_token()}"}
    transport = ASGITransport(app=app)

    with patch("app.features.ai.terminal.agentic_terminal_service.track_spawned_process", new_callable=AsyncMock), \
         patch("app.features.ai.terminal.agentic_terminal_service.untrack_process", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create session
            create_resp = await client.post(
                "/api/terminal/create",
                json={"job_id": "job_route_test", "workspace": str(tmp_path)},
                headers=headers,
            )
            assert create_resp.status_code == 200
            term_id = create_resp.json()["terminal_id"]
            assert term_id.startswith("term_")

            # 2. Execute command
            cmd = 'python -c "print(\'route test ok\')"'
            exec_resp = await client.post(
                "/api/terminal/execute",
                json={"terminal_id": term_id, "command": cmd},
                headers=headers,
            )
            assert exec_resp.status_code == 200
            assert "route test ok" in exec_resp.json()["result"]["stdout"]

            # 3. Get history
            hist_resp = await client.get(f"/api/terminal/history/{term_id}", headers=headers)
            assert hist_resp.status_code == 200
            assert len(hist_resp.json()["history"]) == 1

            # 4. Signal endpoint
            sig_resp = await client.post(
                "/api/terminal/signal",
                json={"terminal_id": term_id, "signal": "SIGINT"},
                headers=headers,
            )
            assert sig_resp.status_code == 200

            # 5. Close session
            close_resp = await client.post(
                "/api/terminal/close",
                json={"terminal_id": term_id},
                headers=headers,
            )
            assert close_resp.status_code == 200
            assert close_resp.json()["closed"] is True
