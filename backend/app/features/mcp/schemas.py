from pydantic import BaseModel, Field
from typing import Literal, Dict, List, Optional, Any


class MCPServerConfig(BaseModel):
    id: str
    name: str
    type: Literal["stdio", "http"] = "stdio"
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None
    enabled: bool = True
    auto_approve_read_only: bool = False


class MCPServerStatus(BaseModel):
    id: str
    name: str
    type: Literal["stdio", "http"]
    status: Literal["running", "stopped", "crashed", "starting", "error"]
    enabled: bool
    restart_count: int = 0
    tool_count: int = 0
    error: Optional[str] = None
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None
    auto_approve_read_only: bool = False


class MCPToolDefinition(BaseModel):
    server_id: str
    name: str
    namespaced_name: str  # mcp__<server_id>__<name>
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False


class MCPCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    workspace: Optional[str] = None


class MCPCallResponse(BaseModel):
    content: List[Dict[str, Any]] = Field(default_factory=list)
    is_error: bool = False
    raw_output: str = ""
