from fastapi import APIRouter, HTTPException, Body, Query
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from .mcp_manager import mcp_manager
from .schemas import MCPServerConfig, MCPServerStatus, MCPToolDefinition, MCPCallRequest, MCPCallResponse
from .scanner import mcp_scanner, ScanRequest, ValidationResult
from ...core.trust import ensure_workspace_trusted as _ensure_trusted

router = APIRouter()


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("/servers", response_model=List[MCPServerStatus])
async def list_servers():
    """List all configured MCP servers and their real-time lifecycle/health statuses."""
    return await mcp_manager.list_server_statuses()


@router.post("/servers", response_model=MCPServerStatus)
async def register_server(config: MCPServerConfig):
    """Add or update an MCP server configuration."""
    return await mcp_manager.register_server(config)


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str):
    """Remove an MCP server configuration and stop its process."""
    success = await mcp_manager.remove_server(server_id)
    if not success:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"status": "ok", "message": f"Server {server_id} removed"}


@router.post("/servers/{server_id}/toggle")
async def toggle_server(server_id: str, req: ToggleRequest):
    """Enable or disable an MCP server."""
    if req.enabled:
        await mcp_manager.enable_server(server_id)
        instance = mcp_manager.instances.get(server_id)
        return {
            "status": "ok",
            "enabled": True,
            "server_status": instance.status if instance else "running",
            "error": instance.error_message if instance else None
        }
    else:
        await mcp_manager.disable_server(server_id)
        return {
            "status": "ok",
            "enabled": False,
            "server_status": "stopped",
            "error": None
        }


@router.post("/servers/{server_id}/restart")
async def restart_server(server_id: str):
    """Restart an MCP server and reset its crash counter."""
    await mcp_manager.restart_server(server_id)
    instance = mcp_manager.instances.get(server_id)
    return {
        "status": "ok",
        "message": f"MCP server {server_id} restarted",
        "server_status": instance.status if instance else "running",
        "error": instance.error_message if instance else None
    }


@router.get("/servers/{server_id}/tools", response_model=List[MCPToolDefinition])
async def list_server_tools(server_id: str):
    """List tools discovered from a specific running MCP server."""
    if server_id not in mcp_manager.instances:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found or not active")
    return mcp_manager.instances[server_id].tools


@router.get("/servers/{server_id}/logs")
async def get_server_logs(server_id: str):
    """Retrieve the rolling log buffer (last 200 lines) for an MCP server."""
    if server_id not in mcp_manager.instances:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")
    return {"server_id": server_id, "logs": list(mcp_manager.instances[server_id].logs)}


@router.get("/tools", response_model=List[MCPToolDefinition])
async def list_all_tools():
    """List all aggregated tools across all currently running MCP servers."""
    return mcp_manager.get_all_tools()


@router.post("/call", response_model=MCPCallResponse)
async def call_tool(req: MCPCallRequest):
    """Execute an MCP tool call with Restricted Mode mutability filtering and safety caps."""
    namespaced_name = req.tool_name
    parts = namespaced_name.split("__")
    if len(parts) < 3 or parts[0] != "mcp":
        raise HTTPException(status_code=400, detail=f"Invalid namespaced MCP tool: '{namespaced_name}'")

    server_id = parts[1]
    raw_tool_name = "__".join(parts[2:])

    # Restricted Mode verification
    if req.workspace:
        from ..workspaces.trust_service import get_workspace_trust
        trust = await get_workspace_trust(req.workspace)
        is_trusted = trust.get("trusted", False)

        if not is_trusted:
            if server_id in mcp_manager.instances:
                instance = mcp_manager.instances[server_id]
                tool_def = next((t for t in instance.tools if t.name == raw_tool_name), None)
                if not tool_def or not tool_def.read_only:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Workspace is in Restricted Mode. Mutating MCP tool '{namespaced_name}' is blocked."
                    )
            else:
                raise HTTPException(
                    status_code=403,
                    detail=f"Workspace is in Restricted Mode. MCP tool '{namespaced_name}' is blocked."
                )

    try:
        res = await mcp_manager.call_tool(namespaced_name, req.arguments)
        return MCPCallResponse(**res)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/scan", response_model=List[MCPServerConfig])
async def scan_mcp_servers(req: ScanRequest):
    """Scan GitHub repo, JSON file, command spec, or workspace for MCP server configs (read-only, no auto-exec)."""
    ws_key = req.workspace or "global"
    if not mcp_scanner.check_rate_limit(ws_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded: maximum 5 scans per minute allowed.")

    if req.source_type == "command_spec":
        cfg = mcp_scanner.scan_command_spec(req.target)
        return [cfg] if cfg else []

    elif req.source_type == "json_file":
        return mcp_scanner.scan_json_file(req.target)

    elif req.source_type == "workspace":
        return mcp_scanner.scan_workspace(req.target)

    elif req.source_type == "github":
        try:
            return await mcp_scanner.scan_github_repo(req.target)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return []
