# CODE OS — Subsystem Expected vs. Actual Analysis

**Audit Date:** September 2026  
**Document:** Subsystem Promise vs. Reality Forensic Comparison  
**Baseline:** CODE OS v4.5 / Phase 9 Architecture

---

## 1. Agent Harness & Tool Execution

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Rollback Integrity** | Transactional undo/rollback restores exact pre-turn files with verified byte integrity. | Pre-turn checkpoints were created without content hashing; rollbacks did not verify restored file SHA-256 against pre-turn state. | Checkpoint manager computes pre-edit SHA-256 hashes; stage finalizer verifies disk content matches staged hash before and after apply. | **CLOSED** (AUD-002, commit 9285055) |
| **Token Estimation** | Provider-true token counting using native BPE/tiktoken tokenizers; UTF-8 multi-byte sequence fidelity in streams. | Character-length heuristic (`len/4`) led to budget overflows; raw byte splits caused unicode corruption in SSE streams. | Added `tiktoken` encoder with graceful fallback; UTF-8 byte boundary preservation in SSE streamer. | **CLOSED** (AUD-004, commit 9c98a04) |
| **Test Tool Truthfulness** | `run_test` execution returns honest status, exit code, and stdout/stderr; failure triggers repair/loop breakers. | Test runner swallowed failures, returning generic string output without failure flag; loop breakers never incremented. | Tool executor returns structured test results (`passed`, `returncode`, `output`); chat harness records failure and trips loop breaker after 3 repeats. | **CLOSED** (AUD-005, commit 95e55ab) |
| **Duo Loop Termination** | Generator-Critic loop converges on verifiable specification satisfaction. | Termination relies on max-round count or LLM prose heuristic rather than strict semantic exit criteria. | Tracked for semantic gate integration. | **OPEN** (AUD-001) |
| **Compaction Recovery** | Extreme context expansion fails closed safely without truncating essential system instructions. | Large payload compaction may drop required system context if token limits are exceeded abruptly. | Tracked for fail-closed compaction manager. | **OPEN** (AUD-003) |

---

## 2. Terminal & Process Lifecycle

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Windows Process Lifecycle** | Agentic terminal commands terminate cleanly within timeout or cancellation, leaving zero orphaned processes. | `terminate()` on Windows left child subprocess trees running indefinitely (e.g. `debugpy --wait-for-client`, `node.exe`). | Implemented bounded process group termination using `taskkill /PID {pid} /T /F` on Windows with timeout guards. | **CLOSED** (AUD-009, commit 0f1153d) |
| **Environment Sanitization** | Terminal subprocesses execute with sanitized environment variables excluding backend API keys and session tokens. | Initially inherited full backend `os.environ` prior to v4.5 remediation. | Sanitized environment verified; ongoing audits maintain strict key scrub. | **VERIFIED** |

---

## 3. Marathon Autopilot

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Git Commit Scope** | Autonomous task commits in Marathon mode commit strictly the files modified by that specific task step. | Checkpoint commits ran global `git add .`, accidentally staging and committing unrelated dirty files from the user's workspace. | Scoped `git add -- <touched_files>` ensuring strictly path-isolated task commits without sweeping unrelated changes. | **CLOSED** (AUD-008, commit dece572) |
| **Budget Guard** | Marathon halts execution if token or monetary budget reaches user-configured threshold. | Budget guard computes token costs accurately and pauses run before next task dispatch. | Working as expected. | **VERIFIED** |

---

## 4. Semantic RAG & Vector Index

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Path Traversal Security** | Workspace containment strictly enforced on all indexing, query, and file preview endpoints. | RAG route endpoints accepted user-supplied paths without canonicalization, allowing traversal outside workspace. | Added `normalize_path` and `ensure_within_workspace` to `rag_routes.py` and `vector_index_service.py`, raising 403 on escapes. | **CLOSED** (AUD-007, commit a2a5ebe) |
| **Semantic Retrieval** | Code retrieval ranks snippets using vector embeddings and AST hybrid search. | Hybrid search verified with local embeddings and AST chunker. | Working as expected. | **VERIFIED** |

---

## 5. SSE Transport & Real-Time UI Streams

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Stream Authentication** | Packaged Electron app connects to Team, Marathon, and Terminal streams with verified authorization. | Frontend stores (`teamStore`, `marathonStore`, `agenticTerminalStore`) use plain `EventSource(url)` without auth token; backend returns 401. | Implementing shared authenticated SSE helper + short-lived scoped stream tokens (`?token=`, TTL <= 60s). | **OPEN** (AUD-010, Phase 10.1 target) |
| **Reconnection & Hygiene** | Streams reconnect with exponential backoff on drop and cleanly unsubscribe on component unmount without leaks. | Ad-hoc reconnection in individual stores with potential duplicate listener leaks on rapid remount. | Unified lifecycle in shared SSE client helper with unmount cleanup. | **OPEN** (AUD-010, Phase 10.1 target) |

---

## 6. Multi-Agent Team Orchestration

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Step Durability** | Task steps write atomic progress to `task_steps` table in SQLite for reliable crash resumption. | `dag_engine.py` and `team/orchestrator.py` maintain in-memory state; step milestones are not consistently flushed to SQLite. | Tracked for Phase 10+ durability hardening. | **OPEN** (AUD-006) |
| **Role Separation** | Architect and Reviewer roles are strictly read-only; Coder and Tester roles can execute and repair. | Enforced in Phase 6.3 tool manifests; Reviewer and Documenter manifests exclude modifying tools. | Working as expected. | **VERIFIED** |

---

## 7. Sandboxing & Desktop Security

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Server-Side Sandbox Policy** | Commands from untrusted workspaces are forced into sandboxed container execution regardless of model prompt. | `require_sandbox` parameter was partially influenced by model tool call arguments. | Tracked for server-side policy enforcement. | **OPEN** (AUD-011) |
| **CaptureService Hardening** | Electron screenshot capture endpoint requires session authentication, enforces localhost origin, and disables webSecurity bypass. | Initial captureService allowed cross-origin access and unauthenticated capture. | Tracked for security lockdown. | **OPEN** (AUD-012) |

---

## 8. Memory & Self-Improvement

| Dimension | Expected / Stated Promise | Actual Behavior Before Phase 9 | Remediation State | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Autonomous Ingestion** | Failed tool runs, rejected diffs, and verification failures are automatically synthesized into lessons. | Ingestion requires explicit API calls; background auto-logging hook is not fully wired across all failure paths. | Tracked for automated feedback loop wiring. | **OPEN** (AUD-013) |
