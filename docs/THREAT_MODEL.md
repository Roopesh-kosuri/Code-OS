# CODE OS — Architectural Threat Model (v3.1.0)

This document outlines the architectural trust boundaries, threat scenarios, implemented mitigations, and residual risks in CODE OS.

---

## System Architecture & Trust Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│              Electron Renderer / Browser UI                 │
│      (Monaco Editor, Xterm.js, Diff Viewer, AI Chat)        │
└──────────────────────────────┬──────────────────────────────┘
                               │ (HTTP / WebSocket via Bearer Token + CSP)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              Python FastAPI Backend Supervisor              │
│  (Auth Middleware, RequestID, Rate Limiter, Event Bus)      │
└──────┬───────────────┬───────────────┬───────────────┬──────┘
       │               │               │               │
       ▼               ▼               ▼               ▼
┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
│ SQLite + WAL ││ File System  ││ Terminal PTY ││ AI Providers │
│ (Durable DB, ││ (Containment,││ (Env Scrub,  ││ & MCP Servers│
│  Orphan Reap)││  Symlink Chk)││  Trust Gate) ││ (AES-GCM Key)│
└──────────────┘└──────────────┘└──────────────┘└──────────────┘
```

---

## Trust Boundary 1: Renderer ↔ Backend Service

- **Assets at Risk**: File system integrity, session authentication tokens, API keys, local workspace code.
- **Threat Scenarios**:
  - Malicious web page loaded in renderer makes unauthorized API requests to `127.0.0.1:8000`.
  - Cross-Site Scripting (XSS) in Monaco editor or Markdown preview attempts data exfiltration.
- **Implemented Mitigations**:
  - **Bearer Token Auth**: Ephemeral 256-bit session token generated on backend startup and passed via stdout to Electron. Mutating endpoints require `Authorization: Bearer <session-token>` verified via constant-time comparison (`secrets.compare_digest`).
  - **Content Security Policy (CSP)**: `index.html` restricts `connect-src` to `localhost:8000` / `127.0.0.1:8000` and authorized AI provider domains.
  - **CORS Allowlist**: CORS origins restricted strictly to localhost Vite dev servers.
- **Unmitigated Risks**:
  - Local malware running as the same desktop user can inspect `~/.code-os/session_token`.

---

## Trust Boundary 2: Backend ↔ File System & Path Containment

- **Assets at Risk**: System files (`/etc/passwd`, `C:\Windows`), SSH keys (`~/.ssh/id_rsa`), environment files (`.env`).
- **Threat Scenarios**:
  - AI prompt or user path input uses `../`, `..\`, UNC shares (`\\evil\share`), or symlinks to escape workspace root.
  - Null byte injections (`file\x00.txt`) or Unicode homoglyphs attempt path canonicalization bypass.
- **Implemented Mitigations**:
  - **Path Normalization**: Client paths checked with `ensure_within_workspace`. `Path.resolve()` resolves all symlinks before checking `is_relative_to(workspace)`.
  - **UNC and Device Path Rejection**: `_reject_dangerous_prefixes()` strictly rejects `\\`, `//`, `\\?\`, and `\\.\` paths to prevent Windows SMB network stalls and share escapes.
  - **Tilde & Null Byte Rejection**: Immediate 400 rejection for tilde (`~`) and null bytes (`\x00`).
  - **Workspace Trust Enforcement**: Restricted mode blocks file creation, modification, move, delete, and git mutations until user marks workspace as trusted.
  - **Debugger Workspace Containment**: `start_debugger` and `set_breakpoint` handlers validate file and breakpoint targets against `ensure_within_workspace`.
- **Property Testing Validation**:
  - Automated Hypothesis property suite validates 600+ edge-case paths with zero workspace escapes.

---

## Trust Boundary 3: Durable Execution, WAL & State Machine (Phase 3)

- **Assets at Risk**: Job execution consistency, pending code changes, database integrity during sudden process crashes.
- **Threat Scenarios**:
  - Backend crashes mid-step leaving orphaned subprocesses or corrupted database state.
  - Race conditions during concurrent approval actions or rapid step dispatch.
- **Implemented Mitigations**:
  - **Write-Ahead Logging (WAL)**: SQLite database configured in WAL mode with `busy_timeout = 5000ms` and `synchronous = NORMAL` for atomic crash resilience.
  - **Orphan Job Reaper**: Background reaper reclaims or fails dead jobs on startup using lease expiry checks (`heartbeat_timeout = 30s`).
  - **Persistent Approval State Machine**: Multi-step proposals are persisted with cryptographic step hashes preventing re-execution or step tampering.
  - **Graceful Pause & Resume**: Task runners persist execution snapshots enabling pause/resume without state drift.

---

## Trust Boundary 4: MCP Server Trust Boundary (Phase 2.6)

- **Assets at Risk**: Local shell execution, arbitrary tool invocations from third-party MCP servers.
- **Threat Scenarios**:
  - Malicious GitHub repository contains auto-executable MCP server configs in `package.json` or `README.md`.
  - Server-Side Request Forgery (SSRF) targeting local network or cloud metadata services via HTTP MCP endpoints.
- **Implemented Mitigations**:
  - **Strict Domain Whitelisting**: MCP GitHub scanning is strictly constrained to `github.com` and `raw.githubusercontent.com`.
  - **Explicit User Approval Gate**: Auto-discovered MCP servers are registered with `enabled = False` and require explicit user toggle and approval before launching.
  - **Command Validation**: Stdio commands are restricted to authorized binaries (`npx`, `uvx`, `python`, `node`) with dangerous flags stripped.

---

## Trust Boundary 5: AI Provider APIs & Key Management (Phase 4)

- **Assets at Risk**: Provider API keys (OpenAI, Anthropic, Gemini, DeepSeek, Moonshot, Qwen, GLM, xAI, Mistral, Groq, Cohere, NVIDIA NIM).
- **Threat Scenarios**:
  - Plaintext master keys stored on disk stolen by malware.
  - Prompt injection attacks in LLM output crafting malicious diffs.
- **Implemented Mitigations**:
  - **OS Keyring & AES-GCM**: API keys encrypted with Fernet / AES-GCM master keys stored in OS Keychain / Credential Manager.
  - **Multi-Format Robust Proposal Parsing**: Fuzzed parsers sanitize and isolate code diffs with mandatory user confirmation in the Diff Viewer before disk write.
  - **Provider Health Monitoring & Circuit Breakers**: Automatic failover routes around degraded endpoints without exposing credentials.
