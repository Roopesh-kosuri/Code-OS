<div align="center">

# CODE OS

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

**[Getting Started](#-getting-started)** · **[Features](#-what-it-can-do)** · **[Architecture](#%EF%B8%8F-architecture)** · **[Security](#-security)** · **[Status](#-project-status)** · **[Docs](#-documentation)**

</div>

---

## ⚡ Why CODE OS

Most "AI IDEs" are a chat box bolted onto a text editor. CODE OS is built differently:

- 🧠 **5 specialized agents** — Planner, Coder, Reviewer, Tester, Documenter — that plan, write, self-review, and test code as one coordinated system, not a single chat wrapper
- 🔒 **Nothing runs or writes without your approval** — every AI-proposed change goes through a diff you review; every shell command needs an explicit click
- 🌐 **9 AI providers, your choice** — Ollama locally, or bring your own key for OpenAI, Anthropic, Gemini, Groq, DeepSeek, Mistral, OpenRouter, or NVIDIA NIM
- ⚔️ **Duo Loop** — two models argue it out (Generator vs. Critic) until the code is actually good, before you ever see it
- 💻 **A real terminal** — genuine PTY support (`vim`, `git rebase -i`, REPLs), not a fake command box
- 🎨 **7 themes**, including a proper Cyberpunk mode

Everything runs on your machine. Your code never leaves it, except to whichever AI provider you explicitly choose, with your own key.

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

> Docker runs CODE OS in browser mode — you get the full AI/agent experience, with a WebSocket-based terminal fallback instead of Electron's native PTY. For the complete desktop experience, use Option B.

### Option B — Full Desktop App

Unlike Docker, this requires a few things installed **on your machine first** — these are language runtimes CODE OS depends on, not something CODE OS can install for itself (no project can bootstrap its own runtime — `npm` ships with Node, `pip` ships with Python, so both need to already exist before either can be used).

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

**Want a packaged installer instead?**
```bash
npm run package
```
Builds a `.exe` (Windows), `.dmg` (macOS), or `.AppImage`/`.deb` (Linux) via `electron-builder`.

> ℹ️ The packaged installer still expects Python on the host machine — a fully bundled standalone backend (no separate Python install needed) is on the roadmap for an upcoming release.
> ℹ️ **macOS:** since installer builds aren't code-signed yet, Gatekeeper will block the `.app` on first open. Right-click → Open, or run `xattr -d com.apple.quarantine /Applications/CODE\ OS.app`.

---

## 🧩 What It Can Do

<table>
<tr>
<td width="50%" valign="top">

### 🧠 Multi-Agent System
Five agents, one job engine. **CoderAgent** is the flagship — it grounds every plan in your real codebase (indexed symbols, imports, dependencies), writes multi-file changes as one coherent unit, self-reviews its own diffs, runs your test suite on itself, and calls in a second opinion (Duo Loop) for anything risky. Tasks run as real background jobs — switch panels all you want, they keep going.

### ⚔️ Duo Loop
Pick a Generator and a Critic — any mix of local and API models — and let them go back and forth until the Critic actually approves, capped at a safe round limit. You only see the final, vetted result.

### 💬 AI Chat, Done Properly
Real markdown & syntax-highlighted code blocks, multi-thread history, full visibility into what context is being sent, and slash commands (`/fix`, `/refactor`, `/test`, `/review`, and more).

</td>
<td width="50%" valign="top">

### 🛡️ Security That's Actually Enforced
Open an unfamiliar folder and choose **Restricted Mode** — and it's enforced *server-side*, across every file-write, search-replace, terminal session, and MCP call. Not a UI suggestion. A real boundary.

### 🖥️ A Real IDE Underneath
Monaco editor with tabs & split view, Git (status/diff/commit/branch/history), real symbol-indexed search, and a genuine PTY terminal that runs `vim` and interactive `git rebase -i` like the real thing.

### 🎨 7 Themes
Dark, Light, Crimson, Navy, Void, Violet, and a proper dual-accent **Cyberpunk** mode — not just palette swaps.

</td>
</tr>
</table>

---

## 🏗️ Architecture

\`\`\`mermaid
flowchart TD
    A["Electron Main Process (Node.js)<br/>native PTYs · window · backend lifecycle"]
    B["React Frontend<br/>Monaco · panels · Zustand state"]
    C["FastAPI Backend (Python)<br/>files · git · search · indexing · AI orchestration"]
    D[("SQLite<br/>workspaces · settings · encrypted keys · index · jobs · history")]

    A -- IPC --> B
    B -- "HTTP / SSE / WebSocket" --> C
    C -- aiosqlite --> D
\`\`\`

*(Diagram renders natively on GitHub.)*

| Layer | Tech |
|---|---|
| Desktop | Electron 33 |
| Frontend | React 18 · TypeScript · Zustand · Tailwind · Monaco · xterm.js |
| Backend | Python · FastAPI · Uvicorn · aiosqlite |
| Terminal | node-pty (Electron) / pywinpty on Windows + ptyprocess on macOS/Linux (WebSocket fallback) |
| Git | GitPython |
| AI | Ollama + OpenAI · Anthropic · Gemini · Groq · DeepSeek · Mistral · OpenRouter · NVIDIA NIM |
| Security | Fernet-encrypted keys · server-side trust enforcement |
| CI/CD | GitHub Actions — tests + build on every push, multi-platform installers on release |

---

## 🔐 Security

Every untrusted workspace runs in **Restricted Mode**, blocked at the API layer — not just hidden buttons. Every shell command needs explicit approval. API keys are encrypted at rest, never logged in plaintext, and spawned processes get their environment sanitized of anything credential-shaped.

A formal third-party security audit hasn't happened yet — **planned for Q3 2026 in collaboration with external auditors** as part of an upcoming hardening release, and it'll be linked here the moment it's done.

Full threat model & disclosure process → **[SECURITY.md](./SECURITY.md)**

---

## 📊 Project Status

This is real, working software — actively developed and hardened through iterative testing, not a mockup. Community feedback is shaping upcoming releases:

✅ **Solid & verified:** core IDE (files, editor, Git, search, terminal), the full AI edit-proposal pipeline, the multi-agent system + Duo Loop (including background job persistence), workspace trust enforcement swept across every route, a real automated test suite, CI/CD running on every push via GitHub Actions.

🛠️ **Coming in an upcoming update:** the plugin/extension system currently discovers extensions but can't execute them yet — full execution support is next up. A bundled standalone backend (so the installer no longer needs a separate Python install) is also in progress, and a formal third-party security audit is **planned for Q3 2026 in collaboration with external auditors**.

Built iteratively, hardened by actually testing behavior — not by assuming code that compiles is code that works.

---

## 📚 Documentation

All project docs in one place, so you don't have to go hunting:

| Doc | What's in it |
|---|---|
| **[ARCHITECTURE.md](./ARCHITECTURE.md)** | Full system design, data flow, and component breakdown |
| **[SECURITY.md](./SECURITY.md)** | Threat model, Restricted Mode enforcement, disclosure process |
| **[ROADMAP.md](./ROADMAP.md)** | What's shipped, what's in progress, what's next |
| **[CONTRIBUTING.md](./CONTRIBUTING.md)** | How to set up, branch, and submit PRs |

---

## 🤝 Contributing

Bug reports, feature ideas, and pull requests are genuinely welcome — particularly around **plugin execution, new AI provider integrations, security hardening, UI themes, and testing improvements**, but any contribution counts. See **[CONTRIBUTING.md](./CONTRIBUTING.md)** to get set up. PRs need to pass CI (typecheck, build, backend test suite) before merge.

## 📄 License

This project is licensed under the MIT License — see [LICENSE](./LICENSE).

---

🔗 **Links**
LinkedIn: [Roopesh Ram Varma Kosuri](https://www.linkedin.com/in/roopesh-ram-varma-kosuri-28186a37b/)
X (Twitter): [@KosuriRoopesh](https://x.com/KosuriRoopesh)
