# CODE OS — Complete Documentation

> Local-first AI development workspace: React + Monaco + FastAPI + Electron + SQLite

---

## Quick Start

```bash
npm install && pip install -r backend/requirements.txt
npm run dev
```

- Frontend: http://127.0.0.1:5173  
- Backend: http://127.0.0.1:8000

---

## Architecture

CODE OS is a three-layer local IDE stack:

**Layer 1: Electron Shell**
- Wraps the React frontend in a native desktop window
- Hosts node-pty for real PTY terminals via IPC
- Spawns the Python backend subprocess
- Provides native OS dialogs (open folder)

**Layer 2: React Frontend (Vite, port 5173)**
- Zustand stores for state management
- Monaco Editor for code editing
- xterm.js for terminal rendering
- Tailwind CSS with CSS variable theming

**Layer 3: FastAPI Backend (Python, port 8000)**
- All file operations, git, search, settings
- AI chat streaming (SSE) + agent orchestration
- SQLite via aiosqlite
- MCP server management (stdio JSON-RPC)

**Transport choices:**
- REST: all file/git/settings/AI endpoints
- SSE (StreamingResponse): AI chat token streaming
- WebSocket: terminal sessions only (real bidirectional I/O)
- Electron IPC: node-pty PTY (preferred when in Electron)

---

## Project File Map

```
CODE OS/
-- electron/
   -- main.ts              # PTY sessions, window, menus, IPC handlers
   -- preload.ts           # contextBridge.exposeInMainWorld('codeOS', ...)
   -- services/backendProcess.ts
-- backend/
   -- requirements.txt
   -- app/
      -- main.py           # FastAPI app + router registration
      -- core/
         -- config.py      # data_dir = ~/.codeos, db path
         -- paths.py       # normalize_path(), IGNORED_DIRS
         -- security.py    # Fernet API key encryption
         -- plugins/       # Plugin loader + manifest parser
      -- db/database.py    # SQLite schema init + get_connection()
      -- features/
         -- ai/
            -- routes.py          # /api/ai/*
            -- agent_routes.py    # /api/agents/*
            -- service.py         # stream_chat(), proposals, slash commands
            -- job_service.py     # SQLite job/task CRUD
            -- dag_engine.py      # Parallel DAG task runner (asyncio)
            -- event_bus.py       # Internal pub/sub
            -- context_service.py # Workspace context gathering
            -- providers/
               -- ollama.py
               -- openai_compatible.py
            -- agents/
               -- agent_factory.py, base.py
               -- planner.py, coder.py, reviewer.py, tester.py, documenter.py
               -- permission_state.py (human-in-the-loop approval)
         -- files/routes.py + service.py
         -- git/routes.py + service.py  (GitPython)
         -- indexing/routes.py + service.py + parsers.py
         -- search/routes.py
         -- settings/routes.py + service.py
         -- terminal/routes.py + service.py
         -- workspaces/routes.py + file_watcher.py (watchdog)
         -- diagnostics/routes.py  (psutil, wmic fallback)
         -- mcp/mcp_manager.py + routes.py
-- src/
   -- App.tsx              # Theme toggle, workspace restore, keyboard shortcuts
   -- styles.css           # CSS variables: dark/light token sets
   -- components/layout/
      -- AppShell.tsx      # Full layout, resize, panel visibility
      -- TopBar.tsx        # Utility panel toggle buttons
   -- features/
      -- ai/
         -- AIChatPanel.tsx    # Streaming chat, slash commands, file attach
         -- AgentConsole.tsx   # Plan -> approve -> job poll
         -- ContextPanel.tsx   # AI context inspector
         -- DiffViewer.tsx     # Edit proposal view/approve/reject
         -- MemoryPanel.tsx    # Per-workspace key-value memory
      -- diagnostics/PerformanceDashboard.tsx
      -- editor/EditorWorkspace.tsx  # Monaco tabs, split view
      -- explorer/
         -- FileExplorer.tsx          # Multi-root file tree
         -- RepoUnderstanding.tsx     # Language/deps/symbol browser
      -- git/GitPanel.tsx
      -- search/SearchPanel.tsx
      -- settings/SettingsPanel.tsx
      -- terminal/TerminalPanel.tsx   # xterm.js, Electron/WS routing
   -- stores/
      -- workspaceStore.ts  # selectWorkspaceForPath() - CRITICAL
      -- editorStore.ts     # openFile/saveFile/closeFile (call selectWorkspace)
      -- settingsStore.ts
      -- aiStore.ts
      -- indexStore.ts
   -- types/api.ts
-- tailwind.config.ts      # CSS variable color tokens
-- package.json
```

