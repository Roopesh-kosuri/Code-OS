# CODE OS — Phase 9 & 10 Remediation Fix Plan

**Document:** Remediation & Engineering Implementation Roadmap  
**Protocol:** Local git commits only, truth-first verification, full regression suite green before closing any item. Zero remote pushes.

---

## Batch Overview

```mermaid
graph TD
    B1["Batch 1 (Codex Patches)<br/>AUD-009, AUD-002, AUD-004, AUD-008, AUD-007, AUD-005<br/>[CLOSED]"] --> B2["Batch 2 (Phase 10.1)<br/>AUD-010: Authenticated SSE Transport<br/>[CLOSED - commit a469052]"]
    B2 --> B3["Batch 3 (Phase 10.2)<br/>AUD-001, AUD-006, AUD-011<br/>Pre-Approval Purity, Escalation Isolation, Concurrent-Send Isolation<br/>[CLOSED - commits df22d9c, 5976221, 914139d]"]
    B3 --> B4["Batch 4 (Phase 10.3)<br/>AUD-003, AUD-012, AUD-013<br/>Contamination Wiring, RAG Queue Bound, Enhancer Revision Gate<br/>[CLOSED - commits 0d70f96, f373f13, f238c3a]"]
    B4 --> B5["Batch 5 (Phase 10.4)<br/>AUD-014<br/>CI/Packaging & Security Gates<br/>[CLOSED - commit 3ff3d40]"]
    B5 --> B6["Batch 6 (Phase 10.6)<br/>AUD-016<br/>Monaco Double Line-Spacing Bug (Ship-Blocker)<br/>[CLOSED - commit d6581f9]"]
```

---

## Batch 1: Codex Core Hardening (COMPLETED)

All 6 patches integrated, verified with focused test suites, and committed locally:

1. **AUD-009 — Windows Terminal Lifecycle**:
   - Target: `backend/app/features/ai/terminal/agentic_terminal_service.py`, `backend/tests/test_agentic_terminal.py`
   - Scope: Bounded Windows process-group termination (`taskkill /T /F`).
   - Commit: `0f1153d` (`fix(terminal): bounded Windows process-group termination (AUD-009)`)
   - Status: **CLOSED**

2. **AUD-002 — Transactional Apply & Rollback**:
   - Target: `backend/app/features/ai/harness/checkpoint_manager.py`, `backend/app/features/ai/harness/stage_finalizer.py`, `backend/tests/test_proposal_integrity.py`
   - Scope: Pre-edit and post-apply SHA-256 hash verification, atomic undo.
   - Commit: `9285055` (`fix(harness): transactional apply/rollback with hash verification (AUD-002)`)
   - Status: **CLOSED**

3. **AUD-004 — Provider-True Tokenization & UTF-8 Fidelity**:
   - Target: `backend/app/features/ai/harness/payload_governor.py`, `backend/app/features/ai/harness/context_assembler.py`, `backend/app/features/ai/chat_harness.py`, `backend/app/features/ai/harness/sse_streamer.py`, `backend/tests/test_payload_governance.py`
   - Scope: Provider-true tokenizer integration via tiktoken; multi-byte UTF-8 boundary preservation in SSE streamer.
   - Commit: `9c98a04` (`fix(harness): provider-true tokenization + UTF-8 byte fidelity (AUD-004)`)
   - Status: **CLOSED**

4. **AUD-008 — Marathon Git Isolation**:
   - Target: `backend/app/features/ai/marathon/marathon_executor.py`, `backend/tests/test_marathon_autopilot.py`
   - Scope: Path-scoped git commits, preventing accidental staging of unrelated user files.
   - Commit: `dece572` (`fix(marathon): path-scoped git commits, no unrelated dirty files (AUD-008)`)
   - Status: **CLOSED**

