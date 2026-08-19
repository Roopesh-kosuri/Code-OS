<div align="center">

# CODE-OS (v2.4.0)

### A local-first AI IDE that plans, codes, reviews, and runs your software — with strict server-side boundaries and zero telemetry leaks.

[![CI/CD](https://github.com/Roopesh-kosuri/code-os/actions/workflows/ci.yml/badge.svg)](https://github.com/Roopesh-kosuri/code-os/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-brightgreen.svg)]()
[![Electron](https://img.shields.io/badge/Electron-33-47848F.svg)](https://www.electronjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)

<br>

### ▶️ Demo & Website

🌐 [**CODE OS Website**](https://roopesh-kosuri.github.io/websitecodeos/) · 📹 [**Watch Demo Video**](https://www.youtube.com/watch?v=2LZ2V9nhz34)

**[Getting Started](#-getting-started)** · **[Key Features](#-what-it-can-do)** · **[Architecture](#%EF%B8%8F-architecture)** · **[Security Model](#-security-architecture)** · **[Docs](#-documentation)**

</div>

---

## ⚡ Why CODE OS?

Most "AI IDEs" are simply a chat box bolted onto a text editor. CODE OS is designed from the ground up as an agentic developer operating system:

- 🧠 **5 Specialized Agents** — Planner, Coder, Reviewer, Tester, and Documenter work as a coordinated team with AST symbol indexing and dependency mapping.
- 🔒 **Zero Unapproved Writes** — Every AI-proposed change generates an interactive diff for user approval before anything touches disk.
- 🌐 **9 AI Providers Supported** — 100% offline with Ollama, or bring your own key for Google Gemini, Groq, OpenAI, Anthropic Claude, DeepSeek, Mistral, OpenRouter, or NVIDIA NIM.
- ⚔️ **Duo Loop Engine** — Automated adversarial generator-vs-critic debates that refine code quality before presenting final proposals.
- 🚀 **Native Multi-Language Runner** — Integrated execution (`Ctrl+Shift+R` / `F5`) with auto toolchain detection across Python, JS/TS, C/C++, Rust, Go, Java, and PowerShell with memory limits and instant process kill.
- 👁️ **Offscreen Vision & VLM QA** — Electron offscreen rendering pool for automated UI defect analysis and visual regression testing.
- 💻 **True PTY Terminal** — Full pseudo-terminal support (`node-pty` / `pywinpty`) capable of running `vim`, interactive `git rebase -i`, and real REPLs.
- 🎨 **7 Polished Themes** — Cyberpunk, Void, Dark, Light, Crimson, Navy, and Violet.

Everything runs on your local machine. Your code never leaves your computer, except to whichever AI provider you explicitly configure.

---

## 🚀 Getting Started

### Prerequisites

- **Node.js 20+** — [nodejs.org](https://nodejs.org)
- **Python 3.11+** — [python.org](https://python.org)
- **Git**
- **C++ Build Tools** (for native `node-pty` terminal compilation):
  - **Windows**: [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (Desktop C++ workload)
  - **macOS**: `xcode-select --install`
  - **Linux**: `sudo apt-get install -y build-essential python3`

---

### Installation & Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/roopesh-kosuri/code-os.git
   cd code-os
   ```

2. **Install dependencies:**
   ```bash
   npm install
   pip install -r backend/requirements.txt
   ```

3. **Configure environment (optional):**
   ```bash
   cp .env.example .env
   ```

4. **Launch the development environment:**
   ```bash
   npm run dev
   ```
   *This starts the FastAPI backend (`http://127.0.0.1:8000`), the Vite frontend, and the Electron desktop application concurrently.*

---

### Docker Quickstart (Browser Mode)

Run CODE OS in browser mode without configuring local Node/Python runtimes:

```bash
docker compose up
```
- **Frontend UI**: `http://localhost:5173`
- **Backend API**: `http://localhost:8000`
- **Health Check**: `http://localhost:8000/health` → `{"status": "ok"}`

---

## 🧩 What It Can Do

| Capability | Description |
|---|---|
| **Autonomous Multi-Agent System** | Coordinates Planner, Coder, Reviewer, Tester, and Documenter on complex multi-file engineering tasks with background job queues. |
| **Duo Adversarial Loop** | Dual-model debate engine (Generator vs. Critic) that iterates until rigorous criteria are satisfied. |
| **Interactive Diff Proposal Engine** | Real-time line-by-line diff review with side-by-side Monaco comparison before applying changes. |
| **Multi-Language Runner** | One-click execution with sandboxed memory governors (512MB RAM cap) and execution timeouts (60s). |
| **Repository Intelligence Indexer** | AST symbol extraction, cross-file reference tracking, import graph analysis, and convention learning. |
| **Restricted Mode Security** | Server-enforced read-only workspace containment blocking file mutation, execution, and secret leaks on untrusted repos. |
| **Offline Privacy Mode** | Complete offline support via local Ollama models with zero external network connectivity required. |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Electron Desktop Shell                      │
│   Native PTY Subprocesses · Window Management · IPC         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     React 18 Frontend                       │
│   Monaco Editor · Zustand Stores · Tailwind CSS · xterm.js  │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / SSE / WebSocket
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend Core                      │
│   Agent Harness · Code Intelligence · Multi-Language Runner  │
│   Restricted Mode Guard · Session Token Auth · Vision Pool  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   Local Storage & Persistence               │
│   SQLite (Encrypted API Keys, Jobs, Workspaces, Index)      │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack Breakdown

- **Desktop Shell**: Electron 33, `node-pty` 1.1
- **Frontend UI**: React 18, TypeScript 5.7, Tailwind CSS 3, Zustand 5, Monaco Editor, xterm.js, Vite 6
- **Backend API**: Python 3.11+, FastAPI 0.115, Uvicorn, aiosqlite, GitPython, psutil, httpx
- **Security & Crypto**: Cryptography (Fernet), OS Keychain (`keyring`), Session Bearer Tokens

---

## 🛡️ Security Architecture

CODE OS implements multi-layer defense-in-depth across the entire stack:

1. **Workspace Trust Model**: Untrusted workspaces boot in **Restricted Mode**. File writes, shell executions, search-and-replace mutations, and MCP calls are blocked server-side by FastAPI middleware.
2. **Strict Path Sandboxing**: Client-supplied paths are validated using `ensure_within_workspace`, blocking tilde expansion, symlink escape, and path traversal attacks.
3. **Session Token Authentication**: High-privilege API routes require a cryptographically generated 256-bit bearer token (`Authorization: Bearer <session-token>`).
4. **Environment Sanitization**: Subprocess runners execute with an explicit environment allowlist, stripping cloud credentials (`AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`, etc.).
5. **Encrypted Key Storage**: API keys are encrypted at rest with Fernet symmetric encryption and stored in OS-native credential storage (Windows Credential Manager, macOS Keychain, Linux Secret Service).
6. **Rate Limiting & Memory Governors**: Sliding-window rate limiters prevent API quota exhaustion; memory monitors enforce hard process RAM limits.

---

## 📚 Documentation

- [**CHANGELOG.md**](./CHANGELOG.md) — Release notes and detailed feature history.
- [**SECURITY.md**](./SECURITY.md) — Security policies, vulnerability disclosure, and threat mitigations.
- [**ARCHITECTURE.md**](./ARCHITECTURE.md) — Deep architectural specification and module breakdown.
- [**CONTRIBUTING.md**](./CONTRIBUTING.md) — Contribution guidelines and development workflows.
- [**.env.example**](./.env.example) — Full environment variable reference.

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](./LICENSE) for more information.

---

<div align="center">
  <sub>Developed by <b>Roopesh Kosuri</b>. Contributions and feedback are welcome!</sub>
</div>
