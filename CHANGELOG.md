# Changelog

All notable changes to CODE OS are documented in this file.

## [5.0.0] - 2026-09-14

### Summary
CODE OS v5.0.0 is the first stable release with comprehensive audit
remediation, autonomous orchestration, and hardened reliability. This
release closes all 15 audit findings, implements the Marathon Autopilot
for multi-day autonomous execution, and bundles all runtimes for
fresh-laptop operation.

### Key Features
- **Tiered Execution**: 4-tier complexity classifier (Tier 0-3) with
  automatic escalation to 5-agent team for complex tasks
- **Marathon Autopilot**: Goal → DAG decomposition → autonomous execution
  with budget guards, state persistence, and Kanban dashboard
- **Bundled Runtimes**: Python 3.11 + Node 20 + Git + Tiktoken cache
  packaged in installer for zero-dependency operation
- **Authenticated SSE Transport**: Short-lived stream tokens for live
  updates in packaged app (Team/Marathon/Terminal)
- **Monaco Diff Viewer**: Side-by-side syntax-highlighted diffs on
  approval cards and checkpoints
- **Live Editor Refresh**: File watcher events auto-reload clean tabs;
  dirty-state conflict protection

### Audit Remediation (Phase 10)
All 15 audit findings closed with regression tests:
- AUD-001: Pre-approval filesystem mutation eliminated
- AUD-002: Transactional apply/rollback with SHA-256 verification
- AUD-003: Cross-turn contamination gate wired with conversation history
- AUD-004: Provider-true tokenization (tiktoken) with fail-closed governance
- AUD-005: Honest test tool results (failed tests stay failed)
- AUD-006: Exact escalation action-ID isolation
- AUD-007: RAG path containment (reject escapes)
- AUD-008: Marathon git isolation (path-scoped commits)
- AUD-009: Windows terminal lifecycle (bounded process-group termination)
- AUD-010: Authenticated SSE transport (scoped 60s stream tokens)
- AUD-011: Concurrent-send turn isolation (single-active-send queue)
- AUD-012: RAG queue bounded & coalesced
- AUD-013: Enhancer stale-response revision gate
- AUD-014: CI security gates (bandit + pip-audit + npm audit)
- AUD-016: Monaco line-spacing fix (CRLF/LF normalization)

### Bug Fixes
#### Security & Isolation
- [`c370362`] enforce rate limiter with configurable limits (M2)
- [`a94e53a`] pin validated IP in url_fetcher to prevent DNS rebinding (M6)
- [`699c529`] tighten CSP, remove unsafe-inline/eval (M4)
- [`b5a43e1`] enable sandbox in main BrowserWindow (M5)
- [`b3f3e12`] validate URL schemes in shell:openExternal (M8)
- [`eeb2e30`] mitigate TOCTOU symlink race with O_NOFOLLOW (L2)
- [`2fc8bd4`] use relative_to for path containment (L3)
- [`4ed3bad`] harden trusted command matching and ignore untrusted workspace rules (M1)
- [`1a71aa9`] enforce server-side sandbox policy with fail-closed strict mode (H4)
- [`bad9688`] sanitize environment and arguments in agentic terminal (H3)
- [`6321804`] authenticate capture service and block SSRF and local file leaks (H2)
- [`6255d52`] route run_test through command validation and approval pipeline (H1)

#### AI Orchestration & Turn Safety
- [`1577c26`] Phase 7.1 hotfix - gate escalation turn, kill [DONE] leak, breaker & integrity guards
- [`860c32d`] Phase 6.1 & 6.2 Hotfixes — conversational turn safety & proposal integrity gate
- [`8bf3a9a`] live session semantic RAG reconciliation, tier guard, and visibility
- [`1f08d93`] consult semantic RAG for tier 1 conceptual codebase questions and expose semantic_search tool
- [`489010d`] refine single-action and deep project creation heuristics in unified classifier
- [`060f621`] prevent tech names from becoming staging targets and route document reviews to read-only Tier 0
- [`5f3e261`] intercept and reject autonomous git mutations unless explicitly requested
- [`c5706ad`] neutralize ask_user clarification loops on document review and classify attachments cleanly
- [`91c500b`] enforce read-only status on attached reference documents to prevent unwanted edit proposals and update NIM fallback suggestions
- [`65a6a48`] add untrusted attachment sandbox boundary, inject preamble, and route team attachments through formatter (S10)
- [`abbc556`] implement payload governance, tool-call text suppression, tier toolset restriction, and 413 shrink-and-retry (S7, S8, S9)
- [`4df3d4d`] enforce ask_user hard cap, loop breaker, and substantive answer completion gate
- [`32ec706`] align NVIDIA NIM DeepSeek parameters with temperature=1.0, top_p=0.95, seed=42, and chat_template_kwargs
- [`ce33dca`] cap attached file prompts to stay within TPM limits and cache ingestion metadata
- [`45343a4`] restore moonshotai/kimi-k3 on NVIDIA NIM, add reasoning watchdog, and update catalog
- [`f436f66`] restrict rate limit classification to true 429s and update Groq failover to openai/gpt-oss-20b
- [`0cfa6f8`] resolve multi-root file upload resolution and persistent message chips