---

## Full API Reference

Base URL: http://127.0.0.1:8000

### /api/workspaces
- GET /api/workspaces — list all
- GET /api/workspaces/last — last opened
- POST /api/workspaces/open — {path}

### /api/files
- GET /api/files/tree — ?workspace=&max_depth=8
- GET /api/files/read — ?workspace=&path=
- POST /api/files/write — {workspace, path, content}
- POST /api/files/mkdir — {workspace, path}
- DELETE /api/files/delete — {workspace, path}
- POST /api/files/move — {workspace, source, destination}
- POST /api/files/duplicate — {workspace, path}

### /api/git
- GET /api/git/status — ?workspace=
- GET /api/git/diff — ?workspace=&path=
- POST /api/git/commit — {workspace, message} (auto stages all)
- POST /api/git/pull — {workspace}
- POST /api/git/push — {workspace} (auto sets upstream)
- POST /api/git/branch/switch — {workspace, branch}
- POST /api/git/branch/create — {workspace, branch}
- GET /api/git/history — ?workspace=&limit=30

### /api/terminal
- GET /api/terminal/sessions — list sessions
- POST /api/terminal/sessions — {cwd, shell?}
- POST /api/terminal/sessions/{id}/command — {command, background} (non-PTY legacy)
- POST /api/terminal/sessions/{id}/kill
- WS /api/terminal/ws — ?cwd=&session_id= (real WebSocket terminal)
  Input:  {type: 'input', data: '...'} or {type: 'resize', cols, rows}
  Output: raw ANSI text chunks

### /api/ai
- GET /api/ai/ollama/health — ?base_url=
- GET /api/ai/ollama/models
- POST /api/ai/chat/stream — ChatRequest (SSE response)
- GET /api/ai/edit-proposals — ?workspace=
- POST /api/ai/edit-proposals — {workspace, summary, changes[]}
- POST /api/ai/edit-proposals/{id}/apply — writes to disk
- POST /api/ai/edit-proposals/{id}/reject
- POST /api/ai/context — {workspace, active_path?, selection?, open_tabs?, query?}

ChatRequest body:
{
  messages: [{role, content}],
  model: 'llama3',
  provider: 'ollama|openai-compatible|auto',
  base_url: 'http://...',
  workspace: '/path',
  attached_paths: ['/path/to/file'],
  temperature: 0.7
}

### /api/agents
- POST /api/agents/plan — {workspace, user_request} -> task graph
- POST /api/agents/jobs — {workspace, workflow, tasks[]}
- GET /api/agents/jobs — ?workspace=
- GET /api/agents/jobs/{id} — job + tasks + progress %
- POST /api/agents/jobs/{id}/cancel
- POST /api/agents/jobs/{id}/tasks/{tid}/approve
- POST /api/agents/jobs/{id}/tasks/{tid}/reject

### /api/search
- POST /api/search/text — {workspace, query, regex, case_sensitive, whole_word}
- POST /api/search/symbols — {workspace, query}
- POST /api/search/replace — {workspace, query, replacement, files[]}

### /api/index
- POST /api/index/schedule — {workspace}
- GET /api/index/status — ?workspace=
- GET /api/index/summary — ?workspace=

### /api/settings
- GET /api/settings
- POST /api/settings/{key} — {value}
- GET|POST|DELETE /api/settings/api-keys/{provider}
- GET|POST|DELETE /api/settings/memory — ?workspace= / {workspace, key, value}

