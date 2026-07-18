# Model Context Protocol (MCP) Integration Guide

CODE OS natively supports the Model Context Protocol (MCP) to allow tools and context to be dynamically queried by AI systems.

## Mounting Custom MCP Servers

MCP servers are spawned as independent standard streams (stdio) subprocesses managed by `MCPManager` inside the FastAPI backend.

### 1. Default Pre-Configured MCP Servers
- **Filesystem MCP**: Integrates filesystem access with model actions.
- **Git MCP**: Exposes Git diff summaries, branches, and logs directly to context builders.

### 2. Adding a Custom Server via Config
You can register a custom server by modifying the database settings key `mcp_status_<server_id>` or registering it in `mcp_manager.py`:

```python
# In mcp_manager.py:
self.default_configs["database_mcp"] = {
    "name": "Database MCP",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost:5432"]
}
```

### 3. Execution Pipeline

When an MCP server is toggled `on`:
1. `MCPManager` launches the subprocess over stdio.
2. Standard input is used to write JSON-RPC payloads (e.g., `list_tools`, `call_tool`).
3. Standard output returns JSON-RPC response logs.
4. If a connection drops, the process is terminated and automatically restarted upon next usage.