#### Prompt Enhancer & Classification
- [`f238c3a`] revision ID and abort gate for prompt enhancer (AUD-013)
- [`38696a6`] tune escalation classifier for full-stack multi-layer and high-loc complex algorithms
- [`bef55a2`] resolve prompt enhancer execution flow and failure UX
- [`73543ec`] complete phase 6.4b enhancer policy, breaker, conclude rule, startup sha log
- [`8118fb4`] resolve Windows subprocess execution and prompt enhancement stream handling
- [`0a2ddea`] resolve live prompt enhancer triggering and pronoun rescue (Phase 5.1)

#### Testing & Integrity Gates
- [`0d70f96`] wire live history into contamination integrity gate (AUD-003)
- [`95e55ab`] honest test tool results, breaker integration (AUD-005)
- [`9c98a04`] provider-true tokenization + UTF-8 byte fidelity (AUD-004)
- [`9285055`] transactional apply/rollback with hash verification (AUD-002)
- [`cc92b7b`] import _sse_escalation_recommendation to properly emit escalation gate events

#### CI/CD & Release Signing
- [`3ff3d40`] mandatory security gates and release signing verification (AUD-014)
- [`8ac5466`] handle headless DISPLAY KeyError in computer_controller and run pytest with xvfb-run
- [`809ebc2`] resolve PyAV and ffmpeg build failure on macOS and Linux runners
- [`9484701`] ensure clean instant exit on pytest session finish and daemonize watcher threads
- [`890ac7d`] resolve CI typecheck exclusions, Linux fpm dependency, and startup timing
- [`9c84df3`] add Python dependency installation and PyInstaller compilation step before electron-builder packaging
- [`2d6730d`] add build:vite and build:renderer scripts and disable CSC auto discovery for macOS packaging

#### Retrieval-Augmented Generation (RAG)
- [`f373f13`] bounded last-event-wins reindex queue with cancellation (AUD-012)
- [`a2a5ebe`] strict workspace path containment, reject escapes (AUD-007)
- [`697f38f`] resolve retrieval scope, ranking, and failure UX (Phase 4.3)

#### Editor & Monaco Normalization
- [`d6581f9`] resolve Monaco double line-spacing bug across CRLF/LF open/close cycles (AUD-016)

#### Packaging & Bundled Runtimes
- [`8d33e8d`] harden backend spawn, isolate environment, add preflight check, and scope CI to macOS

#### Assets & App Icon Transparency
- [`bec0837`] remove black square background from app icon via border flood fill and regenerate with alpha (Phase 10.8)

#### Chat & Concurrency Isolation
- [`914139d`] single-active-send queue isolates concurrent sends (AUD-011)

#### Escalation Handlers
- [`5976221`] exact action_id required for all resolution paths (AUD-006)

#### File Staging & Transactions
- [`df22d9c`] remove pre-approval mkdir during file staging (AUD-001)

#### Marathon Autopilot & Git Scoping
- [`dece572`] path-scoped git commits, no unrelated dirty files (AUD-008)

#### Terminal & Process Lifecycle
- [`0f1153d`] bounded Windows process-group termination (AUD-009)

#### Server-Sent Events & Streaming
- [`a469052`] authenticated stream transport for team/marathon/terminal (AUD-010)

#### Startup & Workspace Initialization
- [`ceeccfe`] ignore release artifacts in vector indexing and prevent event-loop starvation
- [`1fd6687`] resolve workspace init hang, port collisions, and orphan uvicorn workers

