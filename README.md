<!-- ![CODE OS](docs/logocodeos.png) -->

<div align="center">

# CODE OS

### A local-first AI IDE that plans, codes, and reviews your software — and never touches disk without your say-so.

<!-- Add badges once live:
[![CI](https://github.com/YOUR_USERNAME/Code-OS/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/Code-OS/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-informational)
![Made with Electron](https://img.shields.io/badge/Electron-33-47848F?logo=electron&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?logo=fastapi&logoColor=white)
-->

<!-- Add demo GIF once available: ![Demo](docs/demo.gif) -->

**[Getting Started](#-getting-started)** · **[Features](#-what-it-can-do)** · **[Architecture](#%EF%B8%8F-architecture)** · **[Security](#-security)** · **[Status](#-project-status)**

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

### Option A — Docker (fastest way to try it)

```bash
git clone <this-repo-url>
cd code-os
docker compose up
```

→ Frontend at `http://localhost:5173` · Backend at `http://localhost:8000`

> Docker runs CODE OS in browser mode — you get the full AI/agent experience, with a WebSocket-based terminal fallback instead of Electron's native PTY. For the complete desktop experience, use Option B.

### Option B — Full Desktop App

**You'll need:** Node.js 20+, Python 3.11+, and (Windows only) Build Tools for Visual Studio for the native terminal. [Ollama](https://ollama.com) is optional, for local models.

```bash
git clone <this-repo-url>
cd code-os

npm install
pip install -r backend/requirements.txt

npm run dev
```

That's it — Electron, the Vite dev server, and the FastAPI backend all start together. First launch walks you through a quick setup: accept the terms, optionally take the guided tour, then open your first folder and add your API key(s) under **Settings → AI Providers**.

**Want a packaged installer instead?**
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

```
Electron Main Process (Node.js)
   │  native PTYs · window · backend lifecycle
   │  IPC
   ▼
React Frontend
   │  Monaco · panels · Zustand state
   │  HTTP / SSE / WebSocket
   ▼
FastAPI Backend (Python)
   │  files · git · search · indexing · AI orchestration
   │  aiosqlite
   ▼
SQLite  →  workspaces · settings · encrypted keys · index · jobs · history
```

| Layer | Tech |
|---|---|
| Desktop | Electron 33 |
| Frontend | React 18 · TypeScript · Zustand · Tailwind · Monaco · xterm.js |
| Backend | Python · FastAPI · Uvicorn · aiosqlite |
| Terminal | node-pty (Electron) / pywinpty + ptyprocess (fallback) |
| AI | Ollama + OpenAI · Anthropic · Gemini · Groq · DeepSeek · Mistral · OpenRouter · NVIDIA NIM |
| Security | Fernet-encrypted keys · server-side trust enforcement |
| CI/CD | GitHub Actions — tests + build on every push, multi-platform installers on release |

---

## 🔐 Security

Every untrusted workspace runs in **Restricted Mode**, blocked at the API layer — not just hidden buttons. Every shell command needs explicit approval. API keys are encrypted at rest, never logged in plaintext, and spawned processes get their environment sanitized of anything credential-shaped.

Full threat model & disclosure process → **[SECURITY.md](./SECURITY.md)**

---

## 📊 Project Status

This is real, working software — not a mockup. In the interest of not overselling it:

✅ **Solid & verified:** core IDE (files, editor, Git, search, terminal), the full AI edit-proposal pipeline, the multi-agent system + Duo Loop (including background job persistence), workspace trust enforcement swept across every route, a real automated test suite.

🚧 **Known gaps, stated plainly:** the plugin/extension system currently discovers extensions but can't execute them yet; packaged installers still need Python on the host machine (a bundled standalone backend is planned); no formal third-party security audit has been done.

Built iteratively, hardened by actually testing behavior — not by assuming code that compiles is code that works.

---

## 🤝 Contributing

See **[CONTRIBUTING.md](./CONTRIBUTING.md)**. PRs need to pass CI (typecheck, build, backend test suite) before merge.

## 📄 License

This project is licensed under the MIT License — see [LICENSE](./LICENSE).


🔗 Links
LinkedIn: Roopesh Ram Varma Kosuri
X (Twitter): @KosuriRoopesh
<!--
## 🔗 Links
- Live demo:
- Video walkthrough:
-->
