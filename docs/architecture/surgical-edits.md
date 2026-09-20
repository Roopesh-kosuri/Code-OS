# Surgical Edit Architecture (CODE OS v5.0.0 — Phase 12.5)

## Overview

The Surgical Edit Architecture provides a drift-proof, content-anchored, syntax-verified mechanism for applying code modifications in CODE OS. Rather than relying on fragile line numbers alone or rewriting entire files, agents inspect code ranges using `read_range`, stage changes anchored to exact original content via `edit_range`, and execute atomic, conflict-checked patches with automatic line relocation and immediate symbol index invalidation.

---

## Architecture Flow Diagram

```mermaid
flowchart TD
    subgraph Client [User & Client Interface]
        REQ[User Prompt] --> CLASSIFY[Tier Classifier]
        CLASSIFY --> MANIFEST[Tool Manifest Construction]
    end

    subgraph LLM_Turn [Model Turn Execution]
        MANIFEST --> LLM[Model Decides Actions]
        LLM -->|read_range| RR[read_range Tool: slice, sha256, mtime]
        RR -->|anchored context| LLM
        LLM -->|tool invocation| DISPATCH{Tool Allowed in Active Tier?}
    end

    subgraph Escalation [H4: Denied-Tool Deterministic Escalation - Phase 12.5.1 G3]
        DISPATCH -->|No: Log [TOOL_DENIED]| REEVAL{Context-Driven Re-eval\n_classify_task_effort\n(No tool name/args injected)}
        REEVAL -->|Tier >= 2| UPGRADE[Upgrade Tier mid-turn\nEmit tier_upgrade SSE\nRetry call ONCE]
        UPGRADE --> EXEC
        REEVAL -->|Tier < 2| ESC_CARD[Emit Escalation Approval Card\nPendingApproval: tier_upgrade]
        ESC_CARD -->|Approved| UPGRADE_USER[Upgrade Tier 2 mid-turn\nRetry call ONCE]
        UPGRADE_USER --> EXEC
        ESC_CARD -->|Declined / Timeout| HONEST_DENY[ToolResult: 'Tool denied in current tier: operation requires Tier 2 (Deep Task).'\nContinue Read-Only]
    end

    subgraph Staging [H1 / H2: Staging & Layered Syntax Verification]
        DISPATCH -->|Yes: edit_range with anchor| EXEC[Stage FileChange]
        EXEC --> L1{Layer 1:\ncheck_slice_syntax}
        L1 -->|Syntax Error| BLOCK_STAGE[Block Staging: slice invalid alone]
        L1 -->|Valid| L2{Layer 2:\ncheck_projected_file_syntax}
        L2 -->|Syntax Error| BLOCK_STAGE2[Block Staging: breaks outer file scope]
        L2 -->|Valid| STAGED[Changes Held in Staging]
    end

    subgraph PreApply [H5 & G4: Pre-Apply Conflict & Invalidation Scanning]
        STAGED --> APPROVAL[User Approval Card / Auto-Finalize]
        APPROVAL --> PRE_SCAN{Pre-Apply Conflict Scan}
        PRE_SCAN -->|Unanchored 2nd+ patch on file| REJ_MULTI[Reject: 'multi-edit turns require anchors']
        PRE_SCAN -->|Ranges Overlap/Nest: max s1,s2 <= min e1,e2| REJ_OVERLAP[Reject: 'overlapping edits in one turn: split into sequential turns']
        PRE_SCAN -->|Relocation anchor < 40 chars & < 3 lines| REJ_SHORT[Reject: 'anchor_too_short']
        PRE_SCAN -->|Mid-sequence simulation: anchor count 1 -> 0| REJ_DEST[Reject: 'seq_anchor_destroyed']
        PRE_SCAN -->|Mid-sequence simulation: anchor count 1 -> >1| REJ_AMB[Reject: 'seq_anchor_ambiguous']
        PRE_SCAN -->|All Invariants Pass| RESOLVE[Anchor Resolution Engine]
    end

    subgraph ApplyLoop [H1 / H6 / G1 / G2 / G5: Apply, Relocate & Invalidate]
        RESOLVE --> CHECK_LINE{Does line slice == anchor?}
        CHECK_LINE -->|Yes| APPLY_PATCH[Apply Replacement in-memory]
        CHECK_LINE -->|No| ANCHOR_SIZE{Anchor Size OK?\n>=40 chars OR >=3 lines}
        ANCHOR_SIZE -->|No| REJ_SHORT_APPLY[Rollback: 'anchor_too_short']
        ANCHOR_SIZE -->|Yes| RELOCATE{Search unique anchor in disk content}
        RELOCATE -->|1 match found| LOG_RELOC[Log [EDIT_RELOCATED]\nAttach relocation_event\nSurface Amber Banner in Approval Card]
        RELOCATE -->|0 matches found| REJ_DRIFT[Rollback: 'anchor not found: file drifted']
        RELOCATE -->|>1 matches found| REJ_AMBIG[Rollback: 'anchor ambiguous']
        
        LOG_RELOC --> APPLY_PATCH
        APPLY_PATCH --> POST_SYNTAX{G5: 5-Branch Syntax Contract}
        POST_SYNTAX -->|Newly broken code| ROLLBACK[Atomic Rollback to Pre-Turn Checkpoint]
        POST_SYNTAX -->|Pre-existing breakage not worsened| WRITE_DISK
        POST_SYNTAX -->|Non-code or unavailable checker| WRITE_DISK[Atomic Disk Write]
        
        WRITE_DISK --> SYNC_INV[Synchronous Invalidation:\ninvalidate_file path -> clear symbol index & repo-map]
        ROLLBACK --> ROLLBACK_INV[Synchronous Invalidation on Restored Files]
    end
```

