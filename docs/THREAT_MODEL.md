# CODE OS — Architectural Threat Model

This document outlines the architectural trust boundaries, threat scenarios, implemented mitigations, and residual risks in CODE OS.

---

## Trust Boundaries

```
[ Electron Renderer / Browser UI ]
             │  (HTTP / WebSocket via Bearer Token + CSP)
             ▼
[ Python FastAPI Backend Service ]
             │
 ┌───────────┼───────────────┬─────────────────┐
 │           │               │                 │
 ▼           ▼               ▼                 ▼
[ SQLite ] [ File System ] [ Terminal PTY ] [ External AI APIs ]
```

---

## Trust Boundary 1: Renderer ↔ Backend Service

- **Assets at Risk**: File system integrity, session authentication tokens, API keys, local workspace code.
- **Threat Scenarios**:
  - Malicious web page loaded in renderer makes unauthorized API requests to `127.0.0.1:8000`.
  - Cross-Site Scripting (XSS) in Monaco editor or Markdown preview attempts data exfiltration.
- **Implemented Mitigations**:
  - **Bearer Token Auth**: Ephemeral 256-bit session token generated on backend startup and passed via stdout to Electron. Mutating endpoints require `Authorization: Bearer <session-token>`.
  - **Content Security Policy (CSP)**: `index.html` restricts `connect-src` to `localhost:8000` / `127.0.0.1:8000` and authorized AI provider domains.
  - **CORS Allowlist**: CORS origins restricted strictly to localhost Vite dev servers.
- **Unmitigated Risks**:
  - Local malware running as the same desktop user can inspect `~/.code-os/session_token`.

---

## Trust Boundary 2: Backend ↔ File System

- **Assets at Risk**: System files (`/etc/passwd`, `C:\Windows`), SSH keys (`~/.ssh/id_rsa`), environment files (`.env`).
- **Threat Scenarios**:
  - AI prompt or user path input uses `../` or symlinks to escape workspace root and read/overwrite system files.
  - Tilde (`~`) paths resolve to user home directory and leak private files.
- **Implemented Mitigations**:
  - **Path Normalization**: Client paths checked with `ensure_within_workspace`. `Path.resolve()` resolves all symlinks before checking `is_relative_to(workspace)`.
  - **Tilde Rejection**: `_reject_tilde()` throws HTTP 400 if client-supplied path starts with `~`.
  - **Workspace Trust Enforcement**: Restricted mode blocks file creation, modification, move, delete, and git mutations until user marks workspace as trusted.
- **Unmitigated Risks**:
  - Hard links pointing to files outside workspace are not explicitly blocked if `Path.resolve()` resolves inside workspace.

---

## Trust Boundary 3: Backend ↔ AI Provider APIs

- **Assets at Risk**: API keys, proprietary codebase contents.
- **Threat Scenarios**:
  - Plaintext master keys stored on disk stolen by malware.
  - AI responses contain prompt injection or malicious code proposals.
- **Implemented Mitigations**:
  - **OS Keyring Integration**: API keys encrypted using Fernet master key stored in macOS Keychain / Windows Credential Manager / Linux Secret Service (`keyring`). Fallback file enforces `chmod 600`.
  - **Proposal Review Workflow**: Edit proposals must be explicitly approved by user in Diff Inspector before writing to disk.
  - **Rate Limiting**: Sliding-window rate limiting prevents API quota exhaustion.
- **Unmitigated Risks**:
  - Prompts sent to external AI provider endpoints (Anthropic, OpenAI) are subject to third-party privacy policies.

---

## Trust Boundary 4: Backend ↔ Terminal / Subprocess Shell

- **Assets at Risk**: Environment credentials (`AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`), system stability.
- **Threat Scenarios**:
  - Terminal subshell inherits master process environment and leaks cloud secrets.
  - Terminal session started in untrusted directory executes untrusted repository scripts.
- **Implemented Mitigations**:
  - **Environment Allowlist**: Subprocesses executed with `_sanitize_env()`, stripping known secret environment variables while preserving `PATH`, `TERM`, `SSH_AGENT_PID`.
  - **Trust Gate**: Terminal creation in untrusted workspace returns HTTP 403.
- **Unmitigated Risks**:
  - Processes run with user OS privileges; no hardware-level container or sandbox (Docker/jail) is enforced around the terminal process.
