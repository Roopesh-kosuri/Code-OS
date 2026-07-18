import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from backend.app.features.settings.service import list_settings, set_setting
from backend.app.features.workspaces.service import get_last_workspace

logger = logging.getLogger(__name__)

class MCPServerInstance:
    def __init__(self, server_id: str, command: str, args: List[str]):
        self.server_id = server_id
        self.command = command
        self.args = args
        self.process: Optional[asyncio.subprocess.Process] = None
        self.read_task: Optional[asyncio.Task] = None
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.request_counter = 0

    async def start(self) -> bool:
        if self.process:
            return True
        try:
            logger.info("mcp.instance.start starting server_id=%s with cmd=%s %s", self.server_id, self.command, self.args)
            
            # Check if command is 'npx' on Windows and locate it.
            # On Windows, create_subprocess_exec doesn't always automatically resolve batch files like 'npx' or 'npm'.
            # We can use a shell execution or resolve the executable name.
            # To be safe and robust, let's use create_subprocess_shell if running on Windows.
            import sys
            if sys.platform == "win32":
                full_cmd = f"{self.command} " + " ".join(f'"{a}"' for a in self.args)
                self.process = await asyncio.create_subprocess_shell(
                    full_cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL
                )
            else:
                self.process = await asyncio.create_subprocess_exec(
                    self.command,
                    *self.args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL
                )
            
            self.read_task = asyncio.create_task(self._read_loop())
            logger.info("mcp.instance.start started server_id=%s successfully", self.server_id)
            return True
        except Exception as e:
            logger.error("mcp.instance.start failed for server_id=%s: %s", self.server_id, e)
            self.process = None
            return False

    async def stop(self):
        logger.info("mcp.instance.stop stopping server_id=%s", self.server_id)
        if self.read_task:
            self.read_task.cancel()
            self.read_task = None
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception as e:
                logger.warning("mcp.instance.stop exception terminating server_id=%s: %s", self.server_id, e)
            self.process = None
        
        # Resolve all pending requests with error
        for req_id, fut in self.pending_requests.items():
            if not fut.done():
                fut.set_exception(RuntimeError("MCP server stopped"))
        self.pending_requests.clear()

    async def _read_loop(self):
        try:
            while self.process and self.process.stdout:
                line_bytes = await self.process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "id" in data:
                        req_id = data["id"]
                        if req_id in self.pending_requests:
                            self.pending_requests[req_id].set_result(data)
                            del self.pending_requests[req_id]
                except Exception as e:
                    logger.debug("mcp.instance.read_loop json parse error: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("mcp.instance.read_loop exception for server_id=%s: %s", self.server_id, e)

    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.process or not self.process.stdin:
            raise RuntimeError(f"MCP Server {self.server_id} is not running")

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
        self.process.stdin.write(raw_data.encode("utf-8"))
        await self.process.stdin.drain()
        
        try:
            # 15s timeout for MCP response
            res = await asyncio.wait_for(fut, timeout=15.0)
            return res
        except asyncio.TimeoutError:
            if req_id in self.pending_requests:
                del self.pending_requests[req_id]
            raise RuntimeError(f"MCP Server request timeout (method: {method})")


class MCPManager:
    def __init__(self):
        self.instances: Dict[str, MCPServerInstance] = {}
        # Predefined servers
        self.default_configs = {
            "filesystem": {
                "name": "Filesystem MCP",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem"]
            },
            "git": {
                "name": "Git MCP",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-git"]
            }
        }

    async def initialize_servers(self):
        settings = await list_settings()
        last_ws = await get_last_workspace()
        ws_path = last_ws.path if last_ws else str(Path.home())

        for server_id, cfg in self.default_configs.items():
            status_key = f"mcp_status_{server_id}"
            # Enabled by default unless specified
            is_enabled = settings.get(status_key, "enabled") == "enabled"
            
            if is_enabled:
                args = list(cfg["args"])
                if server_id == "filesystem":
                    # Append workspace path to filesystem arguments
                    args.append(ws_path)
                
                instance = MCPServerInstance(server_id, cfg["command"], args)
                self.instances[server_id] = instance
                await instance.start()

    async def enable_server(self, server_id: str) -> bool:
        if server_id not in self.default_configs:
            return False
            
        await set_setting(f"mcp_status_{server_id}", "enabled")
        
        # Stop existing if any
        if server_id in self.instances:
            await self.instances[server_id].stop()
            
        cfg = self.default_configs[server_id]
        last_ws = await get_last_workspace()
        ws_path = last_ws.path if last_ws else str(Path.home())
        
        args = list(cfg["args"])
        if server_id == "filesystem":
            args.append(ws_path)
            
        instance = MCPServerInstance(server_id, cfg["command"], args)
        self.instances[server_id] = instance
        success = await instance.start()
        return success

    async def disable_server(self, server_id: str) -> bool:
        if server_id not in self.default_configs:
            return False
            
        await set_setting(f"mcp_status_{server_id}", "disabled")
        if server_id in self.instances:
            await self.instances[server_id].stop()
            del self.instances[server_id]
        return True

    async def shutdown(self):
        for instance in list(self.instances.values()):
            await instance.stop()
        self.instances.clear()

    async def call_server(self, server_id: str, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if server_id not in self.instances:
            raise RuntimeError(f"MCP Server {server_id} is not enabled or running")
        return await self.instances[server_id].send_request(method, params)

mcp_manager = MCPManager()
