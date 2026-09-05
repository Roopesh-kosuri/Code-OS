# ADR-001: Monolith Decomposition

## Status
Accepted | Date: 2026-08-27

## Context
The core agent orchestration file `chat_harness.py` grew organically to over 4,250 lines. It contained mixed responsibilities: tool execution, prompt building, loop detection, duo-escalation, git checkpoints, approval coordination, and result compaction. This violated the Single Responsibility Principle (SRP), caused merge conflicts, made targeted unit testing difficult, and hindered readability.

## Decision
Decompose `chat_harness.py` into a modular package `backend/app/features/ai/harness/` containing 9 focused submodules:
1. `tool_executor.py`: Safe command and tool invocation handlers with LRU disk read caching and idempotency checks.
2. `prompt_builder.py`: Multi-tier prompt assembly, architecture docs, and style guidelines injection.
3. `checkpoint_manager.py`: Git checkpoint commits, atomic staging, and per-turn undo file restorations.
4. `approval_coordinator.py`: Interactive user approval requests, SQLite persistence, and command trust tracking.
5. `duo_escalator.py`: Multi-tier model escalation (Tier 1 -> Tier 2 -> Tier 3) with dynamic failure escalation.
6. `compaction_manager.py`: Message history compaction, tool result summarization, and context window pruning.
7. `plan_parser.py`: Regex and semantic extraction of step-by-step checklist plans.
8. `stage_finalizer.py`: Quality gate evaluation, test pass validation, and security audit sign-offs.
9. `context_assembler.py`: Token budget estimation, memory retrieval, and symbol index lookups.

## Consequences
### Positive
- Reduced main harness orchestrator line count by over 66%.
- Each submodule is independently testable with dedicated mock fixtures.
- Clean dependency boundaries prevent circular imports.
- New agent tools and quality gates can be added without modifying the core execution loop.

### Negative
- Inter-module communication requires standardized interfaces and explicit dataclasses.

### Metrics
- Monolith size: 4,250 lines -> Submodules average <400 lines each.
- Full harness test execution time: improved from ~18s to ~5.2s via isolated unit test fixtures.
