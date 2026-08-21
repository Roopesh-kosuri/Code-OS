<div align="center">

# CODE-OS

### A local-first AI IDE that plans, codes, and reviews your software — and never touches disk without your say-so.

[![CI/CD](./docs/badges/cicd.svg)](https://github.com/Roopesh-kosuri/Code-OS/actions/workflows/ci.yml)
[![License: PolyForm Noncommercial 1.0.0](./docs/badges/license.svg)](./License.md)
![Platform](./docs/badges/platform.svg)

![Made with Electron](./docs/badges/electron.svg)
![FastAPI](./docs/badges/fastapi.svg)

<br>

### ▶️ Demo

[![Watch the demo](https://img.youtube.com/vi/2LZ2V9nhz34/maxresdefault.jpg)](https://www.youtube.com/watch?v=2LZ2V9nhz34)

🌐 [**CODE OS Website**](https://roopesh-kosuri.github.io/websitecodeos/)

**[Getting Started](#-getting-started)** · **[Download](#-download)** · **[Features](#-what-it-can-do)** · **[Rony Agent](#-rony-agent--the-chat-harness)** · **[Architecture](#%EF%B8%8F-architecture)** · **[Security](#-security)** · **[Status](#-project-status)** · **[Docs](#-documentation)**

</div>

---

## ⚡ Why CODE OS

Most "AI IDEs" are a chat box bolted onto a text editor. CODE OS is built differently — it now runs **two distinct agent systems**, matched to the size of the task:

- 🧠 **5 specialized agents in Agent Console** — Planner, Coder, Reviewer, Tester, Documenter — for long, heavy, multi-step work. Full DAG planning, self-review, and test execution as one coordinated system.
- 💬 **Rony Agent — a fast, intelligent chat harness** — for everyday coding, entirely inside the chat panel: reads and edits your real files, runs terminal commands, runs your tests, finds and fixes bugs, and shows its live thinking as it works. Escalates automatically to Duo Loop for genuinely hard tasks. Completely separate code path from Agent Console — zero coupling, by design.
- 🔒 **Nothing runs or writes without your approval** — every AI-proposed change goes through a diff you review; every mutating shell command needs an explicit click; read-only commands (`ls`, `git status`, `cat`, etc.) run instantly from a strict allowlist, everything else fails closed.
- 🌐 **9 AI providers, your choice** — Ollama locally, native Anthropic Messages API, or OpenAI-compatible support for OpenAI, Gemini, Groq, DeepSeek, Mistral, OpenRouter, and NVIDIA NIM — with adaptive per-tier model routing to control cost.
- ⚔️ **Duo Loop** — two models argue it out (Generator vs. Critic) until the code is actually good, before you ever see it. Both Agent Console and Rony Agent can escalate into it for high-stakes work.
- 🛡️ **Code Verification Agent** — a real, model-driven security auditor that checks your project for SQL injection, exposed secrets, missing input validation, and other production-readiness risks, and gives you a rating out of 100 with a downloadable report
- 👁️ **Vision** — the agent can take a screenshot of what it just built (a running app window, or CODE OS itself), send it to a vision model, and catch visual defects a text-only pass would miss
- 🏖️ **Sandboxed execution** — tiered isolation for anything the agent runs, from lightweight path/resource containment up to a fully disposable Windows Sandbox VM for untrusted projects
- 💻 **A real terminal** — genuine PTY support (`vim`, `git rebase -i`, REPLs), not a fake command box
- 🎨 **4 polished themes** — Dark, Light, Void, and a proper dual-accent Cyberpunk mode

Everything runs on your machine. Your code never leaves it, except to whichever AI provider you explicitly choose, with your own key.

---

## 📦 Download

**[Latest Release: v2.4.0](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v2.4.0)**

| Platform | Installer / Download |
| :--- | :--- |
| **Windows** | [GitHub Release v2.4.0](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v2.4.0) |
| **Linux** | [GitHub Release v2.4.0](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v2.4.0) |
| **macOS** | *Coming soon* |

> Installers aren't code-signed yet — Windows SmartScreen or macOS Gatekeeper may warn on first run. This is expected for an unsigned build; see [Security](#-security) for details.

---

## 🚀 Getting Started

### Option A — Docker (fastest way to try it, nothing to install locally)

The only thing you need on your machine is **Docker** itself — Node.js and Python are bundled inside the container, so you don't need either installed locally.

```bash
git clone https://github.com/roopesh-kosuri/code-os.git
cd code-os
docker compose up
```

→ Frontend at `http://localhost:5176` · Backend at `http://localhost:8000`
→ Verify it's healthy: visit `http://localhost:8000/health` — should return `{"status": "ok"}`

> Docker runs CODE OS in browser mode — you get the full AI/agent experience, with a WebSocket-based terminal fallback instead of Electron's native PTY. For the complete desktop experience, use Option B or grab a prebuilt release above.

### Option B — Full Desktop App (build from source)

Unlike Docker, this requires a few things installed **on your machine first** — these are language runtimes CODE OS depends on, not something CODE OS can install for itself.

**1. Install these first, manually, before anything else:**
- **Node.js 20+** — [nodejs.org](https://nodejs.org)
- **Python 3.11+** — [python.org](https://python.org)
- **Git**
- **OS-specific build tools** (required to compile `node-pty`'s native terminal module):
  - **Windows**: [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) — select the "Desktop development with C++" workload, and make sure Python is on your system `PATH`
  - **macOS**: run `xcode-select --install` in a terminal
  - **Linux (Ubuntu/Debian)**: `sudo apt-get update && sudo apt-get install -y build-essential make python3`

**2. Once those exist, everything else is automatic:**

```bash
git clone https://github.com/roopesh-kosuri/code-os.git
cd code-os

npm install
pip install -r backend/requirements.txt
```

> The backend's terminal dependency is platform-specific and installs automatically for your OS: `pywinpty` on Windows, `ptyprocess` on macOS/Linux — `pip install` picks the right one for you.

**Run everything together (recommended):**
```bash
npm run dev
```
This starts the Vite dev server, the FastAPI backend, and Electron all at once. The Electron window should open automatically.

**Or run backend/frontend separately** (useful for API testing or browser-only UI work without Electron):
```bash
# Terminal 1 — backend only
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend only (browser mode, no Electron)
npm run dev:web
```
Then open `http://127.0.0.1:5176` in your browser.

**Verify it's running:** visit `http://localhost:8000/health` — should return `{"status": "ok"}`.

First launch walks you through a quick setup: accept the terms, optionally take the guided tour, then open your first folder and add your API key(s) under **Settings → AI Providers**. No manual database setup needed — the SQLite database initializes itself on first run.

> **Using local models?** Install [Ollama](https://ollama.com) separately and run `ollama pull <model-name>` before selecting Ollama as your provider in Settings — this is optional and only needed if you want local (non-API) models.

**Want to build your own installer?**
```bash
npm run package
```
Builds a `.exe` (Windows), `.dmg` (macOS), or `.AppImage`/`.deb` (Linux) via `electron-builder`.

---

## 💬 Rony Agent — the chat harness

Agent Console (below) is CODE OS's original heavy-lifting system — five specialized agents, full DAG planning, built for large multi-step jobs you kick off and let run. **Rony Agent** is newer and solves a different problem: most coding requests aren't a 9-step project, they're "fix this function" or "add validation here" — and for those, you shouldn't need to leave chat.

Rony Agent turns the main chat panel into a fast, intelligent, autonomous coding agent — built as a **separate, lightweight system with zero coupling to Agent Console**. Toggle it on with the header switch (off by default); everything below only activates in Agent mode.

**What it can do, directly in chat:**
- Reads and edits your real files, runs terminal commands, runs your actual test suite — not simulated, genuinely executed
- Retrieves relevant context by meaning (semantic search over your workspace), not just files you've explicitly mentioned
- Breaks multi-file requests into an internal step plan before executing, instead of attempting everything in one blind pass
- Shows its live thinking as it works — a collapsible status pill ("Reasoning...", "Reading auth/middleware.py...", "Step 2/4: Updating tests...") that expands into the full step plan and tool-call history for the turn
- Escalates automatically to Duo Loop for genuinely hard tasks (repeated test failures, or the model flagging low confidence), with a visible "Duo Loop running..." status while that happens
- Takes a screenshot of what it just built — a running app window, or CODE OS itself — and sends it to a vision model to catch visual defects a text-only pass would miss
- Checkpoints before every turn (a scoped git commit of just the files it touches) with one-click Undo — never a destructive `reset --hard`
- Remembers your workspace's conventions (naming, import style, error handling) and its own architecture map across sessions, so it doesn't need to relearn your codebase every time
- Warns you when the backend is running stale code after an update, instead of silently executing outdated logic

**Trust & safety, specifically for this system:**
- File edits go through the same diff-review approval flow as everything else in CODE OS — no auto-apply
- Terminal commands: a strict *allowlist* of safe read-only commands run instantly; everything else (anything that writes, installs, or isn't recognized) requires your explicit approval — fails closed, not open
- "Always allow" approval memory is scoped per-workspace and fully revocable from Settings
- A pre-proposal secret scanner blocks anything that looks like an API key or credential before it's ever written or committed
- Sandboxed execution (see below) for anything the agent runs, tiered by how much you trust the workspace

Rony Agent went through a real red-team audit that found and fixed 6 issues before anything shipped further — see [Security](#-security) for the specifics. It's had one focused development cycle of real-task testing, not the extended track record Agent Console has; treat it as genuinely capable but newer.

---

## 🧩 What It Can Do

<table>
<tr>
<td width="50%" valign="top">

### 🧠 Multi-Agent System (Agent Console)
Five agents, one job engine. **CoderAgent** is the flagship — it grounds every plan in your real codebase (indexed symbols, imports, dependencies), writes multi-file changes as one coherent unit, self-reviews its own diffs, runs your test suite on itself, and calls in a second opinion (Duo Loop) for anything risky. Tasks run as real background jobs — switch panels all you want, they keep going. If a task is ambiguous, the agent asks a clarifying question instead of guessing.

### 💬 Rony Agent
The fast chat-based alternative for everyday work — see the [dedicated section above](#-rony-agent--the-chat-harness) for the full picture.

### ⚔️ Duo Loop
A full generator/critic adversarial review — two models argue over the same code until it's genuinely good, before you ever see it. Both Agent Console and Rony Agent can escalate into a Duo Loop session for high-stakes work.

### 🛡️ Code Verification Agent
A dedicated security/production-readiness auditor — checks for SQL injection, exposed secrets, missing input validation, XSS, and other real vulnerability classes, then gives you a 0–100 readiness score and a downloadable, severity-ranked report.

</td>
<td width="50%" valign="top">

### 👁️ Vision
The agent can see what it built. It captures a screenshot — either a hidden offscreen render of your app (HTML/URL workspace preview) or CODE OS's own window — and hands it to a dedicated vision model (configurable per-provider) for a focused visual check, while the main agent loop stays text-only for cost efficiency.

### 🏖️ Sandboxed & Hardened Execution
Tiered isolation for anything an agent runs: baseline path containment + resource/process limits on every machine, an automatic step up to a locked-down Docker/WSL2 container when available, and a fully disposable Windows Sandbox VM for genuinely untrusted projects. Backed by a real production-hardening pass — credential redaction in error logs, request rate limiting, rotating encrypted backups, and a clean static-analysis audit (0 high/critical findings) across the codebase.

### 🛡️ Security That's Actually Enforced
Open an unfamiliar folder and choose **Restricted Mode** — enforced *server-side*, across every file-write, search-replace, terminal session, and MCP call. Session-token authentication on privileged endpoints, strict path sandboxing (blocks symlink escapes and `..` traversal), sanitized terminal environments, encrypted API keys backed by your OS's native credential store, and rate limiting on mutating/streaming endpoints.

### 🖥️ A Real IDE Underneath
Monaco editor with tabs & split view, Git (status/diff/commit/branch/history), real symbol-indexed search (`find_references`, `go_to_definition`), and a genuine PTY terminal that runs `vim` and interactive `git rebase -i` like the real thing.

</td>
</tr>
</table>

---

## 🏗️ Architecture

```
Electron Main Process (Node.js)
│ native PTYs · window · backend lifecycle
│ IPC
▼
React Frontend
│ Monaco · panels · Zustand state · Rony Agent chat harness
│ HTTP / SSE / WebSocket
▼
FastAPI Backend (Python)
│ files · git · search · indexing · sandboxed execution
│ Agent Console (5-agent DAG)  ──┐
│ Rony Agent (lightweight loop) ─┼─► shared tool layer (read/edit/terminal/test), zero cross-coupling
│ Duo Loop (generator/critic)   ─┘
│ aiosqlite
▼
SQLite → workspaces · settings · encrypted keys · index · jobs · history · activity log
```

| Layer | Tech |
|---|---|
| Desktop | Electron 33 |
| Frontend | React 18 · TypeScript · Zustand 5 · Tailwind CSS 3 · Monaco Editor · xterm.js · Vite 6 |
| Backend | Python 3.11+ · FastAPI 0.115 · Uvicorn · aiosqlite · GitPython · psutil · cryptography · keyring · watchdog · httpx |
| Terminal | node-pty (Electron) / pywinpty on Windows + ptyprocess on macOS/Linux (WebSocket fallback) |
| Sandboxing | Path/resource containment (all platforms) · Docker/WSL2 containers (auto-detected) · Windows Sandbox `.wsb` disposable VMs |
| AI | Ollama · native Anthropic Messages API · OpenAI-compatible (OpenAI, Gemini, Groq, DeepSeek, Mistral, OpenRouter, NVIDIA NIM) · adaptive per-tier model routing |
| Security | Fernet-encrypted keys backed by OS keychain (`keyring`) · server-side trust enforcement · session-token auth · rate limiting · CSP · secret scanning (regex + entropy) · prompt-injection filtering |
| CI/CD | GitHub Actions — tests + build on every push, multi-platform installers on release |

**Agent Console and Rony Agent are architecturally isolated on purpose** — separate modules, separate routes, separate frontend components, zero shared mutable state. This is a hard project boundary, verified with a file-level diff check after every change to either system, specifically so heavy-pipeline work and fast chat-agent work can evolve independently without one destabilizing the other.

---

## 🔐 Security

Every untrusted workspace runs in **Restricted Mode**, blocked at the API layer — not just hidden buttons. Every mutating shell command needs explicit approval; read-only commands run from a strict, fail-closed allowlist.

- **Session bearer-token authentication** on high-privilege endpoints
- **Strict path sandboxing** — blocks `~` expansion, symlink escapes, and `..` traversal, plus absolute-path/drive-letter rejection on baseline read commands
- **Terminal environment sanitization** — an explicit allowlist strips credentials (API keys, `AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`, SSH/Git config, etc.) before any shell command runs
- **Tiered sandboxed execution** — baseline process/resource governance everywhere, containerized execution (Docker/WSL2, no network, non-root, resource-capped) where available, disposable Windows Sandbox VMs for untrusted projects, with an explicit fail-closed prompt (never a silent fallback to unsandboxed execution) if isolation isn't available
- **API keys encrypted at rest** via Fernet, with the master key stored in your OS's native credential store (macOS Keychain, Windows Credential Manager, Linux Secret Service via `keyring`), falling back to a strictly-permissioned local file if unavailable
- **Pre-proposal secret scanner** (key-prefix patterns + Shannon entropy) blocks likely credentials before they're ever written or committed
- **Prompt-injection resistance** — all file contents fed to an agent are wrapped and explicitly marked as untrusted data, with a pre-execution filter blocking known injection/exfiltration command patterns
- **Rate limiting** on mutating and AI streaming endpoints, plus monthly token budgets
- **Content Security Policy** restricting network connectivity and script sources

**A real red-team audit was run against Rony Agent** and found 6 issues — all fixed the same day, before further capability work continued: a git-staging path that could leak untracked credential files (now stages only the agent's own touched files, plus pre-commit validation against a sensitive-file list), a sandbox availability check that could silently fall back to unsandboxed execution (now fails closed with an explicit confirmation required), the prompt-injection filtering described above, unbounded activity-log growth (now rotated and paginated), a vision-capture window leak under repeated use (now pooled and cleaned up), and an oversized core module (now split into focused, independently testable files). This is the kind of thing we'll keep doing before any future release, not a one-time pass.

**Known limitations, stated plainly:** installers aren't code-signed yet; no formal third-party security audit has been performed yet — planned for a future release; container/VM sandbox tiers depend on Docker/WSL2/Windows Sandbox being available on your machine, with baseline (non-containerized) protection as the universal floor.

Full threat model & disclosure process → **[SECURITY.md](./SECURITY.md)** · **[docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md)**

---

## 📊 Project Status

This is real, working software, currently at **v2.4.0** — actively developed and hardened through iterative testing, not a mockup.

✅ **Solid & verified:** core IDE (files, editor, Git, search, terminal), the full AI edit-proposal pipeline, the multi-agent Agent Console + Duo Loop (including background job persistence), the Code Verification Agent, workspace trust enforcement swept across every route, session-token auth, OS-keychain-backed key encryption, a real automated test suite, CI/CD running on every push, multi-platform installer builds.

✅ **Also solid & verified, new in v2.4.0:** the Rony Agent chat harness (tool loop, retrieval, task decomposition, visible thinking UI, Duo Loop escalation, strict command allowlisting) and its full bug-hunt pass (truncation/timeout handling, stuck-loop breakers, hang watchdogs, task-difficulty routing, UI state fixes); per-turn checkpoint/undo via scoped git commits; runtime-freshness detection; scoped approval memory; adaptive per-tier model routing with cost tracking; pre-proposal self-critique and a before/after regression test guard; a searchable activity timeline; a symbol indexer with find-references/go-to-definition; a background server-session tool; a structured git-diff reader; the secret scanner and prompt-injection filtering described in Security; codebase style learning; a dead-code detector; an agent-maintained architecture map; vision/screenshot capability; the full tiered sandboxing system; the production-hardening + red-team fix pass; a multi-language Run button; and inline AI code completion (ghost-text suggestions, Tab to accept).

🛠️ **In flight (built with strict no-refactor boundaries against the rest of the app, pending final verification):** GitHub commit/push integration, Python debugging via `debugpy` with Monaco breakpoint support.

🗺️ **Backlog:** command palette, file drag-drop upload, terminal split, workspace templates, markdown preview, git blame, find-all-references UI, minimap, a plugin/extension system, real-time collaboration, macOS installer support, code signing, MCP server security scanning integration, LSP-based live diagnostics, and a formal third-party security audit.

Built iteratively, hardened by actually testing behavior — not by assuming code that compiles is code that works. Every capability above marked "solid & verified" was confirmed with real task runs, not just passing unit tests; several bugs in the list only surfaced that way and unit tests alone would have missed them.

---

## 📚 Documentation

| Doc | What's in it |
|---|---|
| **[ARCHITECTURE.md](./ARCHITECTURE.md)** | Full system design, data flow, and component breakdown |
| **[SECURITY.md](./SECURITY.md)** | Security policy, reporting SLA, security controls summary |
| **[docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md)** | Trust boundaries, threats, and mitigations |
| **[Documentation.md](./documentation.md)** | Complete technical specification and API documentation |
| **[ROADMAP.md](./ROADMAP.md)** | What's shipped, what's in progress, what's next |
| **[CONTRIBUTING.md](./CONTRIBUTING.md)** | How to set up, branch, and submit PRs |

---

## 🤝 Contributing

Bug reports, feature ideas, and pull requests are genuinely welcome — particularly around **plugin execution, macOS support, code signing, LSP integration, and testing improvements**, but any contribution counts. See **[CONTRIBUTING.md](./CONTRIBUTING.md)** to get set up. PRs need to pass CI (typecheck, build, backend test suite) before merge.


## 📄 License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](./License.md) — free for personal, educational, and non-commercial use. For commercial use, please reach out first (see [Links](#-links) below).


---

🔗 **Links**
LinkedIn: [Roopesh Ram Varma Kosuri](https://www.linkedin.com/in/roopesh-ram-varma-kosuri-28186a37b/)
X (Twitter): [@KosuriRoopesh](https://x.com/KosuriRoopesh)
