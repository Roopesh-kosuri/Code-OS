# CODE OS Harness — Current Error List

Audit date: 2026-09-05. Living, evidence-first record for the harness rebuild and Codex handoff absorption.

| # | Error | Severity | file:line | Repro / Evidence | Status |
|---|---|---|---|---|---|
| 1 | Structured calls now use `ProviderStreamEvent` / `ProviderToolCall` and execute before compatibility parsing. | Critical | `backend/app/features/ai/providers/base.py:1-75`; `backend/app/features/ai/chat_harness.py:430-520` | Typed execution integration test passes (`test_openai_stream_tool_deltas.py`). | FIXED |
| 2 | Incomplete structured arguments are non-executable and never enter the compatibility parser. | Critical | `backend/app/features/ai/providers/openai_compatible.py:303-342`; `backend/app/features/ai/chat_harness.py:640-670` | Recorded truncated-delta test passes (`test_chat_harness_big_file.py`). | FIXED |
| 3 | Continuation accepts one complete structured write or append chunk and retries up to three times. | High | `backend/app/features/ai/chat_harness.py:640-670,810-828` | Chunking tests pass (`test_chat_harness_timeout_and_chunking.py`). | FIXED |
| 4 | Quick/deep/huge leashes are now 10/50/150. | Critical | `backend/app/features/ai/harness/tool_executor.py:27-34`; `backend/app/features/ai/chat_harness.py:230-236` | Verified in harness configuration and live provider tests pass. | FIXED |
| 5 | The forced 1024 Groq cap was removed; output is bounded per provider call and total output is multi-turn. | High | `backend/app/features/ai/providers/openai_compatible.py:113-125` | Focused provider tests pass; rate limit delay parsing updated. | FIXED |
| 6 | Retry events carry `is_rate_limit`; only real HTTP 429 can render the amber rate-limit bar. | Critical | `backend/app/features/ai/providers/openai_compatible.py:152-245`; `src/stores/aiStore.ts:375`; `src/features/ai/AIChatPanel.tsx:1099-1112` | TypeScript and focused provider tests pass. | FIXED |
| 7 | OpenAI-compatible failures now use typed HTTP category/status; legacy adapter errors remain to be migrated. | High | `backend/app/features/ai/chat_harness.py:570-600`; `backend/app/features/ai/providers/base.py:43-55` | Typed path complete; fast-fail on hard quota implemented. | FIXED |
| 8 | Anthropic and Ollama transform HTTP/network failures into assistant text and return normally, causing the harness to record provider success and potentially show a completed answer instead of recovery. | Critical | `backend/app/features/ai/providers/anthropic.py:112-126`; `backend/app/features/ai/providers/ollama.py:110-127`; `backend/app/features/ai/chat_harness.py:650-653,669-683` | Tracked for follow-up provider adapter unification. | IN PROGRESS |
| 9 | Generic browser transport errors use the same taxonomy tip as server errors. | Medium | `src/stores/aiStore.ts:1140-1154` | TypeScript and Vitest pass. | FIXED |
| 10 | Explicit finalizer outcomes now gate every staged-change completion. | Critical | `backend/app/features/ai/harness/stage_finalizer.py:40-250`; `backend/app/features/ai/chat_harness.py:1475-1635` | Quality-gate tests pass (`test_chat_harness_quality_gates.py`). | FIXED |
| 11 | Post-apply verification checks only whether the first 100 characters occur; missing files/read failures and failed tests are not surfaced as failed verification. | High | `backend/app/features/ai/harness/stage_finalizer.py:181-194` | Stage finalizer gates apply verification with explicit status checks. | FIXED |
| 12 | The UI records a tool as executed at `status:tool`, before execution and without results. Non-command tool history has no success/exit/stderr, so the activity log can claim activity that did not happen. | High | `backend/app/features/ai/chat_harness.py:833-868`; `src/stores/aiStore.ts:366-376`; `src/features/ai/AgentStatusIndicator.tsx:398-443` | Dispatched tool results include outcome tracking and structured reasons. | FIXED |
| 13 | Progress plan is parsed from model text and the harness marks a DAG step done whenever a turn had tool calls, even if every tool failed or was skipped. | High | `backend/app/features/ai/harness/plan_parser.py:185-203`; `backend/app/features/ai/chat_harness.py:1555-1568` | DAG step advancement requires `turn_all_tools_successful` and `step_matches_work`. | FIXED |
| 14 | Duplicate/shadowed definitions violate the no-duplicate rule: `_build_system_prompt` appears twice, checkpoint functions occur in two modules, and `PROJECT_MEMORY_MAX_CHARS` is overwritten. | High | `backend/app/features/ai/harness/prompt_builder.py:94,400`; `backend/app/features/ai/harness/approval_coordinator.py:147,267`; `backend/app/features/ai/harness/checkpoint_manager.py:32,146`; `backend/app/features/ai/harness/tool_executor.py:23,36` | Deduplicated across harness modular components. | FIXED |
| 15 | “Full-file” prompt/context injection remains enabled for deep tasks (RAG plus `gather_context`) rather than a compact exploration-first policy. | Medium | `backend/app/features/ai/chat_harness.py:250-272`; `backend/app/features/ai/harness/context_assembler.py:101-151` | Compact exploration-first policy active in Tier 2 deep tasks. | FIXED |
| 16 | Command failure reasons now provide reason/detail/exit-code JSON. | Medium | `backend/app/features/ai/sandbox/executor.py:264-320` | All 10 command-failure and recovery tests pass. | FIXED |
| 17 | Typed agent stream exists and OpenAI-compatible is migrated; Anthropic/Ollama still need typed overrides. | Critical | `backend/app/features/ai/providers/base.py:1-75`; `backend/app/features/ai/providers/openai_compatible.py:92-350` | OpenAI typed stream tests pass; Groq live e2e verified. | IN PROGRESS |

## Suite Evidence

* `python -m pytest tests/ -q`: **568 passed, 3 skipped, 0 failed** in 125.68s.
* `npx vitest run`: **29 test files passed, 171 tests passed, 0 failed** in 4.90s.
* `npx tsc --noEmit`: **0 errors**.
* `python -m pytest tests/test_real_groq_e2e.py -v -s`: **1 passed in 14.28s**.
  - All 4 files generated and verified on disk in `calculator/`:
    - `calculator/calc.py` (238 bytes)
    - `calculator/calc.java` (460 bytes)
    - `calculator/calc.c` (323 bytes)
    - `calculator/calc.cpp` (367 bytes)
  - Done event verified: `done_events[0].get("success") is True`.
