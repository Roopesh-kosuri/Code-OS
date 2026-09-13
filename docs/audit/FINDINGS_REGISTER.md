# CODE OS — Phase 9 Comprehensive Audit Findings Register

**Audit Date:** September 2026  
**Scope:** Full-system audit of CODE OS (AI Harness, Terminal, Marathon, Team Orchestration, RAG, Security, Auth, Desktop)  
**Status Summary:** 10 findings CLOSED (verified in commits 0f1153d..914139d), 4 findings OPEN (tracked in Phase 10.3+).

---

## Findings Table

| Finding ID | Subsystem | Severity | Description | Target Files | Status | Commit / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AUD-001** | Harness | High | Staging a nested new-file edit created parent directories BEFORE user approval; reject/timeout left artifact directories on disk. | `backend/app/features/ai/chat_harness.py` | **CLOSED** | **commit df22d9c**: `fix(staging): remove pre-approval mkdir during file staging (AUD-001)` |
| **AUD-002** | Harness | Critical | File edits and rollbacks lacked transactional SHA-256 pre/post state hash verification, allowing partial or corrupt rollbacks. | `backend/app/features/ai/harness/checkpoint_manager.py`, `backend/app/features/ai/harness/stage_finalizer.py` | **CLOSED** | **commit 9285055**: `fix(harness): transactional apply/rollback with hash verification (AUD-002)` |
| **AUD-003** | Harness | High | Large context compaction failure can lead to unhandled overflow without explicit fail-closed recovery for extreme token payloads. | `backend/app/features/ai/harness/payload_governor.py`, `backend/app/features/ai/harness/compaction_manager.py` | **OPEN** | Tracked for Phase 10.3+ hardening. |
| **AUD-004** | Harness | Critical | Character-based token estimation underestimated BPE/tiktoken token counts; UTF-8 multi-byte chunk boundaries split during SSE token streaming. | `backend/app/features/ai/harness/payload_governor.py`, `backend/app/features/ai/harness/context_assembler.py`, `backend/app/features/ai/chat_harness.py`, `backend/app/features/ai/harness/sse_streamer.py` | **CLOSED** | **commit 9c98a04**: `fix(harness): provider-true tokenization + UTF-8 byte fidelity (AUD-004)` |
| **AUD-005** | Harness | High | Tool executor and agent tools masked test failures as generic string outputs; failed tests did not trigger consecutive-failure loop breakers. | `backend/app/features/ai/agents/agent_tools.py`, `backend/app/features/ai/harness/tool_executor.py`, `backend/app/features/ai/chat_harness.py` | **CLOSED** | **commit 95e55ab**: `fix(harness): honest test tool results, breaker integration (AUD-005)` |
| **AUD-006** | Team Mode | High | Escalation resolver resolved a DIFFERENT pending escalation via workspace/task substring or "most recent pending" fallback, bypassing action_id isolation. | `backend/app/features/ai/harness/approval_coordinator.py`, `backend/app/features/ai/chat_harness_routes.py`, `backend/app/features/ai/team/team_routes.py` | **CLOSED** | **commit 5976221**: `fix(escalation): exact action_id required for all resolution paths (AUD-006)` |
| **AUD-007** | RAG | High | Vector index service and RAG endpoints accepted arbitrary paths without strict workspace containment, permitting traversal. | `backend/app/features/ai/rag/rag_routes.py`, `backend/app/features/ai/rag/vector_index_service.py` | **CLOSED** | **commit a2a5ebe**: `fix(rag): strict workspace path containment, reject escapes (AUD-007)` |
| **AUD-008** | Marathon | High | Marathon autopilot git checkpointing performed global staging (`git add .`), committing unrelated uncommitted user files into agent commits. | `backend/app/features/ai/marathon/marathon_executor.py` | **CLOSED** | **commit dece572**: `fix(marathon): path-scoped git commits, no unrelated dirty files (AUD-008)` |
| **AUD-009** | Terminal | Critical | Windows terminal process termination leaked orphaned process groups on timeout or cancellation; lacked bounded tree kill (`taskkill /T /F`). | `backend/app/features/ai/terminal/agentic_terminal_service.py` | **CLOSED** | **commit 0f1153d**: `fix(terminal): bounded Windows process-group termination (AUD-009)` |
| **AUD-010** | SSE Transport | Critical | Packaged-app Team Console, Marathon, and terminal live streams get 401 and never update: native EventSource cannot send Authorization headers and store URLs omit stream tokens. | `backend/app/main.py`, `backend/app/core/auth.py`, `src/features/ai/console/teamStore.ts`, `src/features/marathon/marathonStore.ts`, `src/features/terminal/agenticTerminalStore.ts` | **CLOSED** | **commit a469052**: `fix(sse): authenticated stream transport for team/marathon/terminal (AUD-010)` |
| **AUD-011** | Chat / Frontend | High | Rapid double-send mixed old stream tokens into the newest assistant bubble and stale finalizers could clear streaming state while a newer run was active. | `src/stores/aiStore.ts` | **CLOSED** | **commit 914139d**: `fix(chat): single-active-send queue isolates concurrent sends (AUD-011)` |
| **AUD-012** | Desktop | High | Electron `captureService.ts` lacked session token requirement on `/capture`, used overly permissive CORS, and had potential SSRF surfaces. | `electron/services/captureService.ts` | **OPEN** | Tracked for Phase 10.3+ hardening. |
| **AUD-013** | Memory | Medium | Self-improving memory lacked automated ingestion hooks from failed test runs and rejected staging diffs, requiring manual lesson creation. | `backend/app/features/ai/memory/memory_service.py` | **OPEN** | Tracked for Phase 10.3+ hardening. |
| **AUD-014** | CI/Packaging | Medium | CI pipeline lacked mandatory security SAST / dependency auditing gates (`bandit`, `pip-audit`, `npm audit`) and release code signing verification. | `.github/workflows/ci.yml`, `electron-builder.yml` | **OPEN** | Tracked for Phase 10.3+ hardening. |