### /api/diagnostics
- GET /api/diagnostics/metrics -> {system: {cpu, ram, threads, jobs}, ai: {tokens, latency, cost}, plugins: {count, load_times}}

### /api/mcp
- GET /api/mcp/servers
- POST /api/mcp/servers/{id}/enable|disable
- POST /api/mcp/call — {server_id, method, params}

### /api/plugins
- GET /api/plugins

---

## SQLite Schema (at ~/.codeos/codeos.db)

workspaces: id, path (UNIQUE), name, last_opened_at, is_active
settings: key (PK), value
api_keys: provider_id (PK), encrypted_key, updated_at
edit_proposals: id (PK), workspace, status(pending|applied|rejected), payload(JSON), created_at
repo_index_status: workspace (PK), status, message, started_at, completed_at, total_files, indexed_files, project_type, language_summary, frameworks, entry_points
repo_index_files: (workspace, path) PK, relative_path, language, size, mtime_ns, content_hash, symbol_count, imports_json
repo_symbols: id (PK), workspace, path, name, kind, language, line, column, signature, parent
repo_import_edges: (workspace, source_path, module) PK, target_path, kind
repo_dependencies: (workspace, name, source) PK, version
repo_folders: (workspace, path) PK, relative_path, file_count, folder_count
repo_memory: (workspace, key) PK, value, updated_at
agent_jobs: id (PK), workspace, workflow, status, started_at, completed_at, token_usage, duration, files_modified, errors, logs
agent_tasks: id (PK), job_id (FK), title, agent_role, status, dependencies, assigned_agent, reasoning_summary, estimated_effort, started_at, completed_at, pending_action, structured_data

---

## Terminal Architecture Detail

The terminal uses two modes, automatically selected:

ELECTRON MODE (window.codeOS exists):
- electron/main.ts spawns node-pty PTY process
- resolveShell(): pwsh.exe > powershell.exe > cmd.exe (Win) or  (Unix)
- IPC: terminal:create(cwd) -> id; terminal:write(id, data); terminal:resize(id, cols, rows); terminal:kill(id)
- Output arrives via window.codeOS.onTerminalOutput(id, callback)
- FULL PTY: vim, htop, npm run dev, git rebase -i all work
- Sessions in terminalSessions Map in main process
- before-quit kills all sessions

WEBSOCKET MODE (window.codeOS missing = browser):
- backend/app/features/terminal/service.py:create_pty_session()
- subprocess.Popen([pwsh.exe, -NoLogo, -NoProfile, -Command, -], cwd=cwd, stdin=PIPE, stdout=PIPE, stderr=STDOUT)
- Background reader thread -> output_queue -> asyncio drain task -> WebSocket
- Input from WebSocket JSON {type:'input', data:'...'} -> proc.stdin.write()
- NOT a real PTY: vim/interactive programs won't work correctly
- Sessions in pty_sessions dict in service.py

Frontend session lifecycle (TerminalPanel.tsx):
- Module-scope sessions Map<string, TermSession> - survives React re-renders
- detachSession(session): removes xterm DOM element, disconnects ResizeObserver
- attachSession(session, container): re-mounts xterm, reconnects ResizeObserver
- Panel hide -> detachSession (process KEEPS running)
- Panel show -> attachSession (reconnects to same process)
- Kill button -> ws.close() or codeOS.terminalKill()

---

## AI System Detail

SLASH COMMANDS (prepend system prompts):
/explain - code explanation
/fix - bug finding + [PROPOSAL] block
/refactor - refactoring [PROPOSAL]
/document - docstrings [PROPOSAL]
/test - test generation [PROPOSAL]
/review - code review
/optimize - performance [PROPOSAL]
/rename - symbol rename [PROPOSAL]
/commit - auto-fetches git diff -> commit message

PROPOSAL FORMAT (parsed by PROPOSAL_RE in service.py):
[PROPOSAL: path/to/file.py]
<<<<
old code to replace
====
new code
>>>>

After full SSE stream, backend parses and calls create_proposal() -> stores in edit_proposals SQLite table.

