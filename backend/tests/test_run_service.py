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


def test_java_toolchain_status_missing_and_installed():
    """Verify check_toolchain_status for Java requires javac."""
    from unittest.mock import patch
    
    # 1. When javac is missing
    with patch("app.features.terminal.language_detector._find_executable", side_effect=lambda cmds: "java.exe" if "java" in cmds else None):
        status = check_toolchain_status("java")
        assert status.installed is False
        assert "Java compiler (javac) not found" in (status.error_message or "")
        assert "adoptium.net" in (status.install_hint or "")

    # 2. When both javac and java are present
    with patch("app.features.terminal.language_detector._find_executable", side_effect=lambda cmds: "javac.exe" if "javac" in cmds else ("java.exe" if "java" in cmds else None)), \
         patch("app.features.terminal.language_detector._get_version_output", return_value="javac 17.0.2"):
        status = check_toolchain_status("java")
        assert status.installed is True
        assert status.version == "javac 17.0.2"
        assert status.compile_command_path == "javac.exe"


@pytest.mark.asyncio
async def test_java_compilation_and_execution_with_package_and_space_path(tmp_path):
    """Verify compiling and executing Java with package declaration and path with spaces."""
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.features.terminal.language_detector import ToolchainStatus

    ws_dir = tmp_path / "Roopesh Kosuri" / "workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws = str(ws_dir)

    java_file = ws_dir / "src" / "main" / "java" / "com" / "example" / "puzzle" / "SlidingPuzzle.java"
    java_file.parent.mkdir(parents=True, exist_ok=True)
    java_file.write_text(
        "package com.example.puzzle;\n\npublic class SlidingPuzzle {\n    public static void main(String[] args) {\n        System.out.println(\"PUZZLE SOLVED\");\n    }\n}\n",
        encoding="utf-8",
    )

    mock_status = ToolchainStatus(
        id="java",
        name="Java",
        installed=True,
        version="javac 17.0.2",
        command_path="C:\\jdk\\bin\\java.exe",
        compile_command_path="C:\\jdk\\bin\\javac.exe",
        install_hint="Install JDK 17+",
    )

    # Mock subprocess for javac and java
    mock_compile_proc = AsyncMock()
    mock_compile_proc.returncode = 0
    mock_compile_proc.communicate = AsyncMock(return_value=(b"", b""))

    mock_run_proc = AsyncMock()
    mock_run_proc.returncode = 0
    mock_run_proc.pid = 12345
    mock_stdout = AsyncMock()
    mock_stdout.readline = AsyncMock(side_effect=[b"PUZZLE SOLVED\r\n", b""])
    mock_stderr = AsyncMock()
    mock_stderr.readline = AsyncMock(side_effect=[b""])
    mock_run_proc.stdout = mock_stdout
    mock_run_proc.stderr = mock_stderr
    mock_run_proc.wait = AsyncMock(return_value=0)

    spawned_cmds = []

    async def mock_create_subprocess_exec(*cmd, **kwargs):
        spawned_cmds.append(list(cmd))
        if "javac" in cmd[0]:
            return mock_compile_proc
        return mock_run_proc

    with patch("app.features.terminal.run_service.check_toolchain_status", return_value=mock_status), \
         patch("app.features.terminal.run_service._find_executable", side_effect=lambda cmds: "C:\\jdk\\bin\\javac.exe" if "javac" in cmds else "C:\\jdk\\bin\\java.exe"), \
         patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess_exec), \
         patch("app.features.terminal.run_service._monitor_run_governor", AsyncMock()):
        events = []
        async for packet in run_file_stream(ws, "src/main/java/com/example/puzzle/SlidingPuzzle.java"):
            events.append(packet)

        full_stream = "".join(events)
        assert "compiling" in full_stream
        assert "started" in full_stream
        assert "PUZZLE SOLVED" in full_stream
        assert "exit" in full_stream

        # Check compiled with javac and executed fully qualified class name
        assert len(spawned_cmds) >= 2
        javac_cmd = spawned_cmds[0]
        assert "javac" in javac_cmd[0]
        assert "-d" in javac_cmd
        assert "-cp" in javac_cmd
        java_run_cmd = spawned_cmds[1]
        assert "java" in java_run_cmd[0]
        assert "com.example.puzzle.SlidingPuzzle" in java_run_cmd


@pytest.mark.asyncio
async def test_java_compilation_syntax_error_reporting(tmp_path):
    """Verify compilation failure captures line numbers and error detail."""
    from unittest.mock import patch, AsyncMock
    from app.features.terminal.language_detector import ToolchainStatus

    ws = str(tmp_path)
    java_file = tmp_path / "BadSyntax.java"
    java_file.write_text("public class BadSyntax { bad code here }\n", encoding="utf-8")

    mock_status = ToolchainStatus(
        id="java",
        name="Java",
        installed=True,
        version="javac 17.0.2",
        command_path="C:\\jdk\\bin\\java.exe",
        compile_command_path="C:\\jdk\\bin\\javac.exe",
        install_hint="Install JDK 17+",
    )

    mock_compile_proc = AsyncMock()
    mock_compile_proc.returncode = 1
    syntax_err = "BadSyntax.java:1: error: <identifier> expected\npublic class BadSyntax { bad code here }\n                             ^\n1 error"
    mock_compile_proc.communicate = AsyncMock(return_value=(b"", syntax_err.encode("utf-8")))

    with patch("app.features.terminal.run_service.check_toolchain_status", return_value=mock_status), \
         patch("app.features.terminal.run_service._find_executable", side_effect=lambda cmds: "C:\\jdk\\bin\\javac.exe" if "javac" in cmds else "C:\\jdk\\bin\\java.exe"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_compile_proc)):
        events = []
        async for packet in run_file_stream(ws, "BadSyntax.java"):
            events.append(packet)

        full_stream = "".join(events)
        assert "compiling" in full_stream
        assert "stderr" in full_stream
        assert "error: <identifier> expected" in full_stream
        assert "exit" in full_stream
        assert '"failure_reason": "exit_code"' in full_stream


@pytest.mark.asyncio
async def test_java_missing_jdk_run_stream(tmp_path):
    """Verify running a Java file without JDK emits not_found failure and installation guide."""
    ws = str(tmp_path)
    java_file = tmp_path / "SlidingPuzzle.java"
    java_file.write_text("public class SlidingPuzzle {}\n", encoding="utf-8")

    # In our test environment, javac is not in PATH
    events = []
    async for packet in run_file_stream(ws, "SlidingPuzzle.java"):
        events.append(packet)

    full_stream = "".join(events)
    assert "error" in full_stream
    assert "Java compiler (javac) not found" in full_stream
    assert '"failure_reason": "not_found"' in full_stream
    assert "adoptium.net" in full_stream
