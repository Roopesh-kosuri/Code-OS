from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, Any, List

from backend.app.features.mcp.mcp_manager import mcp_manager
from backend.app.features.settings.service import list_settings

router = APIRouter()

class CallRequest(BaseModel):
    method: str
    params: Dict[str, Any] = {}

class ToggleRequest(BaseModel):
    enabled: bool

@router.get("/servers")
async def list_servers():
    settings = await list_settings()
    servers = []
    for server_id, cfg in mcp_manager.default_configs.items():
        status_key = f"mcp_status_{server_id}"
        enabled = settings.get(status_key, "enabled") == "enabled"
        is_running = server_id in mcp_manager.instances and mcp_manager.instances[server_id].process is not None
        servers.append({
            "id": server_id,
            "name": cfg["name"],
            "command": cfg["command"],
            "args": cfg["args"],
            "enabled": enabled,
            "running": is_running
        })
    return servers

@router.post("/servers/{server_id}/toggle")
async def toggle_server(server_id: str, req: ToggleRequest):
    if req.enabled:
        success = await mcp_manager.enable_server(server_id)
        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to start MCP server {server_id}")
        return {"status": "ok", "message": f"MCP server {server_id} started"}
    else:
        success = await mcp_manager.disable_server(server_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"MCP server {server_id} not found")
        return {"status": "ok", "message": f"MCP server {server_id} stopped"}

@router.post("/servers/{server_id}/call")
async def call_server(server_id: str, req: CallRequest):
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    from backend.app.features.workspaces.service import get_last_workspace
    
    last_ws = await get_last_workspace()
    workspace = last_ws.path if last_ws else None
    
    if workspace:
        trust = await get_workspace_trust(workspace)
        is_trusted = trust.get("trusted", False)
    else:
        is_trusted = False

    # If untrusted/Restricted, inspect the call and filter tools
    if not is_trusted:
        # We only filter actual tool executions (tools/call). 
        # Listing tools or other metadata query methods are read-only and allowed.
        if req.method == "tools/call":
            tool_name = req.params.get("name")
            if server_id == "filesystem":
                allowed_tools = ["read_file", "list_directory", "glob", "get_file_info", "search_grep", "view_file"]
                if tool_name not in allowed_tools:
                    raise HTTPException(
                        status_code=403, 
                        detail=f"Workspace is in Restricted Mode. MCP tool '{tool_name}' execution is blocked."
                    )
            elif server_id == "git":
                allowed_tools = ["git_status", "git_diff", "git_log", "git_show"]
                if tool_name not in allowed_tools:
                    raise HTTPException(
                        status_code=403, 
                        detail=f"Workspace is in Restricted Mode. MCP tool '{tool_name}' execution is blocked."
                    )
            else:
                # Block all tool calls for custom/unknown servers since their mutability cannot be verified.
                raise HTTPException(
                    status_code=403, 
                    detail="Workspace is in Restricted Mode. MCP tool execution is disabled for custom servers."
                )

    try:
        response = await mcp_manager.call_server(server_id, req.method, req.params)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
