"""
Unit and regression tests for Multi-Language Run Service and Language Detector.
"""
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.features.terminal.language_detector import (
    detect_language,
    check_toolchain_status,
    get_all_toolchains,
    LANGUAGE_SPECS,
    LanguageSpec,
)
from app.features.terminal.run_service import (
    run_file_stream,
    kill_run_process,
    _active_runs,
    MAX_RUN_MEMORY_BYTES,
    MAX_RUN_TIMEOUT_SECONDS,
)
from app.features.workspaces.trust_service import set_workspace_trust


def test_language_detection_all_families():
    """Verify language detection across all 8 supported language families."""
    assert detect_language("main.py").id == "python"
    assert detect_language("script.pyw").id == "python"
    assert detect_language("app.js").id == "javascript"
    assert detect_language("module.mjs").id == "javascript"
    assert detect_language("config.cjs").id == "javascript"
    assert detect_language("index.ts").id == "typescript"
    assert detect_language("Component.tsx").id == "typescript"
    assert detect_language("main.cpp").id == "cpp"
    assert detect_language("helper.c").id == "cpp"
    assert detect_language("header.h").id == "cpp"
    assert detect_language("App.java").id == "java"
    assert detect_language("server.go").id == "go"
    assert detect_language("lib.rs").id == "rust"
    assert detect_language("deploy.sh").id == "shell"
    assert detect_language("setup.ps1").id == "shell"
    assert detect_language("build.bat").id == "shell"
    assert detect_language("unknown.xyz") is None


def test_toolchain_status_discovery():
    """Verify host toolchain discovery returns structured statuses."""
    toolchains = get_all_toolchains()
    assert len(toolchains) >= 7
    tc_map = {t.id: t for t in toolchains}
    
    # Python is guaranteed installed in the test environment
    assert "python" in tc_map
    assert tc_map["python"].installed is True
    assert tc_map["python"].command_path is not None

    # Shell is guaranteed installed
    assert "shell" in tc_map
    assert tc_map["shell"].installed is True


def test_missing_toolchain_error_message():
    """Verify missing toolchains provide informative error messages with installation guides."""
    spec = LANGUAGE_SPECS["python"]
    # Test fake toolchain
    status = check_toolchain_status("nonexistent_lang")
    assert status.installed is False
    assert "Unsupported language" in (status.error_message or "")


@pytest.mark.asyncio
async def test_run_file_stream_python(tmp_path):
    """Test real Python execution via SSE stream."""
    ws = str(tmp_path)
    py_file = tmp_path / "hello.py"
    py_file.write_text("print('HELLO FROM CODE OS PYTHON RUNNER')\n", encoding="utf-8")

    events = []
    async for packet in run_file_stream(ws, "hello.py"):
        events.append(packet)

    full_stream = "".join(events)
    assert "started" in full_stream
    assert "HELLO FROM CODE OS PYTHON RUNNER" in full_stream
    assert "exit" in full_stream


@pytest.mark.asyncio
async def test_run_file_stream_unsupported_file(tmp_path):
    """Test error event when running unsupported file types."""
    ws = str(tmp_path)
    txt_file = tmp_path / "data.xyz"
    txt_file.write_text("plain text", encoding="utf-8")

    events = []
    async for packet in run_file_stream(ws, "data.xyz"):
        events.append(packet)

    full_stream = "".join(events)
    assert "error" in full_stream
    assert "Unsupported file type" in full_stream


@pytest.mark.asyncio
async def test_kill_run_process(tmp_path):
    """Test terminating a running process via kill_run_process."""
    # Test killing nonexistent
    ok, msg = kill_run_process("fake_run_id_123")
    assert ok is False

    # Spawn real long-running sleep process in Python
    ws = str(tmp_path)
    loop_file = tmp_path / "infinite_loop.py"
    loop_file.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    captured_run_id = None
    gen = run_file_stream(ws, "infinite_loop.py")
    
    # Read first packet (started)
    first_packet = await gen.__anext__()
    for line in first_packet.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[5:])
            captured_run_id = payload.get("run_id")

    assert captured_run_id is not None
    assert captured_run_id in _active_runs

    # Kill process
    kill_ok, kill_msg = kill_run_process(captured_run_id)
    assert kill_ok is True
    assert captured_run_id not in _active_runs


@pytest.mark.asyncio
async def test_api_toolchains_endpoint(async_client):
    """Test GET /api/terminal/toolchains."""
    res = await async_client.get("/api/terminal/toolchains")
    assert res.status_code == 200
    data = res.json()
    assert "toolchains" in data
    assert len(data["toolchains"]) >= 7


@pytest.mark.asyncio
async def test_api_run_and_kill_endpoints(async_client, tmp_path):
    """Test POST /api/terminal/run and POST /api/terminal/run/kill."""
    ws = str(tmp_path / "trusted_run_ws")
    Path(ws).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws, trusted=True)

    py_file = Path(ws) / "calc.py"
    py_file.write_text("print('SUM =', 10 + 25)\n", encoding="utf-8")

    # 1. Run file
    res = await async_client.post(
        "/api/terminal/run",
        json={"workspace": ws, "file_path": "calc.py"}
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
    assert "SUM = 35" in res.text

    # 2. Kill endpoint validation
    res_kill = await async_client.post(
        "/api/terminal/run/kill",
        json={"run_id": "nonexistent_run"}
    )
    assert res_kill.status_code == 200
    assert res_kill.json()["success"] is False
