<div align="center">

# CODE-OS

### A local-first AI IDE that plans, codes, and reviews your software — and never touches disk without your say-so.

[![CI/CD](./docs/badges/cicd.svg)](https://github.com/Roopesh-kosuri/Code-OS/actions/workflows/ci.yml)
[![License: MIT](./docs/badges/license.svg)](./LICENSE)
![Platform](./docs/badges/platform.svg)
![Made with Electron](./docs/badges/electron.svg)
![FastAPI](./docs/badges/fastapi.svg)

<br>

### ▶️ Demo

[![Watch the demo](https://img.youtube.com/vi/2LZ2V9nhz34/maxresdefault.jpg)](https://www.youtube.com/watch?v=2LZ2V9nhz34)

🌐 [**CODE OS Website**](https://roopesh-kosuri.github.io/websitecodeos/)

**[Getting Started](#-getting-started)** · **[Download](#-download)** · **[Features](#-what-it-can-do)** · **[Architecture](#%EF%B8%8F-architecture)** · **[Security](#-security)** · **[Status](#-project-status)** · **[Docs](#-documentation)**

</div>

---

## ⚡ Why CODE OS

Most "AI IDEs" are a chat box bolted onto a text editor. CODE OS is built differently:

- 🧠 **5 specialized agents** — Planner, Coder, Reviewer, Tester, Documenter — that plan, write, self-review, and test code as one coordinated system, not a single chat wrapper
- 🔒 **Nothing runs or writes without your approval** — every AI-proposed change goes through a diff you review; every shell command needs an explicit click
- 🌐 **9 AI providers, your choice** — Ollama locally, native Anthropic Messages API, or OpenAI-compatible support for OpenAI, Gemini, Groq, DeepSeek, Mistral, OpenRouter, and NVIDIA NIM
- ⚔️ **Duo Loop** — two models argue it out (Generator vs. Critic) until the code is actually good, before you ever see it
- ⚡ **Coder Mode** — a fast, single-model CoderAgent + TesterAgent pipeline for regular tasks, at Duo-Loop-like speed, when you don't need the full 5-agent pipeline
- 👥 **Dual Coder** — two models independently attempt the same small task, each producing its own candidate file, so you can compare two real solutions side by side (for small tasks — bigger task support coming soon)
- 🛡️ **Code Verification Agent** — a real, model-driven security auditor that checks your project for SQL injection, exposed secrets, missing input validation, and other production-readiness risks, and gives you a rating out of 100 with a downloadable report
- 💻 **A real terminal** — genuine PTY support (`vim`, `git rebase -i`, REPLs), not a fake command box
- 🎨 **4 polished themes** — Dark, Light, Void, and a proper dual-accent Cyberpunk mode

Everything runs on your machine. Your code never leaves it, except to whichever AI provider you explicitly choose, with your own key.

---

## 📦 Download

**[Latest Release: v1.0.0-beta.1](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v1.0.0-beta.1)**

| Platform | Installer | Unpacked |
|---|---|---|
| **Windows** | [GitHub Release](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v1.0.0-beta.1) | [Code OS Windows (MediaFire)](https://www.mediafire.com/file/jjshcesqufp1yio/Code+OS+Windows.zip/file) |
| **Linux** | [GitHub Release](https://github.com/Roopesh-kosuri/Code-OS/releases/tag/v1.0.0-beta.1) | [Code OS Linux (MediaFire)](https://www.mediafire.com/file/hgiagmsj5da723c/Code+OS+Linux.zip/file) |
| **macOS** | Coming in a future update | — |

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

→ Frontend at `http://localhost:5173` · Backend at `http://localhost:8000`
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
Then open `http://127.0.0.1:5173` in your browser.

**Verify it's running:** visit `http://localhost:8000/health` — should return `{"status": "ok"}`.

First launch walks you through a quick setup: accept the terms, optionally take the guided tour, then open your first folder and add your API key(s) under **Settings → AI Providers**. No manual database setup needed — the SQLite database initializes itself on first run.

> **Using local models?** Install [Ollama](https://ollama.com) separately and run `ollama pull <model-name>` before selecting Ollama as your provider in Settings — this is optional and only needed if you want local (non-API) models.

**Want to build your own installer?**
```bash
npm run package
```
Builds a `.exe` (Windows), `.dmg` (macOS), or `.AppImage`/`.deb` (Linux) via `electron-builder`.

---

## 🧩 What It Can Do

<table>
<tr>
<td width="50%" valign="top">

### 🧠 Multi-Agent System
Five agents, one job engine. **CoderAgent** is the flagship — it grounds every plan in your real codebase (indexed symbols, imports, dependencies), writes multi-file changes as one coherent unit, self-reviews its own diffs, runs your test suite on itself, and calls in a second opinion (Duo Loop) for anything risky. Tasks run as real background jobs — switch panels all you want, they keep going. If a task is ambiguous, the agent asks a clarifying question instead of guessing.

### ⚔️ Duo Loop, Coder, & Dual Coder
Three ways to get code written, matched to the task: **Duo Loop** for a full generator/critic adversarial review, **Coder** for a fast single-model CoderAgent+TesterAgent pass on regular tasks, and **Dual Coder** for small tasks where two models each take an independent swing so you can compare.

### 🛡️ Code Verification Agent
A dedicated security/production-readiness auditor — checks for SQL injection, exposed secrets, missing input validation, XSS, and other real vulnerability classes, then gives you a 0–100 readiness score and a downloadable, severity-ranked report.

### 💬 AI Chat, Done Properly
Real markdown & syntax-highlighted code blocks, multi-thread history, full visibility into what context is being sent, and slash commands (`/fix`, `/refactor`, `/test`, `/review`, `/commit`, and more). Chat is aware of every agent mode above and can explain or invoke them.

</td>
<td width="50%" valign="top">

### 🛡️ Security That's Actually Enforced
Open an unfamiliar folder and choose **Restricted Mode** — enforced *server-side*, across every file-write, search-replace, terminal session, and MCP call. Session-token authentication on privileged endpoints, strict path sandboxing (blocks symlink escapes and `..` traversal), sanitized terminal environments, encrypted API keys backed by your OS's native credential store, and rate limiting on mutating/streaming endpoints.

### 🖥️ A Real IDE Underneath
Monaco editor with tabs & split view, Git (status/diff/commit/branch/history), real symbol-indexed search, and a genuine PTY terminal that runs `vim` and interactive `git rebase -i` like the real thing.

### 🎨 4 Themes
Dark, Light, Void (true OLED minimalism), and a dual-accent **Cyberpunk** mode — each with a fully distinct, complete design system, not palette swaps.

</td>
</tr>
</table>

---

## 🏗️ Architecture

Electron Main Process (Node.js)
│ native PTYs · window · backend lifecycle
│ IPC
▼
React Frontend
│ Monaco · panels · Zustand state
│ HTTP / SSE / WebSocket
▼
FastAPI Backend (Python)
│ files · git · search · indexing · AI orchestration
│ aiosqlite
▼
SQLite → workspaces · settings · encrypted keys · index · jobs · history


| Layer | Tech |
|---|---|
| Desktop | Electron 33 |
| Frontend | React 18 · TypeScript · Zustand 5 · Tailwind CSS 3 · Monaco Editor · xterm.js · Vite 6 |
| Backend | Python 3.11+ · FastAPI 0.115 · Uvicorn · aiosqlite · GitPython · psutil · cryptography · keyring · watchdog · httpx |
| Terminal | node-pty (Electron) / pywinpty on Windows + ptyprocess on macOS/Linux (WebSocket fallback) |
| AI | Ollama · native Anthropic Messages API · OpenAI-compatible (OpenAI, Gemini, Groq, DeepSeek, Mistral, OpenRouter, NVIDIA NIM) |
| Security | Fernet-encrypted keys backed by OS keychain (`keyring`) · server-side trust enforcement · session-token auth · rate limiting · CSP |
| CI/CD | GitHub Actions — tests + build on every push, multi-platform installers on release |

---

## 🔐 Security

Every untrusted workspace runs in **Restricted Mode**, blocked at the API layer — not just hidden buttons. Every shell command needs explicit approval.

- **Session bearer-token authentication** on high-privilege endpoints
- **Strict path sandboxing** — blocks `~` expansion, symlink escapes, and `..` traversal
- **Terminal environment sanitization** — an explicit allowlist strips credentials (API keys, `AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`, etc.) before any shell command runs
- **API keys encrypted at rest** via Fernet, with the master key stored in your OS's native credential store (macOS Keychain, Windows Credential Manager, Linux Secret Service via `keyring`), falling back to a strictly-permissioned local file if unavailable
- **Rate limiting** on mutating and AI streaming endpoints
- **Content Security Policy** restricting network connectivity and script sources

**Known limitations, stated plainly:** no OS-level container/sandbox isolation for terminal execution (relies on the trust model + environment sanitization above, not hardware containerization); installers aren't code-signed yet; no formal third-party security audit has been performed yet — planned for a future release.

Full threat model & disclosure process → **[SECURITY.md](./SECURITY.md)** · **[docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md)**

---

## 📊 Project Status

This is real, working software, currently at **v1.0.0-beta.1** — actively developed and hardened through iterative testing, not a mockup.

✅ **Solid & verified:** core IDE (files, editor, Git, search, terminal), the full AI edit-proposal pipeline, the multi-agent system + Duo Loop + Coder + Dual Coder (including background job persistence), the Code Verification Agent, workspace trust enforcement swept across every route, session-token auth, OS-keychain-backed key encryption, a real automated test suite, CI/CD running on every push, multi-platform installer builds.

🛠️ **Coming in an upcoming update:** the plugin/extension system, macOS installer support, code signing for Windows/macOS installers, MCP server security scanning integration, LSP-based live diagnostics, and a formal third-party security audit.

Built iteratively, hardened by actually testing behavior — not by assuming code that compiles is code that works.

---

## 📚 Documentation

| Doc | What's in it |
|---|---|
| **[ARCHITECTURE.md](./ARCHITECTURE.md)** | Full system design, data flow, and component breakdown |
| **[SECURITY.md](./SECURITY.md)** | Security policy, reporting SLA, security controls summary |
| **[docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md)** | Trust boundaries, threats, and mitigations |
| **[FULL_README.md](./FULL_README.md)** | Complete technical specification and API documentation |
| **[ROADMAP.md](./ROADMAP.md)** | What's shipped, what's in progress, what's next |
| **[CONTRIBUTING.md](./CONTRIBUTING.md)** | How to set up, branch, and submit PRs |

---

## 🤝 Contributing

Bug reports, feature ideas, and pull requests are genuinely welcome — particularly around **plugin execution, macOS support, code signing, LSP integration, and testing improvements**, but any contribution counts. See **[CONTRIBUTING.md](./CONTRIBUTING.md)** to get set up. PRs need to pass CI (typecheck, build, backend test suite) before merge.

## 📄 License

This project is licensed under the MIT License — see [LICENSE](./LICENSE).

---

🔗 **Links**
LinkedIn: [Roopesh Ram Varma Kosuri](https://www.linkedin.com/in/roopesh-ram-varma-kosuri-28186a37b/)
X (Twitter): [@KosuriRoopesh](https://x.com/KosuriRoopesh)