MULTI-AGENT DAG (dag_engine.py):
1. PlannerAgent.plan_task() returns JSON task graph [{id, title, agent_role, dependencies}]
2. create_job() + create_task() write to SQLite
3. dag_engine.start_job() -> asyncio.Task(_run_job())
4. _run_job() loop: find queued tasks with all deps completed -> asyncio.gather(execute_task...)
5. execute_task(): gather_context() + AgentFactory.create_agent(role).execute() -> AgentOutput
6. AgentOutput.proposals -> create_proposal() in SQLite
7. Frontend polls GET /api/agents/jobs/{id} every 2s

PERMISSION SYSTEM (permission_state.py):
- agent sets pending_permission_events[task_id] = asyncio.Event()
- agent awaits event
- User clicks approve/reject in AgentConsole UI
- API sets pending_permission_decisions[task_id] and event.set()
- Agent reads decision and continues

---

## Theme System

styles.css CSS variables:
:root { --bg-surface-950: #101215; ... --text-100: #f1f5f9; }
:root.light { --bg-surface-950: #ffffff; ... --text-100: #1f2328; }

tailwind.config.ts:
surface: { 950: 'var(--bg-surface-950)', ... }
slate: { 100: 'var(--text-100)', ... }

App.tsx reactive toggle:
theme ('dark'|'light'|'system') from settingsStore
-> document.documentElement.classList.toggle('light', isLight)

Monaco editor: theme={isLight ? 'vs' : 'vs-dark'}

---

## Continuation Guide for AI Agents

CRITICAL: Multi-workspace context lock
Every API call needs the right workspace= param. selectWorkspaceForPath(filePath) 
in workspaceStore.ts matches by path prefix to find the right workspace.
Called from: editorStore.openFile/saveFile/closeFile, EditorWorkspace tab clicks, FileExplorer actions.
If adding new file operations: call useWorkspaceStore.getState().selectWorkspaceForPath(path) first.

ADDING A BACKEND FEATURE:
1. Create backend/app/features/{name}/routes.py with router = APIRouter()
2. Import and register in backend/app/main.py
3. Add Pydantic schemas in schemas.py
4. Add service functions in service.py

ADDING A UI PANEL (right sidebar):
1. Create src/features/{name}/MyPanel.tsx
2. AppShell.tsx: add {activeUtility === 'myname' && <MyPanel />}
3. TopBar.tsx: add <IconButton> with toggle logic:
   if (activeUtility === 'myname' && showAI) { onToggleAI(false); }
   else { onUtilityChange('myname'); onToggleAI(true); }

ADDING NEW API TYPES:
Add to src/types/api.ts

PRIORITY IMPROVEMENTS:
1. WebSocket terminal -> real PTY:
   - Add pywinpty to requirements.txt
   - Replace subprocess.Popen with winpty.PtyProcess.spawn() in terminal/service.py
   - Handle ConPTY for true Windows terminal support

2. Search replace -> add confirmation modal in SearchPanel.tsx

3. Agent Console polling -> SSE:
   - Add GET /api/agents/jobs/{id}/stream SSE endpoint
   - Replace 2s setInterval with EventSource in AgentConsole.tsx

4. Git conflicts:
   - Detect MERGE_HEAD in git/service.py status()
   - Show conflict files in GitPanel.tsx
   - Add accept/reject UI for conflict markers

5. Settings MCP panel:
   - Add custom MCP server registration UI in SettingsPanel
   - Store custom servers in SQLite settings

KEY FILES TO UNDERSTAND FIRST:
- backend/app/main.py (all routes registered)
- src/stores/workspaceStore.ts (selectWorkspaceForPath - multi-workspace logic)
- src/stores/editorStore.ts (file open/save with workspace context)
- src/components/layout/AppShell.tsx (layout, panels, resize)
- src/features/terminal/TerminalPanel.tsx (Electron vs WS routing)
- backend/app/features/ai/service.py (chat, proposals, slash commands)
- backend/app/features/ai/dag_engine.py (agent orchestration)
- electron/main.ts (PTY management)

---
CODE OS Phase 1.5 - July 2026