---

## Core Components & Invariants

### 1. Drift-Proof Content Anchors (H1)
- **Anchor Representation**: `edit_range` accepts an optional `anchor` parameter containing the exact expected old text (or sha256 checksum) of the target slice.
- **Resolution Order**:
  1. **Line-range match**: If the disk slice at `[start_line - 1 : end_line]` matches the anchor (verbatim or trimmed), the patch applies at those bounds.
  2. **Auto-relocation**: If lines have shifted (e.g. earlier insertions in the same turn or external edits), the engine searches for the anchor within the file:
     - **Unique match (1)**: Calculates new `start_line` and `end_line`, logs `[EDIT_RELOCATED] path=<p> old_lines=<s1>-<e1> new_lines=<s2>-<e2>`, and applies at the relocated lines.
     - **No match (0)**: Rejects immediately with deterministic reason: `"anchor not found: file drifted"`.
     - **Ambiguous match (>1)**: Rejects immediately with deterministic reason: `"anchor ambiguous"`.
  3. **Unanchored edits**: Must match the disk slice precisely; any drift triggers immediate rejection.

### 2. Layered Syntax Verification (H2)
Verification occurs in two distinct layers before changes reach the disk:
1. **Slice-level check (`check_slice_syntax`)**:
   - Inspects the replacement snippet in isolation.
   - For Python snippets, applies `textwrap.dedent` if indentation alone causes a parse failure.
   - Rejects syntactically broken replacement fragments before file projection.
2. **Projected-file check (`check_projected_file_syntax`)**:
   - Inspects the full file with the replacement applied in memory.
   - Catches cross-boundary syntax breakage (e.g., mismatched enclosing block indents, unclosed class bodies, unbalanced braces).

### 3. Read Range Tool (`read_range`) (H3)
- **Role**: Allows agents to inspect exact bounds and retrieve cryptographic and content anchors before editing.
- **Output**: Returns JSON containing:
  - `slice`: Exact text lines.
  - `sha256`: SHA-256 hash of the extracted slice text.
  - `mtime`: File modification timestamp.
  - `start_line` / `end_line` / `line_count`.
- **System Prompt Guidance**: Agents are instructed:
  > *"Before edit_range, call read_range to obtain exact bounds and use its text as your anchor."*

### 4. Denied-Tool Deterministic Escalation (H4)
- **Active Tier Enforcement**: When an agent attempts to invoke a tool outside the active tier manifest (e.g., `edit_range` at Tier 1):
  - Emits warning log: `[TOOL_DENIED] tool=<name> tier=<n>`.
  - Triggers mid-turn tier re-evaluation with accumulated context (`user_query + tool_name + tool_args`).
  - If re-evaluation scores Tier 2+: upgrades tier mid-turn, expands `active_tools`, emits `tier_upgrade` SSE event, and retries the tool call once.
  - If re-evaluation stays Tier <2: generates an interactive escalation card (`PendingApproval` with `action_type="tier_upgrade"`).
    - **Approve**: Upgrades to Tier 2 and retries call.
    - **Decline / Timeout**: Returns honest `ToolResult` with `"Tool denied in current tier: operation requires Tier 2 (Deep Task)."` and execution continues read-only without stalling.

### 5. Multi-Edit Sequencing & Conflict Scanning (H5)
- **Pre-Apply Conflict Scan**:
  - Scans all range patches for a turn before touching any disk files.
  - **Anchor Requirement**: If a file has 2 or more edits in a single turn, the 2nd and subsequent edits MUST provide anchors. Otherwise rejected pre-apply: `"multi-edit turns require anchors"`.
  - **Overlap Detection**: Resolves all patches against current disk. If any two patches on the same file overlap or nest (`max(s1, s2) <= min(e1, e2)`):
    - Rejects sequence pre-apply with reason: `"overlapping edits in one turn: split into sequential turns"`.
    - Guarantees zero files on disk are touched.
- **Resequencing**:
  - Valid non-overlapping anchored edits execute sequentially.
  - Each edit updates disk state; subsequent edits auto-relocate based on anchor content even if preceding edits shifted line numbers.

