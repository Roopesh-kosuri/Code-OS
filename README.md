<div align="center">

# CODE-OS

### A local-first AI IDE that plans, codes, and reviews your software — and never touches disk without your say-so.

[![CI/CD](./docs/badges/cicd.svg)](https://github.com/Roopesh-kosuri/Code-OS/actions/workflows/build-mac.yml)
[![License: PolyForm Noncommercial 1.0.0](./docs/badges/license.svg)](./License.md)
![Platform](./docs/badges/platform.svg)

![Made with Electron](./docs/badges/electron.svg)
![FastAPI](./docs/badges/fastapi.svg)

<br>

### ▶️ Demo

[![Watch the demo](https://img.youtube.com/vi/2LZ2V9nhz34/maxresdefault.jpg)](https://www.youtube.com/watch?v=2LZ2V9nhz34)

🌐 [**CODE OS Website**](https://roopesh-kosuri.github.io/websitecodeos/)

**[Getting Started](#-getting-started)** · **[Download](#-download)** · **[New in v4.0.0 (Titan Update)](#-new-in-v400--the-titan-update)** · **[Features](#-what-it-can-do)** · **[Rony Agent](#-rony-agent--the-chat-harness)** · **[Architecture](#%EF%B8%8F-architecture)** · **[Security](#-security)** · **[Status](#-project-status)** · **[Docs](#-documentation)**

</div>

---

## ⚡ Why CODE OS

Most "AI IDEs" are a chat box bolted onto a text editor. CODE OS is built differently — it runs **two distinct agent systems**, matched to the size of the task:

- 🧠 **5 specialized agents in Agent Console** — Planner, Coder, Reviewer, Tester, Documenter — for long, heavy, multi-step work. Full DAG planning, self-review, and test execution as one coordinated system.
- 💬 **Rony Agent — a fast, intelligent chat harness** — for everyday coding, entirely inside the chat panel: reads and edits your real files, runs terminal commands, runs your tests, finds and fixes bugs, and shows its live thinking as it works. Escalates automatically to Duo Loop for genuinely hard tasks. Completely separate code path from Agent Console — zero coupling, by design.
- 🔒 **Nothing runs or writes without your approval** — every AI-proposed change goes through a diff you review; every mutating shell command needs an explicit click; read-only commands (`ls`, `git status`, `cat`, etc.) run instantly from a strict allowlist, everything else fails closed.
- 🌐 **14 AI providers, your choice** — Ollama locally ($0 cost), native Anthropic Messages API, or OpenAI-compatible support for OpenAI, Gemini, Groq, DeepSeek, Mistral, OpenRouter, and NVIDIA NIM — with adaptive per-tier model routing to control cost.
- ⚔️ **Duo Loop** — two models argue it out (Generator vs. Critic) until the code is actually good, before you ever see it. Both Agent Console and Rony Agent can escalate into it for high-stakes work.
- 🛡️ **Code Verification & Security Scanner** — an AST-driven security auditor that checks for SQL injection, exposed secrets, and dependency vulnerabilities, generating one-click AST-safe automated patches with test verification.
- 👁️ **Vision** — the agent can take a screenshot of what it just built (a running app window, or CODE OS itself), send it to a vision model, and catch visual defects a text-only pass would miss.
- 🏖️ **Sandboxed execution** — tiered isolation for anything the agent runs, from lightweight path/resource containment up to a fully disposable Windows Sandbox VM for untrusted projects.
- 💻 **Agentic terminal** — genuine PTY support (`vim`, `git rebase -i`, REPLs) with real-time SSE command streaming and safety classification.
- 🎨 **4 polished themes** — Dark, Light, Void, and a proper dual-accent Cyberpunk mode.

Everything runs on your machine. Your code never leaves it, except to whichever AI provider you explicitly choose, with your own key.

---

## 📦 Download

**[Latest Release: v4.0.0 (The Titan Update)](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v4.0.0)**

| Platform | Installer / Download | Details |
| :--- | :--- | :--- |
| **Windows** | [CODE OS Setup 4.0.0.exe](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v4.0.0) | NSIS Setup wizard (`oneClick: false`, custom install directory) |
| **Windows (Portable)** | [CODE OS-4.0.0-portable.exe](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v4.0.0) | Standalone zero-install portable executable |
| **Linux** | [CODE OS-4.0.0.AppImage](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v4.0.0) | Self-contained AppImage for all major Linux distributions |
| **macOS** | [GitHub Release v4.0.0 DMG](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v4.0.0) | Apple Silicon & Intel Universal DMG via CI |

> **v4.0.0 Master Installers are Fresh-Laptop Ready**:
> - **Zero Dev Environment Required**: Bundles Python 3.11, Node.js 20, and all heavy AI dependencies (`chromadb`, `faster-whisper`, `ctranslate2`, `sentence-transformers`, `onnxruntime`, `pyautogui`, `selenium`, `PyMuPDF`) directly inside.
> - **PyInstaller `--onedir` Packaging**: Permanently prevents Windows Defender false-positive quarantines and ensures instant sub-second launch.
> - **User-Writable AppData Isolation**: All SQLite databases, vector indexes, Whisper models, and logs write dynamically to `%APPDATA%/code_os` (Windows) or `~/.config/code_os` (Linux/macOS) — eliminating read-only crashes in `Program Files`.
> - **Watchdog Supervisor**: Built-in `watchdog_launcher` automatically monitors and recovers the backend if unexpected errors occur.

---

## 🚀 New in v4.0.0 — The Titan Update

CODE OS v4.0.0 is the largest and most comprehensive release in the project's history. It introduces **17 major autonomous capabilities**, a complete **Codex-class Chat Harness rebuild**, hardened **multi-provider routing**, and **zero-dependency production installers**.

### 🛠️ Core System & Reliability Fixes (Pre-Existing Issues Resolved)

1. **Chat Harness Rebuild (Codex-Class Quality)**
   - **Structured Tool Calling**: Replaced brittle prompt parsing with native JSON structured tool execution as the primary interface.
   - **Multi-Turn Truncation Continuation**: Automatically resumes streaming across multi-turn exchanges when executing massive code edits.
   - **Tier Leashes & Loop Breakers**: Hard bounds prevent infinite execution loops; enforces honest completion gates where agents must explicitly declare `"DONE"`.
   - **Self-Repair Loop**: Automatically detects test failures and initiates self-repair cycles (max 3 rounds) before presenting code to the user.
   - **Stream Reasoning Filter**: Seamlessly strips `<think>` reasoning blocks from DeepSeek and thinking models before SSE delivery, keeping chat clean.

2. **Rate Limit Taxonomy & Error Classification**
   - Eliminated false-positive "Rate limited" banners. HTTP status codes are now strictly classified:
     - `429 Too Many Requests` → Dedicated Rate Limit banner with live countdown timer and automatic exponential backoff.
     - `5xx Server Errors` → Connection issue notification with one-click retry.
     - `400 Bad Request` → Displays verbatim provider error details for rapid debugging.
     - `Timeouts` → Network latency alert with fallback provider suggestion.

3. **Intelligent Provider Routing (14 Providers, 100+ Models)**
   - Dynamic catalog routing routes `reasoning_effort` only to supported model families (e.g. OpenAI o-series), preventing 400 parameter errors on NVIDIA NIM and Groq.
   - Automatic fallback chains (`Primary → Secondary → Tertiary`) with circuit breaker trip protection (cooldown after 3 consecutive failures).
   - Zero-cost local model detection for Ollama instances.

4. **Server-Side Workspace Trust Enforcement**
   - High-privilege actions (shell commands, git operations, file mutations, and team DAG jobs) strictly require explicit workspace trust.
   - Restricted Mode blocks directory escapes and dangerous execution at the FastAPI middleware layer.

5. **Process Tracking & Clean Orphan Reaping**
   - New `process_tracker` service monitors every spawned child process (pytest runners, browser controllers, PTY shells).
   - Enforces a 300-second maximum timeout per command.
   - Automatically reaps process trees (`taskkill /F /T /PID` on Windows, SIGTERM/SIGKILL escalation on Linux/macOS) on shutdown, eliminating orphaned background locks.

6. **Database Event-Loop Isolation & WAL Mode**
   - SQLite configured with `PRAGMA journal_mode=WAL` and `busy_timeout=5000ms` for seamless concurrent reads and writes.
   - Connection pool dynamically binds to the active `asyncio` event loop, eliminating `RuntimeError: Event loop is closed` and database lock contention during long-running tasks.

---

### 🧩 17 Massive New Features

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   CODE OS v4.0.0 FEATURE MATRIX                                  │
├──────────────────────────────┬──────────────────────────────┬────────────────────────────────────┤
│   🧠 Intelligence & Autonomy │   💻 Editor & Developer Exp  │   ⚡ Ops, Voice & Automation       │
├──────────────────────────────┼──────────────────────────────┼────────────────────────────────────┤
│ • Real-Time Cost Dashboard   │ • Ghost Text & Inline Diffs  │ • Agentic Terminal (xterm.js)      │
│ • Session Replay Time-Travel │ • Smart Staging (PR View)    │ • Git Autopilot ("Ship It")        │
│ • Semantic RAG (ChromaDB)    │ • Architecture Diagrams      │ • Security Scanner & AST Auto-Fix  │
│ • Distributed Model Router   │ • AI Refactoring Assistant   │ • CI/CD Workflow Generator         │
│ • AI Mistakes & Memory Loop  │ • File Upload & Context Pack │ • Daily Standup Generator          │
│                              │                              │ • Voice Mode (Whisper/TTS)         │
│                              │                              │ • Rony Voice Desktop Automation    │
└──────────────────────────────┴──────────────────────────────┴────────────────────────────────────┘
```

#### 🧠 Intelligence & Autonomy

1. **Token & Cost Real-Time Dashboard & Budget Guard**
   - Live spend tracking recorded via `cost_events` with color-coded status in the TopBar (Green <50%, Amber 50-90%, Red >90%).
   - Active budget enforcement: automatically warns at 80%, auto-downgrades models at 90%, and halts at 100%.
   - Full analytics modal powered by Recharts (token distribution, provider cost breakdown, history) with CSV export.

2. **Session Replay & Visual Time Travel**
   - Scrub through past agent jobs with a step-by-step playback slider.
   - Inspect tool calls, before/after diffs, and test outputs at every stage of execution.
   - Fork from any historical step with new instructions or export session replays to Markdown/JSON.

3. **Semantic RAG (Chat with Codebase)**
   - Local ChromaDB vector database with embedded `all-MiniLM-L6-v2` (384 dimensions) running 100% offline.
   - AST-aware chunking (500 tokens with 50-token overlap) across 13 programming languages.
   - Incremental file watcher keeps the index updated in real-time. Toggle "Use RAG" in chat to inject top-5 semantically relevant code chunks into agent prompts.

4. **Distributed Multi-Model Router**
   - Intelligent task classifier evaluates prompt intent and AST complexity to categorize requests into `HARD`, `MEDIUM`, or `EASY`.
   - Automatically routes tasks to optimal tiers (e.g. `HARD` → Claude Opus 5 / GPT-5; `MEDIUM` → Claude Sonnet / GPT-4o; `EASY` → Groq Llama 3.3 70B / Gemini Flash).
   - Visual color-coded DAG boards with manual tier override controls.

5. **AI Learns from Mistakes (Self-Improvement Memory Loop)**
   - Persistent `agent_memories` table stores failure events, rejected diffs, and user undo actions.
   - LLM synthesizes actionable lessons ("Always use parameterized queries in SQLite"), automatically injecting relevant memories into future system prompts via vector retrieval.
   - Interactive Memory Panel allows developers to inspect, add manual rules, or purge lessons.

#### 💻 Editor & Developer Experience

6. **Ghost Text & Inline Streaming Diffs**
   - Cursor-style grey italic streaming directly inside the Monaco editor.
   - Real-time SSE token delivery shows code being written live.
   - One-key acceptance: press <kbd>Tab</kbd> to accept suggestion, or <kbd>Esc</kbd> to discard.

7. **Smart Staging & PR Review Panel**
   - GitHub-PR-style multi-file review interface automatically triggered for edits touching more than 3 files.
   - Interactive checklist on the left; side-by-side Monaco diff viewer on the right with red/green annotations.
   - Granular chunk-level approvals: approve specific files or apply all approved diffs in one click.

8. **Architecture Diagram Generator**
   - Analyzes project codebase via Python `ast` and regex parsers to map modules, dependencies, routes, and database tables.
   - Generates 4 interactive diagram types: Component Diagrams, Request Data Flow, API Sequence, and Entity-Relationship Diagrams (ERD).
   - Rendered using client-side Mermaid with pan/zoom, SVG/PNG export, and "Open in Editor" integration.

9. **AI Code Refactoring Assistant & Smell Detector**
   - Scans codebase for architectural smells: long functions, cyclomatic nesting ("pyramid of doom"), dead code, and duplicates.
   - One-click transformations: Extract Function, Rename Symbol (project-wide), Apply Factory/Strategy Patterns, and Flatten Conditionals.
   - Test-safety verification: automatically runs the workspace test suite on an isolated copy before applying refactors.

10. **Multi-File Ingestion & Context Packager**
    - Drag-and-drop file ingestion zone in Rony Chat and Agent Console.
    - Native extraction for PDFs (via PyMuPDF), images (OCR via pytesseract), source code, JSON, and YAML — 100% local with no cloud uploads.
    - File preview modal with PDF pagination and syntax-highlighted code viewer.

#### ⚡ Ops, Voice & System Automation

11. **Agentic Terminal & Natural Language Shell**
    - Embedded `xterm.js` terminal emulator with real-time SSE command streaming.
    - Prompts formatted as `agent@code-os:~$ <cmd>` with white stdout, red stderr, and exit status badges (`✓ Exit 0` / `✗ Exit 1`).
    - Safety classification (safe, risky, dangerous) with instant kill buttons and multi-terminal session switching.

12. **Git Autopilot ("Ship It")**
    - "Ship It" rocket button in TopBar inspects `git diff` and categorizes changes by Conventional Commit types (`feat`, `fix`, `docs`, `refactor`).
    - Generates 72-character commit messages and comprehensive GitHub PR summaries (Summary, Changes, Test Evidence).
    - Progressive actions: Commit → Commit & Push → Commit, Push & Open PR.

13. **Security Scanner & AST Auto-Fix**
    - Integrated multi-engine auditing: Bandit (Python AST security), npm audit (JS dependencies), and safety check (known CVEs).
    - AI Auto-Fix engine generates verified diffs (e.g. converting raw SQL strings into parameterized bindings).
    - Test-safety gate runs test suite before applying patches; displays critical vulnerability count badges in the sidebar.

14. **CI/CD Workflow Generator**
    - Analyzes workspace stack (Node, Python, Go, Rust, Docker) and generates production-ready GitHub Actions or GitLab CI YAML pipelines.
    - Includes multi-platform test matrices, dependency caching, and build validation stages with direct "Save to Workspace" integration.

15. **Daily Standup & Work Summary Generator**
    - Aggregates past 24-hour workspace activity: completed agent jobs, git commits, executed task steps, and token spend.
    - Synthesizes formatted standups in Slack (with emojis) or Markdown formats with one-click clipboard copying.

16. **Hands-Free Voice Mode**
    - Push-to-talk voice interface utilizing local `faster-whisper` (int8 CPU quantized) and `pyttsx3` offline speech synthesis.
    - Real-time audio waveform visualizer and global hotkey (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd>).
    - "Read replies aloud" mode for eyes-free coding assistance.

17. **Full Rony Voice (Autonomous System Automation)**
    - Extends voice capabilities into an autonomous desktop assistant using `pyautogui` and Selenium.
    - System control: mouse/keyboard automation, window switching, screenshot capture, and application launching.
    - Web automation: searches the web, navigates pages, and extracts research summaries.
    - Strict safety gates: destructive actions require explicit modal approval, payment workflows halt before checkout, and emergency stop is instantly triggered via <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Q</kbd>.

---

## 🚀 Getting Started

### Option A — Prebuilt Installers (Fastest & Recommended)

Download the standalone installer for your operating system from the [**Download Table**](#-download). No Python, Node.js, or C++ build tools are required on your machine.

### Option B — Docker (Browser Mode)

The only requirement is **Docker** — runtimes are containerized:

```bash
git clone https://github.com/roopesh-kosuri/code-os.git
cd code-os
docker compose up
```

→ Open `http://localhost:5176` (Frontend) · `http://localhost:8000` (Backend)  
→ Health Check: `http://localhost:8000/api/health` returns `{"status": "healthy"}`

### Option C — Full Desktop App (Build from Source)

**1. Prerequisites:**
- **Node.js 20+** — [nodejs.org](https://nodejs.org)
- **Python 3.11+** — [python.org](https://python.org)
- **Git**
- **C++ Build Tools** (for native `node-pty` terminal modules):
  - **Windows**: Visual Studio Build Tools with "Desktop development with C++"
  - **macOS**: `xcode-select --install`
  - **Linux**: `sudo apt-get install -y build-essential python3-dev`

**2. Setup & Execution:**

```bash
git clone https://github.com/roopesh-kosuri/code-os.git
cd code-os

npm install
pip install -r backend/requirements.txt
```

**Run Development Mode:**
```bash
npm run dev
```
Starts Vite, FastAPI, and Electron concurrently.

**Build Standalone Installers Locally:**
```bash
# Compile backend in --onedir mode
node scripts/build-backend.js

# Build frontend and package
npm run build:vite
npm run build:electron
npx electron-builder --win        # Windows Setup (.exe) & Portable
# Or on Linux / WSL:
npx electron-builder --linux AppImage  # Linux AppImage
```

---

## 💬 Rony Agent — the chat harness

Agent Console (below) is CODE OS's heavy-lifting multi-agent engine — five specialized agents, full DAG planning, built for large multi-step jobs. **Rony Agent** is designed for everyday coding directly in the chat panel:

**Key Capabilities:**
- Reads and edits files, executes terminal commands, and runs your test suite autonomously.
- Semantic RAG retrieval brings in relevant code context based on meaning rather than explicit file paths.
- Collapsible thinking UI displays live execution status ("Reasoning...", "Executing tests...", "Step 2/4") and full tool history.
- Automatic escalation to Duo Loop for hard tasks or repetitive test failures.
- Vision analysis captures running windows or IDE state and identifies UI defects.
- Scoped Git checkpoints before every turn with one-click Undo (never destructive `reset --hard`).
- Contextual memory stores workspace naming patterns, error handling conventions, and past mistakes.
- All file edits require diff approval; shell commands are governed by an allowlist and fail-closed security.

---

## 🧩 What It Can Do

<table>
<tr>
<td width="50%" valign="top">

### 🧠 Multi-Agent System (Agent Console)
Five agents, one job engine: Planner, Coder, Reviewer, Tester, and Documenter. **CoderAgent** writes multi-file changes as a unified patch, self-reviews diffs, runs test suites, and requests Duo Loop second opinions. Tasks run as durable background jobs.

### 💬 Rony Agent
Autonomous chat-driven coding: file edits, terminal commands, test verification, visual thinking pills, and Duo Loop escalation.

### ⚔️ Duo Loop
Adversarial generator/critic review: two models debate until code satisfies rigorous correctness standards.

### 🛡️ Security Scanner & AST Auto-Fix
Audits SQL injection, exposed secrets, XSS, and vulnerable packages; synthesizes verified AST-safe patches with test-safety gates.

### 🔌 MCP Servers
Full Model Context Protocol support: stdio & HTTP transports, approval-gated tool calls, discovery scanners, and SSRF defenses.

</td>
<td width="50%" valign="top">

### 📊 Token & Cost Dashboard
Real-time cost tracking with TopBar spend pill, Recharts visual analytics, budget limits with auto-downgrade, and CSV export.

### 👁️ Vision & Multimodal Inspection
Captures application screenshots and sends them to vision models for automated visual defect detection.

### 🏖️ Sandboxed & Hardened Execution
Tiered isolation: path/resource limits on all machines, Docker/WSL2 containers when available, and disposable Windows Sandbox VMs.

### 🛡️ Server-Side Trust & Security
Restricted Mode enforced server-side. Session bearer tokens on privileged endpoints, path sandboxing, and encrypted API key storage.

### 🖥️ Native IDE Environment
Monaco editor with tabs/split view, Git history/blame, AST refactoring assistant, and a genuine PTY terminal (`vim`, `git rebase -i`).

</td>
</tr>
</table>

---

## 🏗️ Architecture

```
Electron Main Process (Node.js)
│ native PTYs · window management · watchdog supervisor
│ IPC
▼
React Frontend (Vite + Monaco + xterm.js)
│ Monaco · Zustand store · Ghost Text · Smart Staging · Rony Chat
│ HTTP / SSE / WebSocket
▼
FastAPI Backend (Python 3.11)
│ files · git · AST refactoring · ChromaDB RAG · sandboxing
│ Agent Console (5-agent DAG)  ──┐
│ Rony Agent (chat loop)        ─┼─► shared tool layer (read/edit/terminal/test), zero cross-coupling
│ Duo Loop (generator/critic)   ─┘
│ Watchdog Launcher (auto-restart subprocess supervisor)
│ aiosqlite (WAL mode)
▼
SQLite Database & Storage
│ Workspaces · settings · encrypted keys · agent_memories · cost_events
│ Location: %APPDATA%/code_os (Windows) · ~/.config/code_os (Linux) · ~/Library/Application Support/code_os (macOS)
```

| Layer | Technology |
|---|---|
| Desktop | Electron 33 · electron-builder · PyInstaller (`--onedir`) |
| Frontend | React 18 · TypeScript · Zustand 5 · Tailwind CSS 3 · Monaco Editor · xterm.js · Recharts · Vite 6 |
| Backend | Python 3.11+ · FastAPI · Uvicorn · aiosqlite (WAL mode) · GitPython · psutil · cryptography · keyring · watchdog · httpx |
| AI & Vectors | ChromaDB · faster-whisper · ctranslate2 · sentence-transformers · onnxruntime · PyMuPDF · pytesseract |
| Automation | pyautogui · Selenium · pystray · Playwright |
| Terminal | node-pty (Electron) / pywinpty (Windows) + ptyprocess (Linux/macOS) |
| Security | Fernet encryption via OS keychain (`keyring`) · server-side trust · session-token auth · AST taint inspection |
| CI/CD | GitHub Actions — automated macOS DMG releases; Windows & Linux built locally |

---

## 🔐 Security

Every untrusted workspace defaults to **Restricted Mode**, enforced server-side across all endpoints:

- **Session Bearer Tokens**: Required on all privileged HTTP and WebSocket endpoints.
- **Strict Path Containment**: Blocks `~` expansion, symlink traversal, UNC paths, and `..` directory escapes.
- **Environment Sanitization**: Strips API credentials, AWS keys, and SSH configs before executing terminal commands.
- **Tiered Sandboxing**: Baseline resource governance, optional Docker/WSL2 containers, and disposable Windows Sandbox VMs.
- **Encrypted Credential Storage**: API keys are Fernet-encrypted with master keys held in the OS Credential Manager / Keychain.
- **Pre-Proposal Secret Scanner**: Regex + Shannon entropy detection blocks exposed secrets before proposals or commits are generated.
- **SSRF Defense**: DNS pre-resolution blocks private, loopback, link-local, and cloud metadata IP ranges on URL fetches.

Full threat model & disclosure process → **[SECURITY.md](./SECURITY.md)** · **[docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md)** · **[docs/V4_FINAL_VERIFICATION_REPORT.md](./docs/V4_FINAL_VERIFICATION_REPORT.md)**

---

## 📊 Project Status

CODE OS is at **v4.0.0 (The Titan Update)** — production-ready, fully regression-locked, and verified across both backend and frontend suites.

- ✅ **Full Regression Lock**:
  - **Backend**: **719 passed, 4 skipped, 0 failed** across all feature suites and chaos tests.
  - **Frontend**: **52/52 test files passed, 284/284 tests passed** with Vitest.
  - **Type Safety**: `tsc --noEmit` completed with **0 errors**.
- ✅ **17 Features Verified Working**: Cost Dashboard, Session Replay, Semantic RAG, Distributed Router, AI Learning, Ghost Text, Smart Staging, Architecture Diagrams, Refactoring Assistant, File Upload, Agentic Terminal, Git Autopilot, Security Scanner, CI/CD Generator, Daily Standup, Voice Mode, and Rony Voice.
- ✅ **Clean Protected Core**: All 6 protected architectural files verified with 0 modifications.
- ✅ **Fresh-Laptop Ready**: Windows (`.exe` NSIS setup + portable) and Linux (`.AppImage`) standalone installers built locally.

---

## 📚 Documentation

| Document | Description |
|---|---|
| **[ARCHITECTURE.md](./ARCHITECTURE.md)** | System design, component boundaries, and data flow |
| **[SECURITY.md](./SECURITY.md)** | Security policy, threat model, and vulnerability reporting |
| **[docs/V4_FINAL_VERIFICATION_REPORT.md](./docs/V4_FINAL_VERIFICATION_REPORT.md)** | v4.0.0 Final Gate verification results and evidence matrix |
| **[docs/SYSTEM_VERIFICATION_REPORT.md](./docs/SYSTEM_VERIFICATION_REPORT.md)** | Full system subsystem certification audit |
| **[MCP_INTEGRATION.md](./MCP_INTEGRATION.md)** | MCP server configuration and security model |
| **[documentation.md](./documentation.md)** | API specifications and internal developer guide |
| **[ROADMAP.md](./ROADMAP.md)** | Release milestones and upcoming feature plans |
| **[CONTRIBUTING.md](./CONTRIBUTING.md)** | Development environment setup and PR guidelines |

---

## 🤝 Contributing

Contributions are welcome! See **[CONTRIBUTING.md](./CONTRIBUTING.md)** for developer setup and PR guidelines. All submissions must pass CI checks, TypeScript verification, and test suites.

## 📄 License

Licensed under the [PolyForm Noncommercial License 1.0.0](./License.md) — free for personal, educational, and non-commercial use. For commercial inquiries, please reach out via the links below.

---

🔗 **Links**  
LinkedIn: [Roopesh Ram Varma Kosuri](https://www.linkedin.com/in/roopesh-ram-varma-kosuri-28186a37b/)  
X (Twitter): [@KosuriRoopesh](https://x.com/KosuriRoopesh)
