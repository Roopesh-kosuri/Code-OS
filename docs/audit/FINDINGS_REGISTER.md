# CODE OS — Comprehensive Audit Findings Register

**Audit Date:** September 2026  
**Scope:** Full-system audit of CODE OS (AI Harness, Terminal, Marathon, Team Orchestration, RAG, Security, Auth, Desktop, CI/CD)  
**Status Summary:** 14 findings CLOSED (verified in commits 0f1153d..3ff3d40) — ALL AUDIT FINDINGS REMEDIATED.

---

## Findings Table

| Finding ID | Subsystem | Severity | Description | Target Files | Status | Commit / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AUD-001** | Harness | High | Staging a nested new-file edit created parent directories BEFORE user approval; reject/timeout left artifact directories on disk. | `backend/app/features/ai/chat_harness.py` | **CLOSED** | **commit df22d9c**: `fix(staging): remove pre-approval mkdir during file staging (AUD-001)` |
| **AUD-002** | Harness | Critical | File edits and rollbacks lacked transactional SHA-256 pre/post state hash verification, allowing partial or corrupt rollbacks. | `backend/app/features/ai/harness/checkpoint_manager.py`, `backend/app/features/ai/harness/stage_finalizer.py` | **CLOSED** | **commit 9285055**: `fix(harness): transactional apply/rollback with hash verification (AUD-002)` |
| **AUD-003** | Harness | High | Cross-turn contamination check in content integrity was unwired from live conversation history snapshots, permitting copied prose into proposals. | `backend/app/features/ai/harness/content_integrity.py`, `backend/app/features/ai/harness/stage_finalizer.py`, `backend/app/features/ai/chat_harness.py` | **CLOSED** | **commit 0d70f96**: `fix(harness): wire live history into contamination integrity gate (AUD-003)` |
| **AUD-004** | Harness | Critical | Character-based token estimation underestimated BPE/tiktoken token counts; UTF-8 multi-byte chunk boundaries split during SSE token streaming. | `backend/app/features/ai/harness/payload_governor.py`, `backend/app/features/ai/harness/context_assembler.py`, `backend/app/features/ai/chat_harness.py`, `backend/app/features/ai/harness/sse_streamer.py` | **CLOSED** | **commit 9c98a04**: `fix(harness): provider-true tokenization + UTF-8 byte fidelity (AUD-004)` |
| **AUD-005** | Harness | High | Tool executor and agent tools masked test failures as generic string outputs; failed tests did not trigger consecutive-failure loop breakers. | `backend/app/features/ai/agents/agent_tools.py`, `backend/app/features/ai/harness/tool_executor.py`, `backend/app/features/ai/chat_harness.py` | **CLOSED** | **commit 95e55ab**: `fix(harness): honest test tool results, breaker integration (AUD-005)` |
| **AUD-006** | Team Mode | High | Escalation resolver resolved a DIFFERENT pending escalation via workspace/task substring or 'most recent pending' fallback, bypassing action_id isolation. | `backend/app/features/ai/harness/approval_coordinator.py`, `backend/app/features/ai/chat_harness_routes.py`, `backend/app/features/ai/team/team_routes.py` | **CLOSED** | **commit 5976221**: `fix(escalation): exact action_id required for all resolution paths (AUD-006)` |
| **AUD-007** | RAG | High | Vector index service and RAG endpoints accepted arbitrary paths without strict workspace containment, permitting traversal. | `backend/app/features/ai/rag/rag_routes.py`, `backend/app/features/ai/rag/vector_index_service.py` | **CLOSED** | **commit a2a5ebe**: `fix(rag): strict workspace path containment, reject escapes (AUD-007)` |
| **AUD-008** | Marathon | High | Marathon autopilot git checkpointing performed global staging (`git add .`), committing unrelated uncommitted user files into agent commits. | `backend/app/features/ai/marathon/marathon_executor.py` | **CLOSED** | **commit dece572**: `fix(marathon): path-scoped git commits, no unrelated dirty files (AUD-008)` |
| **AUD-009** | Terminal | Critical | Windows terminal process termination leaked orphaned process groups on timeout or cancellation; lacked bounded tree kill (`taskkill /T /F`). | `backend/app/features/ai/terminal/agentic_terminal_service.py` | **CLOSED** | **commit 0f1153d**: `fix(terminal): bounded Windows process-group termination (AUD-009)` |
| **AUD-010** | SSE Transport | Critical | Packaged-app Team Console, Marathon, and terminal live streams get 401 and never update: native EventSource cannot send Authorization headers and store URLs omit stream tokens. | `backend/app/main.py`, `backend/app/core/auth.py`, `src/features/ai/console/teamStore.ts`, `src/features/marathon/marathonStore.ts`, `src/features/terminal/agenticTerminalStore.ts` | **CLOSED** | **commit a469052**: `fix(sse): authenticated stream transport for team/marathon/terminal (AUD-010)` |
| **AUD-011** | Chat / Frontend | High | Rapid double-send mixed old stream tokens into the newest assistant bubble and stale finalizers could clear streaming state while a newer run was active. | `src/stores/aiStore.ts` | **CLOSED** | **commit 914139d**: `fix(chat): single-active-send queue isolates concurrent sends (AUD-011)` |
| **AUD-012** | RAG | High | Save bursts make RAG queue memory and latency unbounded because global queue lacked per-path coalescing and cancellation. | `backend/app/features/ai/rag/vector_index_service.py`, `backend/app/features/ai/rag/__init__.py` | **CLOSED** | **commit f373f13**: `fix(rag): bounded last-event-wins reindex queue with cancellation (AUD-012)` |
| **AUD-013** | Intelligence | High | Slow classification for old drafts caused prompt enhancer race condition where out-of-order completions overwrote current input UI. | `src/stores/intelligenceStore.ts` | **CLOSED** | **commit f238c3a**: `fix(intelligence): revision ID and abort gate for prompt enhancer (AUD-013)` |
| **AUD-014** | CI/Packaging | Medium | CI pipeline lacked mandatory security SAST / dependency auditing gates (`bandit`, `pip-audit`, `npm audit`) and release code signing verification. | `.github/workflows/ci.yml`, `electron-builder.yml`, `pyproject.toml`, `scripts/verify-release-signing.js`, `.security-exceptions.json` | **CLOSED** | **commit 3ff3d40**: `fix(ci): mandatory security gates and release signing verification (AUD-014)` |
| **AUD-016** | Monaco / Editor | High | Blank lines appeared between every line of code on file open/close/reopen cycles due to Windows text mode `\r\n` -> `\r\r\n` -> `\n\n` doubling. | `backend/app/features/files/service.py`, `src/features/editor/EditorWorkspace.tsx`, `src/stores/editorStore.ts` | **CLOSED** | **commit d6581f9**: `fix(editor): resolve Monaco double line-spacing bug across CRLF/LF open/close cycles (AUD-016)` |

---

## Resolution Accounting

- **Total Findings:** 15
- **Closed Findings (15):** AUD-001, AUD-002, AUD-003, AUD-004, AUD-005, AUD-006, AUD-007, AUD-008, AUD-009, AUD-010, AUD-011, AUD-012, AUD-013, AUD-014, AUD-016
- **Open Findings (0):** None
- **Remediation Status:** 100% COMPLETE — ALL 15 AUDIT FINDINGS CLOSED
