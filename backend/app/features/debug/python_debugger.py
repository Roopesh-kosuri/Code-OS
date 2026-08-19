"""A resource-governed debugpy process launcher and minimal DAP WebSocket bridge."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ...core.auth import get_token
from ...core.paths import normalize_path
from ..ai.sandbox.executor import MAX_COMMAND_MEMORY_BYTES, MAX_COMMAND_TIMEOUT_SECONDS, _monitor_process_governor

router = APIRouter()
websocket_router = APIRouter()


class DebugStartRequest(BaseModel):
    file_path: str
    args: list[str] = Field(default_factory=list)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class DebugSession:
    process: asyncio.subprocess.Process
    port: int
    governor_task: asyncio.Task[tuple[bool, str]]
    timeout_task: asyncio.Task[None]
    output_task: asyncio.Task[None]
    created_at: float = field(default_factory=time.monotonic)


_sessions: dict[int, DebugSession] = {}


async def _discard_output(stream: asyncio.StreamReader | None) -> None:
    if stream is None:
        return
    while await stream.read(8192):
        pass


async def _enforce_timeout(process: asyncio.subprocess.Process) -> None:
    await asyncio.sleep(MAX_COMMAND_TIMEOUT_SECONDS)
    if process.returncode is None:
        process.kill()


async def _terminate(session: DebugSession) -> None:
    if session.process.returncode is None:
        session.process.kill()
        await session.process.wait()
    for task in (session.governor_task, session.timeout_task, session.output_task):
        if not task.done():
            task.cancel()


async def _reap_session(process_id: int, session: DebugSession) -> None:
    await session.process.wait()
    for task in (session.governor_task, session.timeout_task, session.output_task):
        if not task.done():
            task.cancel()
    _sessions.pop(process_id, None)


async def start_debugger(payload: DebugStartRequest) -> dict[str, int]:
    file_path = normalize_path(payload.file_path)
    if not file_path.is_file() or file_path.suffix.lower() != ".py":
        raise HTTPException(status_code=400, detail="Debugging requires an existing Python file")

    port = _free_local_port()
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "debugpy", "--listen", f"127.0.0.1:{port}", "--wait-for-client",
        str(file_path), *payload.args,
        cwd=str(file_path.parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    session = DebugSession(
        process=process,
        port=port,
        governor_task=asyncio.create_task(_monitor_process_governor(process, max_memory_bytes=MAX_COMMAND_MEMORY_BYTES)),
        timeout_task=asyncio.create_task(_enforce_timeout(process)),
        output_task=asyncio.create_task(_discard_output(process.stdout)),
    )
    _sessions[process.pid] = session
    asyncio.create_task(_discard_output(process.stderr))
    asyncio.create_task(_reap_session(process.pid, session))
    return {"debug_port": port, "process_id": process.pid}


class DapClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.sequence = 1
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.thread_id: int | None = None
        self.configured = False
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.reader_task = asyncio.create_task(self._read_messages())

    async def _read_messages(self) -> None:
        try:
            while True:
                headers: dict[str, str] = {}
                while True:
                    line = await self.reader.readline()
                    if not line:
                        return
                    if line == b"\r\n":
                        break
                    key, value = line.decode("ascii").split(":", 1)
                    headers[key.lower()] = value.strip()
                body = await self.reader.readexactly(int(headers["content-length"]))
                message = json.loads(body)
                if message.get("type") == "response":
                    future = self.pending.pop(message.get("request_seq"), None)
                    if future and not future.done():
                        future.set_result(message)
                else:
                    if message.get("event") == "stopped":
                        self.thread_id = message.get("body", {}).get("threadId")
                    await self.events.put(message)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Debug adapter disconnected"))

    async def request(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        sequence = self.sequence
        self.sequence += 1
        message = {"seq": sequence, "type": "request", "command": command, "arguments": arguments or {}}
        data = json.dumps(message).encode("utf-8")
        self.writer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
        await self.writer.drain()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[sequence] = future
        return await asyncio.wait_for(future, timeout=10)

    async def send_request(self, command: str, arguments: dict[str, Any] | None = None) -> None:
        sequence = self.sequence
        self.sequence += 1
        message = {"seq": sequence, "type": "request", "command": command, "arguments": arguments or {}}
        data = json.dumps(message).encode("utf-8")
        self.writer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
        await self.writer.drain()

    async def close(self) -> None:
        self.reader_task.cancel()
        self.writer.close()
        await self.writer.wait_closed()


async def _connect_dap(port: int) -> DapClient:
    for _ in range(50):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            client = DapClient(reader, writer)
            await client.request("initialize", {"clientID": "code-os", "adapterID": "python", "pathFormat": "path", "linesStartAt1": True, "columnsStartAt1": True})
            await client.send_request("attach", {"justMyCode": True})
            return client
        except (ConnectionError, OSError):
            await asyncio.sleep(0.1)
    raise HTTPException(status_code=503, detail="Python debug adapter did not start")


async def _variables(client: DapClient) -> dict[str, Any]:
    threads = (await client.request("threads")).get("body", {}).get("threads", [])
    thread_id = client.thread_id or (threads[0]["id"] if threads else None)
    if thread_id is None:
        return {"locals": [], "globals": []}
    frames = (await client.request("stackTrace", {"threadId": thread_id})).get("body", {}).get("stackFrames", [])
    if not frames:
        return {"locals": [], "globals": []}
    scopes = (await client.request("scopes", {"frameId": frames[0]["id"]})).get("body", {}).get("scopes", [])
    result: dict[str, Any] = {}
    for scope in scopes:
        values = await client.request("variables", {"variablesReference": scope["variablesReference"]})
        result[scope["name"].lower()] = values.get("body", {}).get("variables", [])
    return result


async def _handle_command(client: DapClient, session: DebugSession, message: dict[str, Any]) -> dict[str, Any]:
    command = message.get("command")
    if command == "set_breakpoint":
        result = await client.request("setBreakpoints", {"source": {"path": message["file_path"]}, "breakpoints": [{"line": int(line)} for line in message.get("lines", [])]})
        if not client.configured:
            await client.request("configurationDone")
            client.configured = True
        return result
    if not client.configured:
        await client.request("configurationDone")
        client.configured = True
    if command == "continue":
        return await client.request("continue", {"threadId": client.thread_id})
    if command == "step_over":
        return await client.request("next", {"threadId": client.thread_id})
    if command == "step_in":
        return await client.request("stepIn", {"threadId": client.thread_id})
    if command == "step_out":
        return await client.request("stepOut", {"threadId": client.thread_id})
    if command == "get_stack":
        return await client.request("stackTrace", {"threadId": client.thread_id})
    if command == "get_variables":
        return {"body": await _variables(client)}
    if command == "stop":
        await _terminate(session)
        return {"success": True}
    raise HTTPException(status_code=400, detail="Unsupported debug command")


@router.post("/start")
async def start(payload: DebugStartRequest) -> dict[str, int]:
    return await start_debugger(payload)


@websocket_router.websocket("/ws/debug/{process_id}")
async def debug_websocket(websocket: WebSocket, process_id: int) -> None:
    if websocket.query_params.get("token") != get_token():
        await websocket.close(code=4401)
        return
    session = _sessions.get(process_id)
    if not session or session.process.returncode is not None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    client = await _connect_dap(session.port)
    try:
        while True:
            incoming = asyncio.create_task(websocket.receive_json())
            event = asyncio.create_task(client.events.get())
            done, pending = await asyncio.wait((incoming, event), return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            if event in done:
                await websocket.send_json({"type": "event", "event": event.result()})
            if incoming in done:
                result = await _handle_command(client, session, incoming.result())
                await websocket.send_json({"type": "response", "command": incoming.result().get("command"), "result": result})
    except WebSocketDisconnect:
        pass
    finally:
        await client.close()
