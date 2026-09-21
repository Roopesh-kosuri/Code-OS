# CODE OS v5.0.0 — Changelog

## Phase 18: Critical Audit Fixes
- F-0001: Startup workspace purge no longer deletes legitimate workspaces
- F-0010: Marathon execute_task crash fixed
- F-0011: Terminal cmd.exe deadlock fixed
- F-0004: Duo escalator import corrected
- F-0005: Escalation route 404 fixed
- F-0006: PowerShell injection prevented
- F-0007: Voice shell injection prevented
- F-0008: Computer controller subprocess offloaded to thread pool
- F-0012: Role permission gate wired into orchestrator

## Phase 15: Benchmark Gym + Release Discipline
- Benchmark gym with 11 OSS tasks, auto-scorer (100/100 aggregate)
- CycloneDX SBOM generation (309 components cataloged)
- Signed release artifacts wired into CI
- Windows installer at 300MB (≤350MB target)

## Phase 14: Verification Matrix
- Per-turn async verification with baseline attribution
- Targeted bounded test runs (JUnit-based, return codes not trusted)
- Diff-scoped security scan with severity gating
- Completion claims deterministic and evidence-carrying

## Phase 13: Unified Mutation Pipeline
- Single write path for all agents (Rony/Team/Marathon/user)
- 6-stage pipeline: resolve → preflight → validate → apply → invalidate → rollback
- Static guard prevents future direct writes

## Phases 11-12: Surgical Tools + Repo-Map
- Surgical edit tools (find_function, go_to_definition, find_references, edit_range)
- Aider-style ranked repo-map + LSP-lite diagnostics
- Content-anchored edits with auto-relocation
- Unified syntax fail-mode contract

## Phase 10: Hardening & Launchers
- 10.17-EXT: Latency, console reliability, tier deepening
- 10.18: Backend crash-loop fixed, file explorer get-started UX
- 10.19: Proposal integrity, inline approval, truthful claims
- 10.20: Output-limit resilience, patch-style recovery
- 10.16: Launcher rebuild (slim runtime, mac-only CI, fast install)

## Phase 0-9: Foundation
- Tiered agent harness with bounded execution
- Authenticated SSE streaming
- Workspace trust + Restricted Mode
- Proposal approval coordinator
- Checkpoint/undo system

## Known Limitations (S3/S4 from audit)
- README still references v4.0.0 (fixed in v5.1.0)
- /commit slash command git diff broken (fixed in v5.1.0)
- Test files contain UTF-8 BOM (cosmetic, fixed in v5.1.0)