### 6. Synchronous Symbol Index Invalidation (H6)
- File system watchers are asynchronous and subject to OS event lag.
- Surgical edits require immediate freshness for downstream tool calls (`find_function`, `find_references`, `build_repo_map`).
- **Synchronous Call**:
  - Every successful patch write calls `invalidate_file(path)` synchronously.
  - Every atomic rollback calls `invalidate_file(path)` synchronously for each restored/unlinked file.
  - Invalidates both AST/symbol cache and repo-map rank cache in the same call.

---

## Follow-up Hardening (Phase 12.5.1)

Phase 12.5.1 closes five critical architectural gaps across the Phase 12.5 surgical editing pipeline without rewriting or creating parallel paths:

### G1 — Minimum Anchor Size for Safe Relocation
- Generic, trivial anchors (e.g. `pass`, `return None`, `}`) risk finding erroneous matches elsewhere in a file when line drift occurs.
- **Rules**:
  - Constants: `MIN_ANCHOR_CHARS = 40`, `MIN_ANCHOR_LINES = 3`.
  - Dedented, stripped anchor text must have at least 40 characters or at least 3 non-blank lines.
  - If anchor matches exact on-disk line range, it applies immediately regardless of size (exact line match is trusted).
  - If line range does not match, relocation fallback validates anchor size. If too short, rejects with code `anchor_too_short`:
    `"anchor too short for safe relocation (<40 chars, <3 lines): risk of matching wrong site. Use read_range to obtain a longer anchor."`

### G2 — Relocation Surfaced in Approval Card & SSE
- Any edit that is relocated (lines shifted due to drift) attaches a structured `relocation_event`:
  `{ relocated: true, old_range: [start, end], new_range: [reloc_start, reloc_end], reason: "relocated", reason_text: "..." }`
- Propagated across backend `PendingApproval`, SSE `approval_request`, and frontend `InlineConsoleApprovalCard` + `DiffViewer`.
- **UI Elements**:
  - Prominent amber warning banner: `"⚠ File drifted — edit relocated from lines X-Y to lines A-B"`.
  - Non-auto-approving "Re-read and re-confirm" action calling `/api/ai/chat-agent/reread/{action_id}`: invalidates the old card, re-stages against current disk content with fresh bounds, and presents a new approval card.
  - Clear `"anchored"` vs `"line-only"` badge displayed in approval cards and proposal inspect views.

### G3 — Context-Driven H4 Re-Evaluation Contract
- Mid-turn tier re-evaluation in the denied-tool path must be strictly context-driven, never request-driven.
- **Contract Invariant**: Requesting a denied tool does not earn it.
- Denied tool name (`tc.name`) and arguments (`tc.arguments`) carry zero score weight and are excluded from classifier inputs.
- Re-evaluation invokes `_classify_task_effort` strictly over `(user_query, attached_paths, is_agent_mode, history_messages)`.
- If context naturally warrants Tier 2+, upgrade occurs mid-turn with one retry. Otherwise, an interactive escalation card or honest denial is issued.

### G4 — Mid-Sequence Anchor Invalidation Pre-Scan
- For turns containing multiple edits on the same file, earlier patches may invalidate later patches' anchors.
- Pre-apply scan (Step 2b) simulates applying patches sequentially in-memory before touching disk:
  - If a subsequent patch's anchor match count changes from 1 to 0: rejects turn pre-apply with `seq_anchor_destroyed` (`"subsequent patch anchor would be destroyed by earlier patch"`).
  - If a subsequent patch's anchor match count changes from 1 to >1: rejects turn pre-apply with `seq_anchor_ambiguous` (`"subsequent patch would become ambiguous after earlier patch"`).
  - Guarantees zero disk writes occur when any sequence conflict is detected.

### G5 — Explicit 5-Branch Syntax Check Fail-Mode Contract
Syntax verification across `syntax_check`, `check_slice_syntax`, and `check_projected_file_syntax` adheres to an explicit 5-branch contract:
1. **Recognized Code Ext + Available Checker + Newly Broken**: FAIL-CLOSED with precise diagnostic line error.
2. **Pre-Existing Breakage Rule**: If target file had syntax errors before the patch, the patch is allowed if it does not worsen or introduce new syntax errors. Logs INFO `"syntax: file already broken pre-patch, patch does not worsen"`.
3. **Recognized Code Ext + Checker Unavailable**: FAIL-OPEN with log INFO `"syntax_check_unavailable for <ext>, proceeding without"`, emits `[SYNTAX_SKIP] ext=<ext>`, reports `"syntax: unchecked"`.
4. **Non-Code Extensions (`.md`, `.txt`, `.yaml`, `.css`, etc.)**: FAIL-OPEN, emits `[SYNTAX_SKIPPED_NONCODE] ext=<ext>`.
5. **Internal Error / Checker Exception**: FAIL-OPEN, logs WARNING, emits `[SYNTAX_INTERNAL_ERROR] ext=<ext>`.
