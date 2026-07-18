# CODE OS System Architecture

CODE OS is a local-first, extensible AI-assisted development platform. It bridges a React frontend with a high-performance Python/FastAPI backend, wrapped inside an Electron shell to provide a seamless desktop experience.

```mermaid
graph TD
    UI[React & Tailwind Frontend] -->|REST/WebSockets| BE[Python FastAPI Backend]
    Shell[Electron Shell] -->|Inter-Process Communication| UI
    
    subgraph Backend Services
        PM[Plugin Host Manager] -->|Loads| Exts[Dynamic Extensions]
        MCP[MCP Server Manager] -->|Stdio JSON-RPC| Servers[Git / FS MCP Servers]
        DB[SQLite Database]
        Diag[Diagnostics telemetry]
    end
    
    BE --> Backend Services
```

## Architectural Layers

### 1. Electron Container & Desktop Shell
- Serves as the native app container.
- Leverages OS capabilities (window management, native filesystem dialog fallbacks).
- Boots the concurrent development process (Uvicorn backend + Vite renderer).

### 2. React / Zustand Frontend
- A modern sidebar-driven IDE interface built with React, styled using Tailwind CSS, and managed by Zustand stores.
- Connects dynamically to backend REST endpoints and listens to the native IPC event bus.

### 3. FastAPI Python Backend
- Core orchestration API exposing REST and streaming endpoints.
- Houses features like search indexes, code reasoning engines, terminal sessions, Git control, settings configuration, and AI agent execution.

### 4. Extensions Host & Plugin Manager
- Dynamically loads code plugins from `~/.codeos/extensions` using structured `manifest.json` parameters.
- Maintains sandbox isolation policies for third-party scripts.

### 5. MCP (Model Context Protocol) Registry
- Spawns independent stdio-based subprocess connections for Git, Filesystem, and database MCP tools.
- Translates and forwards client JSON-RPC commands asynchronously over stdout/stdin channels.

### 6. Local SQLite Schema
- Handles persistent settings, workspace histories, search index mappings, symbols, and agent job queues.
