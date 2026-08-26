# Model Context Protocol (MCP) Integration Guide — Code-OS

Code-OS provides comprehensive, enterprise-grade support for the **Model Context Protocol (MCP)** specification (`2024-11-05`), dynamically empowering the Rony AI Agent with external tools, contextual retrieval, and remote services.

---

## 1. Architectural Overview

The MCP subsystem runs inside the Code-OS FastAPI backend (`backend/app/features/mcp/`) and communicates with the Electron/React desktop client via REST API and Server-Sent Events (SSE).

```
┌────────────────────────────────────────────────────────┐
│                   Code-OS Client                       │
│  - SettingsModal → MCP Servers (Status dots, Logs)     │
│  - Rony Agent Chat (Interactive Approval Cards)        │
└───────────────────────▲────────────────────────────────┘
                        │ HTTP / SSE
┌───────────────────────▼────────────────────────────────┐
│               FastAPI MCP Manager                      │
│  - Protocol Handshake (initialize / tools/list)        │
│  - Security & Restricted Mode Filter                   │
│  - Prompt-Injection Output Tagging                     │
│  - Lifecycle & Auto-Restart Recovery (3 attempts)      │
└───────────────▲────────────────────────▲───────────────┘
                │ stdio (Isolated Env)   │ HTTP Transport
┌───────────────▼──────────────┐ ┌───────▼───────────────┐
│     stdio MCP Subprocess     │ │   Remote HTTP Server  │
│  - Custom User Env Only      │ │   (e.g., /mcp URL)    │
│  - Host Secrets Stripped     │ │                       │
└──────────────────────────────┘ └───────────────────────┘
```

---

## 2. Strict Security Model (Non-Negotiable)

1. **Subprocess Environment Isolation**:
   - `stdio` servers spawn with explicit, sanitized environment variables only (`PATH`, `SYSTEMROOT`, `TEMP`, `USERPROFILE`) plus user-specified env vars.
   - **Host API keys and secrets (such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are NEVER inherited** by child processes.

2. **Interactive Approval Flow (Fail-Closed)**:
   - Tool calls from the Rony Agent require explicit user confirmation via an action approval card prior to execution.
   - Per-server configurable toggle: **`auto_approve_read_only`** allows auto-execution of safe read-only queries while enforcing interactive approval on mutating operations.

3. **Prompt Injection Defense**:
   - Tool outputs returned to LLMs are wrapped in `<untrusted_mcp_content server="..." tool="...">` tags to prevent jailbreaks and malicious directive execution.

4. **Restricted Mode Server-Side Enforcement**:
   - In untrusted workspaces, all mutating MCP tool calls are blocked server-side with HTTP 403.

5. **Resource Caps & Crash Recovery**:
   - **10.0s Hard Execution Timeout** per call.
   - **100KB Output Truncation Cap** (`[MCP Output Truncated at 100KB]`).
   - **Crash Recovery Loop**: Auto-restarts up to 3 times before transitioning to `crashed` state with error logging.

---

## 3. Server Configuration Schema

Server configurations are stored in the database settings table under `mcp_servers_config`:

```json
{
  "id": "filesystem",
  "name": "Local Filesystem",
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\workspace"],
  "env": {
    "NODE_ENV": "production"
  },
  "url": null,
  "enabled": true,
  "auto_approve_read_only": true
}
```

### Supported Transport Types
- **`stdio`**: Spawn local CLI binary via child process (`npx`, `uvx`, `python`, `node`).
- **`http`**: Connect to remote streamable HTTP server endpoint (`http://localhost:8000/mcp`).

---

## 4. Discovery Scanner (`scanner.py`)

The built-in Discovery Scanner parses external sources and proposes server configurations for explicit user confirmation without executing any commands during discovery:

- **Command Specs**: `Postgres:npx -y @modelcontextprotocol/server-postgres postgresql://localhost:5432`
- **GitHub Repositories**: Scans `README.md` and `package.json` for MCP packages (SSRF guarded to `github.com`).
- **JSON Schemas**: Validates Claude Desktop or Cursor `.mcp.json` / `.cursor-mcp.json` files.
- **Rate Limit**: Enforces max 5 scans per minute per workspace.

---

## 5. Pre-Configured Examples

### Example A: Filesystem MCP Server (Node / npx)
```bash
Command: npx
Arguments: -y @modelcontextprotocol/server-filesystem D:\PROJECTS\CODE OS
Auto-Approve Read-Only: Enabled
```

### Example B: SQLite Database MCP Server (Python / uvx)
```bash
Command: uvx
Arguments: mcp-server-sqlite --db-path ./app.db
Auto-Approve Read-Only: Enabled
```

### Example C: GitHub MCP Server (stdio with Token)
```bash
Command: npx
Arguments: -y @modelcontextprotocol/server-github
Environment:
  GITHUB_PERSONAL_ACCESS_TOKEN = ghp_xxxx
Auto-Approve Read-Only: Disabled
```

---

## 6. REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/mcp/servers` | `GET` | List all configured servers with health status and tool counts |
| `/api/mcp/servers` | `POST` | Add or update an MCP server configuration |
| `/api/mcp/servers/{id}` | `DELETE` | Remove a server and terminate its subprocess |
| `/api/mcp/servers/{id}/toggle` | `POST` | Enable or disable a server |
| `/api/mcp/servers/{id}/restart` | `POST` | Restart a server and reset crash recovery count |
| `/api/mcp/servers/{id}/tools` | `GET` | List discovered tools and input schemas for a server |
| `/api/mcp/servers/{id}/logs` | `GET` | Fetch last 200 lines of raw rolling logs |
| `/api/mcp/tools` | `GET` | List all tools across all active servers (`mcp__<server>__<tool>`) |
| `/api/mcp/call` | `POST` | Execute an MCP tool with Restricted Mode checks and output capping |
| `/api/mcp/scan` | `POST` | Scan GitHub, JSON, command specs, or workspace for server configs |
