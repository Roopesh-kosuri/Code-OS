# CODE OS Product Roadmap

## Completed Milestones

### Phase 1 — Desktop Workspace
- Local-first file tree rendering.
- Integrated Xterm terminal shells with full PTY support (interactive programs, vim, long-running processes).
- Monaco Editor workspaces.

### Phase 2 — Project Indexing
- SQLite index mapping for symbols, imports, and file trees.
- Watchdog workspace listeners.

### Phase 3 — Coordinated Multi-Agent platform
- Multi-agent orchestration (Planner, Coder, Reviewer, Tester, Documenter).
- SQLite-based job routing queues.

---

## Active & Upcoming Goals (Phase 4 & Beyond)

### 1. Extensibility Hub (In Progress)
- Native manifest loader from `~/.codeos/extensions`.
- Diagnostics dashboard panel with realtime resource updates and AI pricing models.

### 2. Isolated Sandboxes (Upcoming)
- Restrict plugin execution contexts utilizing lightweight Docker sandboxes or restricted Python AST execution layers.

### 3. Remote Development (Upcoming)
- Full SSH/SFTP workspace synchronization and remote folder mountings for remote servers and Docker containers.