5. **AUD-007 — RAG Path Containment**:
   - Target: `backend/app/features/ai/rag/rag_routes.py`, `backend/app/features/ai/rag/vector_index_service.py`, `backend/tests/test_semantic_rag.py`
   - Scope: Strict workspace path containment and normalization, blocking directory escapes.
   - Commit: `a2a5ebe` (`fix(rag): strict workspace path containment, reject escapes (AUD-007)`)
   - Status: **CLOSED**

6. **AUD-005 — Tool Result Truthfulness & Breakers**:
   - Target: `backend/app/features/ai/agents/agent_tools.py`, `backend/app/features/ai/harness/tool_executor.py`, `backend/app/features/ai/chat_harness.py`, `backend/tests/test_aud_005_verifier_results.py`
   - Scope: Honest structured test results returned to model; consecutive failure loop breaker integration.
   - Commit: `95e55ab` (`fix(harness): honest test tool results, breaker integration (AUD-005)`)
   - Status: **CLOSED**

---

## Batch 2: Real-Time Stream Transport & Auth (Phase 10.1)

- **AUD-010 — Authenticated SSE Transport**:
  - Target: `backend/app/main.py`, `backend/app/core/auth.py`, `src/lib/sse.ts`, `src/features/ai/console/teamStore.ts`, `src/features/marathon/marathonStore.ts`, `src/features/terminal/agenticTerminalStore.ts`
  - Scope:
    1. Single shared authenticated SSE client helper for frontend stores.
    2. Short-lived single-purpose stream token (`?token=`, TTL <= 60s) scoped strictly to the requested stream route.
    3. Backend `AuthMiddleware` accepts stream tokens ONLY on SSE routes, validates scope and expiration, and rejects missing/invalid/expired tokens with 401.
    4. Automatic reconnection with backoff on drop; unmount cleanup with zero duplicate listeners.
  - Regression Tests:
    - Backend: `test_sse_stream_authorized_via_token`, `test_sse_stream_rejects_missing_invalid_expired_token`
    - Frontend: `test_sse_helper_reconnects_and_cleans_up`, `test_no_eventsource_without_auth_in_stores`
  - Status: **CLOSED** (commit `a469052`: `fix(sse): authenticated stream transport for team/marathon/terminal (AUD-010)`)

---

## Batch 3: Pre-Approval Purity, Escalation Isolation, Concurrent-Send Isolation (Phase 10.2)

- **AUD-001 — Pre-Approval Filesystem Mutation**:
  - Target: `backend/app/features/ai/chat_harness.py`, `backend/tests/test_aud_001_006_011.py`
  - Scope: Removed `mkdir(parents=True)` from the staging path in `chat_harness.py`. Parent directories are now only created inside the approved `apply_proposal`/`write_file` transaction. On rejection or timeout, no directories are created.
  - Regression Tests: `test_nested_new_file_reject_leaves_no_directories`, `test_nested_new_file_timeout_leaves_no_directories`
  - Commit: `df22d9c` (`fix(staging): remove pre-approval mkdir during file staging (AUD-001)`)
  - Status: **CLOSED**

- **AUD-006 — Escalation Resolver Fuzzy Matching**:
  - Target: `backend/app/features/ai/harness/approval_coordinator.py`, `backend/app/features/ai/chat_harness_routes.py`, `backend/app/features/ai/team/team_routes.py`
  - Scope: `resolve_escalation` now requires an exact `action_id`. Workspace substring, task substring, and "most recent pending" fallbacks removed. The `/escalation-decision` endpoint returns 404 when `action_id` is missing or not found. The redundant `resolve_escalation` call in `team_routes.py` (which used no action_id) was removed.
  - Regression Tests: `test_escalation_resolution_requires_exact_action_id`, `test_concurrent_escalations_resolve_independently`, `test_stale_handoff_id_rejected`, `test_workspace_substring_fallback_removed`, `test_task_substring_fallback_removed`, `test_most_recent_pending_fallback_removed`
  - Commit: `5976221` (`fix(escalation): exact action_id required for all resolution paths (AUD-006)`)
  - Status: **CLOSED**

