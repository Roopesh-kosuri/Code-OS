import asyncio
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .schemas import (
    MCPServerConfig,
    MCPServerStatus,
    MCPToolDefinition,
    MCPCallRequest,
    MCPCallResponse,
)
from ..settings.service import get_setting, set_setting
from ..workspaces.service import get_last_workspace

logger = logging.getLogger(__name__)

CALL_TIMEOUT_SECONDS = 10.0
MAX_OUTPUT_BYTES = 100 * 1024  # 100 KB
STREAM_BUFFER_LIMIT = 4 * 1024 * 1024  # 4 MB line buffer for asyncio StreamReader
MAX_RESTART_ATTEMPTS = 3
MAX_LOG_LINES = 200


def is_tool_read_only(tool_name: str, description: str = "") -> bool:
    """Heuristic helper to classify whether an MCP tool is read-only (safe query) vs mutating."""
    name_lower = tool_name.lower()
    desc_lower = (description or "").lower()
    mutating_keywords = [
        "write", "create", "delete", "remove", "update", "modify", "execute",
        "run", "post", "put", "patch", "drop", "insert", "alter", "destroy", "set"
    ]
    for kw in mutating_keywords:
        if kw in name_lower or f" {kw} " in f" {desc_lower} ":
            return False

    read_keywords = ["read", "get", "fetch", "list", "search", "query", "find", "describe", "show", "inspect", "echo"]
    for kw in read_keywords:
        if kw in name_lower or f" {kw} " in f" {desc_lower} ":
            return True

    return False


