<p align="center">
  <img src="public/codeos-logo.png" alt="CODE OS" width="360" />
</p>

# CODE OS — Local-First AI Development Workspace

[![Continuous Integration](https://github.com/Roopesh-kosuri/exoshield-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Roopesh-kosuri/exoshield-ai/actions/workflows/ci.yml)

> Full-featured AI-augmented IDE: **React + Monaco + FastAPI + Electron + SQLite** — 100% local, no cloud required.

## Quick Start

### Local Desktop Execution
```bash
npm install
pip install -r backend/requirements.txt
npm run dev
```

### Sandbox Execution in Docker
Build and start the containerized backend and frontend:
```bash
# Start container suite (binds ports 5173 and 8000)
docker-compose up --build
```
Place any code repositories you wish to edit inside the local `./project-workspace` folder. The container automatically mounts it at `/project-workspace` inside the workspace context.

- **Frontend** (Vite): http://127.0.0.1:5173  
- **Backend** (FastAPI): http://127.0.0.1:8000  
- **Health check**: http://127.0.0.1:8000/health

## What's Inside

| Feature | Status |
|---|---|
| Monaco code editor (multi-tab, split view, syntax highlighting) | WORKING |
| Multi-root workspace explorer (drag-drop, file ops) | WORKING |
| Real PTY terminal via node-pty (Electron) | WORKING |
| WebSocket terminal fallback (browser mode) | WORKING (limited) |
| Git: status, commit, push/pull, branch, history | WORKING |
| AI chat streaming (Ollama + 8 pre-configured API providers) | WORKING |
| Slash commands: /fix /refactor /explain /test /review... | WORKING |
| AI edit proposals (diff view, approve/reject, write to disk) | WORKING |
| Multi-agent orchestration (Planner, Coder, Reviewer, Tester, Documenter) | WORKING |
| Repository indexer (AST symbols, imports, deps) | WORKING |
| Text + symbol search with replace | WORKING |
| Light/dark theme (Monaco synced) | WORKING |
| Resizable panels (persist across reload) | WORKING |
| Settings + encrypted API keys | WORKING |
| Diagnostics dashboard (psutil: real CPU/RAM) | WORKING |
| MCP integration (Filesystem, Git servers) | WORKING |
| Plugin system (load from ~/.codeos/extensions/) | WORKING |
| SSH/Remote workspace | PLANNED |

## Supported AI Providers

CODE OS provides built-in integration presets for 9 local and cloud AI providers:
1. **Ollama** (100% offline local LLM hosting)
2. **OpenAI** (ChatGPT models including GPT-4o, o3-mini)
3. **Anthropic** (Claude 3.5 Sonnet / Claude 3 Opus)
4. **Google Gemini** (Gemini 2.5 Flash / Pro)
5. **Groq** (Low-latency hosting for open-weights models)
6. **DeepSeek** (DeepSeek-V3 / DeepSeek-R1)
7. **Mistral AI** (Mistral Large, Codestral)
8. **OpenRouter** (Unified routing portal to 100+ open/commercial models)
9. **NVIDIA NIM** (Accelerated hosting for open weights with self-hosted overrides)
*(Additionally, generic OpenAI-compatible custom endpoints are fully supported).*

## Full Documentation

See [FULL_README.md](./FULL_README.md) for:
- Complete project structure with every file explained
- Full API reference (all 50+ endpoints)
- Terminal architecture (Electron IPC vs WebSocket modes)
- AI system details (slash commands, proposal format, DAG engine)
- Database schema (all 13 tables)
- Theme system (CSS variables)
- Continuation guide for AI agents

## Scripts

```bash
npm run dev          # All three processes (backend + vite + electron)
npm run dev:backend  # FastAPI only (port 8000)
npm run dev:renderer # Vite only (port 5173)
npm run typecheck    # TypeScript check
npm run build        # Production build
```

## Tech Stack

**Frontend**: React 18, TypeScript, Tailwind CSS 3, Zustand 5, Monaco Editor, xterm.js, Vite 6  
**Backend**: Python 3.11+, FastAPI 0.115, aiosqlite, GitPython, psutil, cryptography, watchdog, httpx  
**Desktop**: Electron 33, node-pty 1.1