---

## Resolution Accounting

- **Total Findings:** 14
- **Closed Findings (10):** AUD-001, AUD-002, AUD-004, AUD-005, AUD-006, AUD-007, AUD-008, AUD-009, AUD-010, AUD-011
- **Open Findings (4):** AUD-003, AUD-012, AUD-013, AUD-014
- **Next Phase in Sequence:** Phase 10.3 (Batch 4 — Remaining Hardening: AUD-003, AUD-012, AUD-013, AUD-014)



---

## Findings Table

| Finding ID | Subsystem | Severity | Description | Target Files | Status | Commit / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AUD-001** | Duo / Harness | High | Generator-Critic loop termination lacks semantic completion gate; relies on turn-count heuristic rather than verified resolution. | `backend/app/features/ai/duo/service.py`, `backend/app/features/ai/chat_harness.py` | **OPEN** | Tracked for Phase 10+ hardening. |
| **AUD-002** | Harness | Critical | File edits and rollbacks lacked transactional SHA-256 pre/post state hash verification, allowing partial or corrupt rollbacks. | `backend/app/features/ai/harness/checkpoint_manager.py`, `backend/app/features/ai/harness/stage_finalizer.py` | **CLOSED** | **commit 9285055**: `fix(harness): transactional apply/rollback with hash verification (AUD-002)` |
| **AUD-003** | Harness | High | Large context compaction failure can lead to unhandled overflow without explicit fail-closed recovery for extreme token payloads. | `backend/app/features/ai/harness/payload_governor.py`, `backend/app/features/ai/harness/compaction_manager.py` | **OPEN** | Tracked for Phase 10+ hardening. |
| **AUD-004** | Harness | Critical | Character-based token estimation underestimated BPE/tiktoken token counts; UTF-8 multi-byte chunk boundaries split during SSE token streaming. | `backend/app/features/ai/harness/payload_governor.py`, `backend/app/features/ai/harness/context_assembler.py`, `backend/app/features/ai/chat_harness.py`, `backend/app/features/ai/harness/sse_streamer.py` | **CLOSED** | **commit 9c98a04**: `fix(harness): provider-true tokenization + UTF-8 byte fidelity (AUD-004)` |
| **AUD-005** | Harness | High | Tool executor and agent tools masked test failures as generic string outputs; failed tests did not trigger consecutive-failure loop breakers. | `backend/app/features/ai/agents/agent_tools.py`, `backend/app/features/ai/harness/tool_executor.py`, `backend/app/features/ai/chat_harness.py` | **CLOSED** | **commit 95e55ab**: `fix(harness): honest test tool results, breaker integration (AUD-005)` |
| **AUD-006** | Team Mode | High | Team DAG scheduler orphaned step durability in `step_tracker.py`; task step progress lacked transactional milestone checkpoints. | `backend/app/features/ai/team/orchestrator.py`, `backend/app/features/ai/step_tracker.py` | **OPEN** | Tracked for Phase 10+ hardening. |
| **AUD-007** | RAG | High | Vector index service and RAG endpoints accepted arbitrary paths without strict workspace containment, permitting traversal. | `backend/app/features/ai/rag/rag_routes.py`, `backend/app/features/ai/rag/vector_index_service.py` | **CLOSED** | **commit a2a5ebe**: `fix(rag): strict workspace path containment, reject escapes (AUD-007)` |
| **AUD-008** | Marathon | High | Marathon autopilot git checkpointing performed global staging (`git add .`), committing unrelated uncommitted user files into agent commits. | `backend/app/features/ai/marathon/marathon_executor.py` | **CLOSED** | **commit dece572**: `fix(marathon): path-scoped git commits, no unrelated dirty files (AUD-008)` |
| **AUD-009** | Terminal | Critical | Windows terminal process termination leaked orphaned process groups on timeout or cancellation; lacked bounded tree kill (`taskkill /T /F`). | `backend/app/features/ai/terminal/agentic_terminal_service.py` | **CLOSED** | **commit 0f1153d**: `fix(terminal): bounded Windows process-group termination (AUD-009)` |
| **AUD-010** | SSE Transport | Critical | Packaged-app Team Console, Marathon, and terminal live streams get 401 and never update: native EventSource cannot send Authorization headers and store URLs omit stream tokens. | `backend/app/main.py`, `backend/app/core/auth.py`, `src/features/ai/console/teamStore.ts`, `src/features/marathon/marathonStore.ts`, `src/features/terminal/agenticTerminalStore.ts` | **CLOSED** | **commit a469052**: `fix(sse): authenticated stream transport for team/marathon/terminal (AUD-010)` |
| **AUD-011** | Security | Critical | Sandbox policy allowed model parameters to influence `require_sandbox`; server-enforced mandatory sandboxing needed for untrusted workspaces. | `backend/app/features/ai/sandbox/policy.py`, `backend/app/features/ai/chat_harness.py` | **OPEN** | Tracked for Phase 10+ hardening. |
| **AUD-012** | Desktop | High | Electron `captureService.ts` lacked session token requirement on `/capture`, used overly permissive CORS, and had potential SSRF surfaces. | `electron/services/captureService.ts` | **OPEN** | Tracked for Phase 10+ hardening. |
| **AUD-013** | Memory | Medium | Self-improving memory lacked automated ingestion hooks from failed test runs and rejected staging diffs, requiring manual lesson creation. | `backend/app/features/ai/memory/memory_service.py` | **OPEN** | Tracked for Phase 10+ hardening. |
| **AUD-014** | CI/Packaging | Medium | CI pipeline lacked mandatory security SAST / dependency auditing gates (`bandit`, `pip-audit`, `npm audit`) and release code signing verification. | `.github/workflows/ci.yml`, `electron-builder.yml` | **OPEN** | Tracked for Phase 10+ hardening. |

---

## Resolution Accounting

- **Total Findings:** 14
- **Closed Findings (7):** AUD-002, AUD-004, AUD-005, AUD-007, AUD-008, AUD-009, AUD-010
- **Open Findings (7):** AUD-001, AUD-003, AUD-006, AUD-011, AUD-012, AUD-013, AUD-014
- **Next Phase in Sequence:** Phase 10.2 (Batch 3 — Harness & Team Durability: AUD-001, AUD-003, AUD-006)