class MCPServerInstance:
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.server_id = config.id
        self.status: str = "stopped"
        self.error_message: Optional[str] = None
        self.restart_count: int = 0
        self.protocol_version: str = "2024-11-05"
        self.tools: List[MCPToolDefinition] = []
        self.logs: List[str] = []
        self.process: Optional[asyncio.subprocess.Process] = None
        self.read_task: Optional[asyncio.Task] = None
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.request_counter: int = 0

    def _append_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        if len(self.logs) > MAX_LOG_LINES:
            self.logs = self.logs[-MAX_LOG_LINES:]

    def _get_isolated_env(self) -> Dict[str, str]:
        """Produce safe execution environment without leaking host process API keys."""
        safe_keys = [
            "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC",
            "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
            "HOMEDRIVE", "HOMEPATH", "HOME", "ProgramFiles", "ProgramFiles(x86)",
            "CommonProgramFiles", "ALLUSERSPROFILE", "PUBLIC"
        ]
        isolated_env = {}
        for k in safe_keys:
            if k in os.environ:
                isolated_env[k] = os.environ[k]
        isolated_env["PYTHONUNBUFFERED"] = "1"
        if self.config.env:
            isolated_env.update(self.config.env)
        return isolated_env

    async def start(self) -> bool:
        if self.status == "running" and self.process:
            return True

        if self.config.type == "http":
            return await self._start_http()

        return await self._start_stdio()

    async def _start_http(self) -> bool:
        self.status = "starting"
        self._append_log(f"Connecting to HTTP MCP server at {self.config.url}...")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(
                    self.config.url or "",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {}}
                    }
                )
                if res.status_code == 200:
                    self.status = "running"
                    self.error_message = None
                    self._append_log("HTTP connection established and initialized.")
                    await self._discover_tools()
                    return True
                else:
                    self.status = "error"
                    self.error_message = f"HTTP status {res.status_code}"
                    self._append_log(f"HTTP connection failed with status {res.status_code}")
                    return False
        except Exception as exc:
            self.status = "error"
            self.error_message = str(exc)
            self._append_log(f"HTTP connection failed: {exc}")
            return False

    async def _start_stdio(self) -> bool:
        self.status = "starting"
        self.error_message = None
        self._append_log(f"Starting stdio MCP server: {self.config.command} {' '.join(self.config.args)}")

        try:
            env = self._get_isolated_env()
            args = list(self.config.args)
            if self.server_id in ["filesystem", "git"] and not any(os.path.isabs(a) for a in args):
                last_ws = await get_last_workspace()
                ws_path = last_ws.path if last_ws else os.getcwd()
                args.append(ws_path)

            cmd = self.config.command
            if "python" in Path(cmd).name.lower() and "-u" not in args:
                args = ["-u"] + args

            resolved_cmd = shutil.which(cmd) or cmd

            # On Windows, if executable is a .cmd/.bat script or binary name, use create_subprocess_shell or direct exec
            if sys.platform == "win32" and (resolved_cmd.lower().endswith((".cmd", ".bat")) or not Path(resolved_cmd).suffix):
                full_cmd = f'"{resolved_cmd}" ' + " ".join(f'"{a}"' for a in args)
                self.process = await asyncio.create_subprocess_shell(
                    full_cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=STREAM_BUFFER_LIMIT,
                    env=env
                )
            else:
                try:
                    self.process = await asyncio.create_subprocess_exec(
                        resolved_cmd,
                        *args,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        limit=STREAM_BUFFER_LIMIT,
                        env=env
                    )
                except Exception:
                    full_cmd = f'"{resolved_cmd}" ' + " ".join(f'"{a}"' for a in args)
                    self.process = await asyncio.create_subprocess_shell(
                        full_cmd,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        limit=STREAM_BUFFER_LIMIT,
                        env=env
                    )

            self.read_task = asyncio.create_task(self._read_loop())
            self.status = "running"
            self._append_log(f"Subprocess spawned with PID {self.process.pid}.")

            handshake_ok = await self._perform_handshake()
            if not handshake_ok:
                await self.stop()
                self.status = "error"
                return False

            await self._discover_tools()
            return True

        except Exception as exc:
            logger.error("mcp.instance.start failed for server %s: %s", self.server_id, exc)
            self.status = "error"
            self.error_message = str(exc)
            self._append_log(f"Failed to spawn process: {exc}")
            self.process = None
            return False

    async def _perform_handshake(self) -> bool:
        try:
            self._append_log("Sending JSON-RPC initialize handshake...")
            init_res = await self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {"listChanged": True},
                    "sampling": {}
                },
                "clientInfo": {
                    "name": "Code-OS",
                    "version": "2.4.0"
                }
            })
            if "error" in init_res:
                err_msg = init_res["error"].get("message", "Unknown initialize error")
                self._append_log(f"Initialize rejected: {err_msg}")
                self.error_message = err_msg
                return False

            if "result" in init_res:
                self.protocol_version = init_res["result"].get("protocolVersion", "2024-11-05")

            self._append_log("Handshake successful. Sending notifications/initialized...")
            await self.send_notification("notifications/initialized", {})
            return True
        except Exception as exc:
            self._append_log(f"Handshake failed: {exc}")
            self.error_message = str(exc)
            return False

    async def _discover_tools(self):
        try:
            self._append_log("Discovering tools via tools/list...")
            res = await self.send_request("tools/list", {})
            if "result" in res and "tools" in res["result"]:
                raw_tools = res["result"]["tools"]
                parsed_tools = []
                for t in raw_tools:
                    name = t.get("name", "")
                    desc = t.get("description", "")
                    schema = t.get("inputSchema", {})
                    read_only = is_tool_read_only(name, desc)
                    parsed_tools.append(MCPToolDefinition(
                        server_id=self.server_id,
                        name=name,
                        namespaced_name=f"mcp__{self.server_id}__{name}",
                        description=desc,
                        input_schema=schema,
                        read_only=read_only
                    ))
                self.tools = parsed_tools
                self._append_log(f"Discovered {len(self.tools)} tool(s).")
        except Exception as exc:
            self._append_log(f"Tool discovery failed: {exc}")
            self.tools = []

    async def stop(self):
        self._append_log("Stopping server...")
        self.status = "stopped"
        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except (asyncio.CancelledError, Exception):
                pass
            self.read_task = None

        if self.process:
            try:
                if self.process.stdin:
                    try:
                        self.process.stdin.close()
                    except Exception:
                        pass
                self.process.kill()
                await asyncio.wait_for(self.process.wait(), timeout=1.0)
            except Exception:
                pass
            self.process = None

        for req_id, fut in list(self.pending_requests.items()):
            if not fut.done():
                fut.set_exception(RuntimeError("MCP server stopped"))
        self.pending_requests.clear()
        self._append_log("Server stopped.")

    async def restart(self) -> bool:
        self.restart_count = 0
        await self.stop()
        return await self.start()

    async def _read_loop(self):
        try:
            while self.process and self.process.stdout:
                line_bytes = await self.process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                self._append_log(f"<< {line[:300]}")

                try:
                    data = json.loads(line)
                    if "id" in data:
                        req_id = data["id"]
                        if req_id in self.pending_requests:
                            fut = self.pending_requests.pop(req_id)
                            if not fut.done():
                                fut.set_result(data)
                except json.JSONDecodeError:
                    pass

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("mcp.read_loop error for %s: %s", self.server_id, exc)
        finally:
            if self.status == "running":
                await self._handle_crash()

    async def _handle_crash(self):
        self._append_log("Process terminated unexpectedly.")
        self.restart_count += 1
        if self.restart_count <= MAX_RESTART_ATTEMPTS:
            self._append_log(f"Auto-restart attempt {self.restart_count}/{MAX_RESTART_ATTEMPTS}...")
            await asyncio.sleep(1.0)
            await self.start()
        else:
            self.status = "crashed"
            self.error_message = f"Server crashed repeatedly (exceeded {MAX_RESTART_ATTEMPTS} auto-restart limit)"
            self._append_log(self.error_message)

    async def send_notification(self, method: str, params: Dict[str, Any]):
        if self.config.type == "http":
            return
        if not self.process or not self.process.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        raw_data = json.dumps(payload) + "\n"
        self.process.stdin.write(raw_data.encode("utf-8"))
        await self.process.stdin.drain()

    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.config.type == "http":
            return await self._send_http_request(method, params)

        if not self.process or not self.process.stdin:
            raise RuntimeError(f"MCP server '{self.server_id}' process is not running.")

        self.request_counter += 1
        req_id = self.request_counter
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending_requests[req_id] = fut

        raw_data = json.dumps(payload) + "\n"
        self._append_log(f">> {raw_data[:200].strip()}")
        self.process.stdin.write(raw_data.encode("utf-8"))
        await self.process.stdin.drain()

        try:
            res = await asyncio.wait_for(fut, timeout=CALL_TIMEOUT_SECONDS)
            return self._enforce_output_cap(res)
        except asyncio.TimeoutError:
            if req_id in self.pending_requests:
                del self.pending_requests[req_id]
            raise TimeoutError(f"MCP Server request timeout (10s limit exceeded for '{method}')")

    async def _send_http_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.request_counter += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_counter,
            "method": method,
            "params": params
        }
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT_SECONDS) as client:
            res = await client.post(self.config.url or "", json=payload)
            if res.status_code != 200:
                raise RuntimeError(f"HTTP MCP error: status {res.status_code}")
            return self._enforce_output_cap(res.json())

    def _enforce_output_cap(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        if "result" in response_data and "content" in response_data["result"]:
            contents = response_data["result"]["content"]
            if isinstance(contents, list):
                for item in contents:
                    if isinstance(item, dict) and "text" in item:
                        raw_text = item["text"]
                        if len(raw_text.encode("utf-8")) > MAX_OUTPUT_BYTES:
                            truncated = raw_text[:MAX_OUTPUT_BYTES] + "\n... [MCP Output Truncated at 100KB]"
                            item["text"] = truncated
        return response_data

    def get_status(self) -> MCPServerStatus:
        return MCPServerStatus(
            id=self.server_id,
            name=self.config.name,
            type=self.config.type,
            status=self.status if self.status in ["running", "stopped", "crashed", "starting", "error"] else "stopped",  # type: ignore
            enabled=self.config.enabled,
            restart_count=self.restart_count,
            tool_count=len(self.tools),
            error=self.error_message,
            command=self.config.command,
            args=self.config.args,
            env=self.config.env,
            url=self.config.url,
            auto_approve_read_only=self.config.auto_approve_read_only
        )


class MCPManager:
    def __init__(self):
        self.instances: Dict[str, MCPServerInstance] = {}
        self.default_configs: Dict[str, MCPServerConfig] = {
            "filesystem": MCPServerConfig(
                id="filesystem",
                name="Filesystem MCP",
                type="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem"],
                enabled=False,
                auto_approve_read_only=True
            ),
            "git": MCPServerConfig(
                id="git",
                name="Git MCP",
                type="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-git"],
                enabled=False,
                auto_approve_read_only=True
            ),
        }

    async def load_configs(self) -> Dict[str, MCPServerConfig]:
        raw = await get_setting("mcp_servers_config")
        configs = dict(self.default_configs)
        if raw:
            try:
                saved = json.loads(raw)
                if isinstance(saved, list):
                    for item in saved:
                        cfg = MCPServerConfig(**item)
                        configs[cfg.id] = cfg
            except Exception as e:
                logger.warning("mcp.load_configs parse error: %s", e)
        return configs

    async def save_configs(self, configs: Dict[str, MCPServerConfig]):
        serialized = [cfg.model_dump() for cfg in configs.values()]
        await set_setting("mcp_servers_config", json.dumps(serialized))

    async def initialize_servers(self):
        configs = await self.load_configs()
        for server_id, cfg in configs.items():
            if cfg.enabled:
                instance = MCPServerInstance(cfg)
                self.instances[server_id] = instance
                asyncio.create_task(instance.start())

    async def register_server(self, config: MCPServerConfig) -> MCPServerStatus:
        configs = await self.load_configs()
        configs[config.id] = config
        await self.save_configs(configs)

        if config.id in self.instances:
            await self.instances[config.id].stop()

        instance = MCPServerInstance(config)
        self.instances[config.id] = instance
        if config.enabled:
            await instance.start()

        return instance.get_status()

    async def remove_server(self, server_id: str) -> bool:
        configs = await self.load_configs()
        if server_id not in configs:
            return False

        del configs[server_id]
        await self.save_configs(configs)

        if server_id in self.instances:
            await self.instances[server_id].stop()
            del self.instances[server_id]
        return True

    async def enable_server(self, server_id: str) -> bool:
        configs = await self.load_configs()
        if server_id not in configs:
            return False

        configs[server_id].enabled = True
        await self.save_configs(configs)

        if server_id not in self.instances:
            self.instances[server_id] = MCPServerInstance(configs[server_id])
        else:
            self.instances[server_id].config.enabled = True

        return await self.instances[server_id].start()

    async def disable_server(self, server_id: str) -> bool:
        configs = await self.load_configs()
        if server_id not in configs:
            return False

        configs[server_id].enabled = False
        await self.save_configs(configs)

        if server_id in self.instances:
            self.instances[server_id].config.enabled = False
            await self.instances[server_id].stop()
        return True

    async def restart_server(self, server_id: str) -> bool:
        if server_id not in self.instances:
            configs = await self.load_configs()
            if server_id not in configs:
                return False
            self.instances[server_id] = MCPServerInstance(configs[server_id])
        return await self.instances[server_id].restart()

    async def list_server_statuses(self) -> List[MCPServerStatus]:
        configs = await self.load_configs()
        statuses = []
        for server_id, cfg in configs.items():
            if server_id in self.instances:
                statuses.append(self.instances[server_id].get_status())
            else:
                statuses.append(MCPServerStatus(
                    id=server_id,
                    name=cfg.name,
                    type=cfg.type,
                    status="stopped",
                    enabled=cfg.enabled,
                    command=cfg.command,
                    args=cfg.args,
                    env=cfg.env,
                    url=cfg.url,
                    auto_approve_read_only=cfg.auto_approve_read_only
                ))
        return statuses

    def get_all_tools(self) -> List[MCPToolDefinition]:
        all_tools = []
        for instance in self.instances.values():
            if instance.status == "running":
                all_tools.extend(instance.tools)
        return all_tools

    async def call_tool(self, namespaced_tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        parts = namespaced_tool_name.split("__")
        if len(parts) < 3 or parts[0] != "mcp":
            raise ValueError(f"Invalid namespaced tool name: '{namespaced_tool_name}' (expected mcp__<server>__<tool>)")

        server_id = parts[1]
        raw_tool_name = "__".join(parts[2:])

        if server_id not in self.instances:
            raise RuntimeError(f"MCP server '{server_id}' is not active.")

        instance = self.instances[server_id]
        if instance.status != "running":
            raise RuntimeError(f"MCP server '{server_id}' status is '{instance.status}', not running.")

        res = await instance.send_request("tools/call", {
            "name": raw_tool_name,
            "arguments": arguments
        })

        if "error" in res:
            return {
                "content": [{"type": "text", "text": res["error"].get("message", "Tool execution error")}],
                "is_error": True
            }

        result_obj = res.get("result", {})
        return {
            "content": result_obj.get("content", []),
            "is_error": result_obj.get("isError", False)
        }

    async def shutdown(self):
        for instance in list(self.instances.values()):
            await instance.stop()
        self.instances.clear()


mcp_manager = MCPManager()