#### Startup & Cleanup
- [`07ae260`] prune temp test workspaces and limit startup rag reconciliation to active/recent workspaces

#### Async Execution & Safety
- [`696b4bf`] correct asyncio.wait result handling for all completion cases

#### Test Suite
- [`155fb00`] make auto_approver loop until task completion in test_phase4_coverage
- [`47721bf`] fix 2 remaining CI failures
- [`44013d4`] resolve 5 CI test failures

#### Dependencies
- [`17e5796`] remove obsolete safety 2.3.5 and pin faster-whisper==1.2.1 to resolve packaging dependency conflict

#### General Fixes
- [`6345521`] chat UI cleanup, Team Mode sidebar, NVIDIA NIM kimi-k3 support

#### Backend
- [`dcbbcaf`] track verify_service.py and restrict verify_*.py rule in .gitignore

#### Mac
- [`ee080ec`] configure Gatekeeper signing, notarization, entitlements, and release guards (Phase 10.5)

#### Safety,Integrity
- [`af5d4bc`] enforce conversational safety, explicit edit intent, and tool result robustness (Phase 6.1 & 6.2)

### Features
#### AI Orchestration & Turn Safety
- [`a764fe2`] replace keyword router with LLM-based classifier (claim reconciliation)
- [`9bda0a3`] make RAG truly semantic with embeddings + reranker (claim reconciliation)
- [`68e976f`] synchronize team orchestration, standup generator, and agent console with dynamic catalog
- [`87035c2`] integrate unified dynamic model catalog and smart router presets
- [`77e4730`] enhance harness resilience, update default models, and expand test suites
- [`3a58790`] adaptive effort routing, budgeted RAG, DAG plans, project memory, and hardening sweep

#### Editor & Monaco Normalization
- [`428ccce`] wire monaco diff viewer, live tab reconciliation, and language-aware verifier selection

#### Electron
- [`33405fc`] implement smooth boot experience with splash window and connection overlay

#### General Fixes
- [`a552b0f`] add Support & Resources section to Settings > About
- [`6c98523`] deep-dive remediation sprint — models, features, sidebar
- [`6def5b8`] CODE OS v4.0.0 — 17-feature release & master installer rebuild
- [`fcf913f`] Multi-Agent Team Mode (Phase B1-B6 complete)
- [`1db617c`] Phase 7 (browser automation) + Phase B1 (team orchestrator core)
- [`55321db`] add Linux AppImage build script
- [`116bbaf`] add Linux DEB and Tar.gz installer packaging and automated macOS DMG GitHub Actions workflow
- [`a613ee5`] complete Phase 1.5 codebase, multi-model resilience, frameless UI, and new icon packaging

#### Prompt Enhancer & Classification
- [`83f5f43`] implement prompt enhancement engine (Phase 5)

#### Marathon Autopilot & Git Scoping
- [`42f4099`] Phase 8.1 — Marathon Mode Tab inside Agent Console, SSE lifecycle cleanup, and sidebar deep-linking
- [`0e7bc3c`] Phase 8 — Marathon Autopilot autonomous DAG execution, state persistence, budget guard, and dashboard

#### Orchestration
- [`cfa4961`] phase 7 adaptive orchestration rony to 5-agent team

#### Packaging & Bundled Runtimes
- [`7289c4b`] bundle Python, Node, Git, and Tiktoken for fresh-laptop installs (Phase 10.9)

#### Phase6
- [`d6ee274`] inject Tier-1 operating protocol, BPE tokenizer, conv summarization

#### Release
- [`04e7698`] CODE OS v3.0.0 - Self-Contained Cross-Platform Release

#### Tools
- [`86ed487`] bulletproof tool manifests, add diagnostics, intent selection, budget governor, and rollback

### Security
- CI enforces SAST gates (bandit, pip-audit, npm audit)
- Release signing verification for macOS/Windows
- Workspace path containment on all file operations
- Sandbox policy for command execution

### Known Limitations
- macOS: unsigned builds show Gatekeeper "damaged" dialog; notarization
  pipeline configured but requires Apple Developer credentials
- Linux installers: not built in this release (Docker not available);
  build command provided in docs/release-process.md
- Small local models (<=13B) underperform on complex planning; HARD tier
  recommended for multi-file work

### Upgrade Notes
This is the first stable release. No migration required.