- **AUD-011 — Concurrent-Send Turn Isolation**:
  - Target: `src/stores/aiStore.ts`, `src/__tests__/aud_011_concurrent_sends.test.ts`
  - Scope: Single-active-send queue. When a second `sendMessage` arrives while streaming is active, the current run's `AbortController` is aborted and a tick is yielded before the new run starts. Each run captures its own `thisController` reference; the `finally` block only clears streaming state when `activeController === thisController` — a stale finalizer from an aborted run cannot clear a newer run's state.
  - Regression Tests: `test_concurrent_sends_isolated_content`, `test_stale_finalizer_cannot_clear_newer_run`
  - Commit: `914139d` (`fix(chat): single-active-send queue isolates concurrent sends (AUD-011)`)
  - Status: **CLOSED**

---

## Batch 4: Contamination Wiring, RAG Queue Bound, Enhancer Revision Gate (Phase 10.3)

- **AUD-003 — Proposal Integrity Contamination Gate Unwired**:
  - Target: `backend/app/features/ai/harness/content_integrity.py`, `backend/app/features/ai/harness/stage_finalizer.py`, `backend/app/features/ai/chat_harness.py`, `backend/tests/test_aud_003_012.py`
  - Scope: Bounded provenance-separated history snapshot (last N assistant messages and tool prose) passed from `chat_harness.py` through `stage_finalizer.py` into `validate_content_integrity`. The contamination detector strictly checks assistant prose while ignoring user instructions and standard code. Proposals containing copied prior assistant prose are blocked.
  - Regression Tests: `test_contamination_gate_blocks_copied_prose_in_live_flow`, `test_ordinary_source_repetition_not_blocked`, `test_check_cross_turn_contamination_provenance_filter`
  - Commit: `0d70f96` (`fix(harness): wire live history into contamination integrity gate (AUD-003)`)
  - Status: **CLOSED**

- **AUD-012 — Semantic RAG Reindex Queue Boundedness & Eviction**:
  - Target: `backend/app/features/ai/rag/vector_index_service.py`, `backend/app/features/ai/rag/__init__.py`, `backend/tests/test_aud_003_012.py`
  - Scope: Replaced unbounded `asyncio.Queue` with per-path coalesced dictionary (`_pending_reindex`) using last-event-wins semantics, bounded capacity (`MAX_REINDEX_QUEUE_SIZE = 1000` with oldest-event eviction), and lifecycle cancellation support (`cancel_rag_reindex`, `get_rag_reindex_queue_size`).
  - Regression Tests: `test_rag_queue_bounded_under_burst`, `test_rag_queue_lifecycle_cancellation`
  - Commit: `f373f13` (`fix(rag): bounded last-event-wins reindex queue with cancellation (AUD-012)`)
  - Status: **CLOSED**

- **AUD-013 — Prompt Enhancer Classification Race / Stale Response**:
  - Target: `src/stores/intelligenceStore.ts`, `src/__tests__/aud_013_enhancer_stale_response.test.ts`
  - Scope: Monotonically increasing revision sequence counter (`currentClassifyRevision`) and `AbortController` gate (`classifyAbortController`). In-flight classification requests are aborted on subsequent input changes, and late/out-of-order responses from superseded revisions are discarded before mutating state.
  - Regression Tests: `test_enhancer_stale_response_discarded`, `test_empty_input_cancels_and_discards_in_flight_classification`
  - Commit: `f238c3a` (`fix(intelligence): revision ID and abort gate for prompt enhancer (AUD-013)`)
  - Status: **CLOSED**

---

## Batch 5: Autonomous Feedback & Packaging Infrastructure (Phase 10.4)

- **AUD-014 — CI/CD Security Scanning & Release Signing**:
  - Target: `.github/workflows/ci.yml`, `electron-builder.yml`, `pyproject.toml`, `scripts/verify-release-signing.js`, `.security-exceptions.json`
  - Scope:
    1. Dedicated `security-gates` job added to `.github/workflows/ci.yml` running `bandit -r backend/ -c pyproject.toml -lll`, `pip-audit -r backend/requirements.txt`, `npm audit --audit-level=high`, and `safety check`, each in its own sub-step with `continue-on-error: false`.
    2. Bandit configured in `pyproject.toml` with `exclude_dirs = ["backend/tests", "backend/scratch", ...]` and `skips = ["B101"]`.
    3. Quarterly allowed-failures register `.security-exceptions.json` with schema validation and expiry verification (`scripts/verify_security_exceptions.py`).
    4. Code signing blocks in `electron-builder.yml` for Windows (`sign`, `CSC_LINK`, `CSC_KEY_PASSWORD`), macOS (`notarize: true`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`), and Linux (`afterSign`).
    5. Release signing verification script (`scripts/verify-release-signing.js`) enforcing valid signatures when signing environment variables are configured or in strict mode.
    6. Dedicated `release-signing-verification` job in CI triggered on tag/release events.
  - Regression Tests:
    - `test_bandit_config_exists_and_valid`
    - `test_pip_audit_config_excludes_tests`
    - `test_npm_audit_high_fails_ci`
    - `test_security_exceptions_file_schema`
    - `test_electron_builder_sign_blocks_present`
    - `test_release_signing_verification_script`
  - Commit: `3ff3d40` (`fix(ci): mandatory security gates and release signing verification (AUD-014)`)
  - Status: **CLOSED**

---

## Batch 6: Monaco Line-Spacing & EOL Handling (Phase 10.6)

- **AUD-016 — Monaco Editor Double Line-Spacing Bug (Ship-Blocker)**:
  - Target: `backend/app/features/files/service.py`, `backend/app/features/ai/ghost_text/ghost_text_service.py`, `backend/app/features/ai/staging/staging_review_service.py`, `backend/app/features/ai/refactoring/refactor_routes.py`, `backend/app/features/ai/refactoring/verify_service.py`, `src/features/editor/EditorWorkspace.tsx`, `src/stores/editorStore.ts`, `backend/tests/test_aud_016_monaco_eol.py`
  - Scope:
    1. Diagnosed root cause with live evidence: Windows text mode in `Path.write_text()` translates `\n` to `\r\n`. If incoming content contains `\r\n` (e.g. from LLM generation or copy-paste), Python writes `\r\r\n` to disk. Subsequent universal-newlines reads (`read_text()`) treat `\r` (bare) and `\r\n` as separate newlines, producing `\n\n` (blank line between every line of code).
    2. Implemented `_normalize_eol()` regex helper in `backend/app/features/files/service.py` to collapse `\r+\n` to `\n` and bare `\r` to `\n` before writing, ensuring single platform newlines on disk.
    3. Updated `read_file()` to read raw bytes and decode through `_normalize_eol()` to heal existing corrupted files on disk without splitting on double CRs.
    4. Normalized content in all AI code generation write paths (`ghost_text_service`, `staging_review_service`, `refactor_routes`, `verify_service`).
    5. Configured explicit `EndOfLineSequence.LF` on Monaco model mount in `EditorWorkspace.tsx`.
    6. Added defensive `normalizeEol` in `editorStore.ts` for `openFile`, `updateContent`, and `handleDiskFileChange`.
  - Regression Tests (26/26 passed):
    - `test_file_open_preserves_line_count`
    - `test_close_reopen_no_extra_lines`
    - `test_crlf_file_no_double_spacing`
    - `test_lf_file_no_double_spacing`
    - `test_mixed_eol_file_normalized_correctly`
    - `test_file_watcher_update_no_line_doubling`
    - `test_save_preserves_original_eol_style`
  - Commit: `d6581f9` (`fix(editor): resolve Monaco double line-spacing bug across CRLF/LF open/close cycles (AUD-016)`)
  - Status: **CLOSED**
