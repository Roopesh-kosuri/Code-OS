"""Unified Mutation Pipeline for CODE OS (Phase 12.6).

Consolidates workspace mutations into a single disciplined 6-stage pipeline:
  S1 resolve     -> path safety, bounds, anchor resolution
  S2 preflight   -> multi-edit conflict scan, G4 sequence simulation
  S3 validate    -> layered syntax checks (G5 contract on projected file)
  S4 apply       -> atomic temp write per file + os.replace, CRLF/BOM preservation
  S5 invalidate  -> synchronous symbol_index & file cache invalidation
  S6 rollback    -> on any failure in S4/S5, exact byte restoration & cleanup

Modes:
- AGENT: Full 6-stage lifecycle for autonomous edits (agent tools, refactor, fix, staging, cicd, ghost text).
- USER_SAVE: Human manual save from Monaco (PUT /api/files/content).
  Deliberately skips syntax gate (S3) so a developer can save half-finished or
  syntactically broken code without being blocked by fail-closed compiler errors.
  Path-safety (S1), atomic write (S4), synchronous invalidation (S5), and rollback (S6)
  are still strictly enforced. Records syntax_status="skipped_user_save" and emits
  metric [SYNTAX_SKIPPED_USER_SAVE].
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from app.core.paths import ensure_within_workspace, normalize_workspace
from .content_integrity import (
    NON_CODE_EXTENSIONS,
    UNAVAILABLE_CHECKER_EXTENSIONS,
    _normalize_lang,
    check_projected_file_syntax,
    check_slice_syntax,
    syntax_check,
    validate_language_syntax,
)
from .patch_applicator import (
    MIN_ANCHOR_CHARS,
    MIN_ANCHOR_LINES,
    _anchor_matches,
    _find_anchor_matches,
    _is_anchor_size_ok,
    _resolve_patch_anchor,
    _simulate_sequence_anchors,
)
from .symbol_index import invalidate_file
from .tool_executor import _clean_rel_path, _file_read_cache, _find_mismatch_context

logger = logging.getLogger(__name__)

# ── Hooks ───────────────────────────────────────────────────────────────────

InvalidationHook = Callable[[str, list[str]], None]
_invalidation_hooks: dict[str, InvalidationHook] = {}


def register_invalidation_hook(hook: InvalidationHook, key: str | None = None) -> str:
    """Register a callback hook invoked synchronously after workspace mutations are applied.

    Hook signature: hook(workspace_root: str, applied_paths: list[str]) -> None
    Used by adapters (e.g. files/service.py directory_cache) to invalidate external caches.
    Idempotent across module re-imports: if key is omitted, uses f"{hook.__module__}.{hook.__qualname__}".
    """
    if key is None:
        mod = getattr(hook, "__module__", "")
        qual = getattr(hook, "__qualname__", getattr(hook, "__name__", str(id(hook))))
        key = f"{mod}.{qual}" if mod else qual
    _invalidation_hooks[key] = hook
    return key


def unregister_invalidation_hook(hook_or_key: InvalidationHook | str) -> None:
    """Remove a previously registered invalidation hook by key or callable."""
    if isinstance(hook_or_key, str):
        _invalidation_hooks.pop(hook_or_key, None)
    else:
        mod = getattr(hook_or_key, "__module__", "")
        qual = getattr(hook_or_key, "__qualname__", getattr(hook_or_key, "__name__", str(id(hook_or_key))))
        key = f"{mod}.{qual}" if mod else qual
        _invalidation_hooks.pop(key, None)
        keys_to_del = [k for k, v in _invalidation_hooks.items() if v == hook_or_key]
        for k in keys_to_del:
            _invalidation_hooks.pop(k, None)


# ── Types & Schemas ─────────────────────────────────────────────────────────

class MutationKind(str, Enum):
    EDIT_RANGE = "EDIT_RANGE"
    WRITE_FULL = "WRITE_FULL"
    CREATE = "CREATE"
    APPEND = "APPEND"


@dataclass
class Mutation:
    kind: MutationKind | str
    path: str
    updated: str = ""                 # For EDIT_RANGE
    start_line: Optional[int] = None  # For EDIT_RANGE (1-indexed)
    end_line: Optional[int] = None    # For EDIT_RANGE (1-indexed, inclusive)
    anchor: Optional[str] = None      # For EDIT_RANGE
    original: Optional[str] = None    # For EDIT_RANGE (line-only fallback verification)
    new_content: str = ""             # For WRITE_FULL
    content: str = ""                 # For CREATE, APPEND

    def __post_init__(self):
        if isinstance(self.kind, str):
            try:
                self.kind = MutationKind(self.kind.upper())
            except ValueError:
                pass
        if self.kind == MutationKind.WRITE_FULL and not self.new_content and self.content:
            self.new_content = self.content
        elif self.kind in (MutationKind.CREATE, MutationKind.APPEND) and not self.content and self.new_content:
            self.content = self.new_content


class RejectionDict(dict):
    """Rejection descriptor supporting both dict key access and property access."""

    def __init__(self, code: str, reason_text: str, stage: str):
        super().__init__(code=code, reason_text=reason_text, stage=stage)

    @property
    def code(self) -> str:
        return self["code"]

    @property
    def reason_text(self) -> str:
        return self["reason_text"]

    @property
    def stage(self) -> str:
        return self["stage"]


@dataclass
class MutationResult:
    success: bool
    applied_paths: list[str] = field(default_factory=list)
    rolled_back_paths: list[str] = field(default_factory=list)
    relocation_events: list[dict] = field(default_factory=list)
    rejection: Optional[RejectionDict] = None
    syntax_status: dict[str, str] = field(default_factory=dict)
    metrics: list[str] = field(default_factory=list)


@dataclass
class ResolvedMutation:
    mutation: Mutation
    rel_p: str
    full_p: Path
    resolved_start: Optional[int] = None
    resolved_end: Optional[int] = None
    relocation_event: Optional[dict] = None


# ── Stage 1: Resolve ────────────────────────────────────────────────────────

def stage_resolve(
    workspace_root: str | Path,
    mutations: list[Mutation],
    mode: str,
) -> tuple[bool, Optional[RejectionDict], list[ResolvedMutation], list[dict]]:
    """Stage 1: Resolve path containment, bounds, and content anchors.

    Returns (is_ok, rejection, resolved_mutations, relocation_events).
    Zero disk writes occur in this stage.
    """
    if mode not in ("AGENT", "USER_SAVE"):
        return (
            False,
            RejectionDict(
                code="invalid_mode",
                reason_text=f"Unknown or invalid mutation mode: '{mode}'. Allowed modes are 'AGENT' and 'USER_SAVE'.",
                stage="resolve",
            ),
            [],
            [],
        )

    try:
        ws_path = normalize_workspace(str(workspace_root))
    except Exception as ws_err:
        return (
            False,
            RejectionDict(
                code="path_outside_workspace",
                reason_text=f"Invalid workspace root: {ws_err}",
                stage="resolve",
            ),
            [],
            [],
        )

    resolved: list[ResolvedMutation] = []
    reloc_events: list[dict] = []

    for idx, mut in enumerate(mutations):
        # 1. Path safety verification via ensure_within_workspace
        target_str = str(mut.path or "")
        cand_p = Path(target_str) if Path(target_str).is_absolute() else (ws_path / target_str)

        # Check for symlink escape before or during resolution
        is_symlink = False
        try:
            curr = cand_p
            while curr != curr.parent:
                if curr.is_symlink():
                    is_symlink = True
                    break
                curr = curr.parent
        except Exception:
            pass

        try:
            full_p = ensure_within_workspace(str(workspace_root), target_str)
        except Exception as p_err:
            code = "symlink_escape" if is_symlink else "path_outside_workspace"
            detail = getattr(p_err, "detail", str(p_err))
            return (
                False,
                RejectionDict(
                    code=code,
                    reason_text=f"Path safety violation: {detail}",
                    stage="resolve",
                ),
                [],
                [],
            )

        # Normalize relative path
        try:
            rel_p = str(full_p.relative_to(ws_path)).replace("\\", "/")
        except ValueError:
            return (
                False,
                RejectionDict(
                    code="path_outside_workspace",
                    reason_text=f"Path '{target_str}' resolved outside workspace root.",
                    stage="resolve",
                ),
                [],
                [],
            )

        # 2. Check kind validity
        if mut.kind not in (
            MutationKind.EDIT_RANGE,
            MutationKind.WRITE_FULL,
            MutationKind.CREATE,
            MutationKind.APPEND,
        ):
            return (
                False,
                RejectionDict(
                    code="invalid_mutation_kind",
                    reason_text=f"Unsupported mutation kind '{mut.kind}'.",
                    stage="resolve",
                ),
                [],
                [],
            )

        # 3. Read initial disk content if exists
        disk_exists = full_p.is_file()
        if disk_exists:
            try:
                disk_bytes = full_p.read_bytes()
                # Check for unsupported encodings (UTF-16 BOM)
                if disk_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
                    return (
                        False,
                        RejectionDict(
                            code="unsupported_encoding",
                            reason_text=f"Unsupported encoding for '{rel_p}': UTF-16 files cannot be safely modified.",
                            stage="resolve",
                        ),
                        [],
                        [],
                    )
                # UTF-8 validation (strict)
                try:
                    b_decode = disk_bytes[3:] if disk_bytes.startswith(b"\xef\xbb\xbf") else disk_bytes
                    disk_text = b_decode.decode("utf-8")
                except UnicodeDecodeError as dec_err:
                    return (
                        False,
                        RejectionDict(
                            code="unsupported_encoding",
                            reason_text=f"Unsupported encoding for '{rel_p}': file contains non-UTF-8 bytes ({dec_err}).",
                            stage="resolve",
                        ),
                        [],
                        [],
                    )
                disk_text = disk_text.replace("\r\n", "\n")
                disk_lines = disk_text.splitlines()
                total_lines = len(disk_lines)
            except Exception as read_err:
                return (
                    False,
                    RejectionDict(
                        code="disk_read_error",
                        reason_text=f"Failed reading '{rel_p}': {read_err}",
                        stage="resolve",
                    ),
                    [],
                    [],
                )
        else:
            disk_text = None
            disk_lines = []
            total_lines = 0

        # 4. Per-kind resolve logic
        if mut.kind == MutationKind.CREATE:
            if disk_text is not None and disk_text.strip() != "":
                return (
                    False,
                    RejectionDict(
                        code="original_must_be_empty",
                        reason_text=f"original_must_be_empty: file '{rel_p}' already exists on disk. Use original snippet to edit.",
                        stage="resolve",
                    ),
                    [],
                    [],
                )
            resolved.append(ResolvedMutation(mutation=mut, rel_p=rel_p, full_p=full_p))

        elif mut.kind == MutationKind.APPEND:
            if not disk_exists:
                return (
                    False,
                    RejectionDict(
                        code="file_does_not_exist",
                        reason_text=f"file does not exist: '{rel_p}'.",
                        stage="resolve",
                    ),
                    [],
                    [],
                )
            resolved.append(ResolvedMutation(mutation=mut, rel_p=rel_p, full_p=full_p))

        elif mut.kind == MutationKind.WRITE_FULL:
            resolved.append(ResolvedMutation(mutation=mut, rel_p=rel_p, full_p=full_p))

        elif mut.kind == MutationKind.EDIT_RANGE:
            if not disk_exists:
                return (
                    False,
                    RejectionDict(
                        code="file_does_not_exist",
                        reason_text=f"file does not exist: '{rel_p}'.",
                        stage="resolve",
                    ),
                    [],
                    [],
                )

            clean_upd = (mut.updated or "").replace("\r\n", "\n")
            if not clean_upd.strip():
                return (
                    False,
                    RejectionDict(
                        code="updated_empty_or_equal",
                        reason_text=f"updated_empty_or_equal: 'updated' content cannot be empty for '{rel_p}'.",
                        stage="resolve",
                    ),
                    [],
                    [],
                )

            s_line = mut.start_line
            e_line = mut.end_line
            anchor = mut.anchor

            if s_line is not None and (s_line < 1 or s_line > total_lines) and not anchor:
                return (
                    False,
                    RejectionDict(
                        code="start_line_out_of_bounds",
                        reason_text=f"start_line ({s_line}) out of bounds (file has {total_lines} lines).",
                        stage="resolve",
                    ),
                    [],
                    [],
                )

            act_end = min(e_line, total_lines) if e_line is not None else total_lines
            disk_range = "\n".join(disk_lines[s_line - 1 : act_end]) if s_line is not None and s_line <= total_lines else ""

            reloc_evt = None
            if mode == "AGENT" and anchor:
                a_ok, a_s, a_e, a_err, reloc_evt = _resolve_patch_anchor(
                    disk_text or "", disk_lines, s_line or 1, act_end, anchor, rel_p
                )
                if not a_ok:
                    if "anchor_too_short" in (a_err or ""):
                        rej_code = "anchor_too_short"
                    elif "ambiguous" in (a_err or ""):
                        rej_code = "anchor_ambiguous"
                    else:
                        rej_code = "anchor_not_found"
                    return (
                        False,
                        RejectionDict(
                            code=rej_code,
                            reason_text=f"{a_err} for '{rel_p}'.",
                            stage="resolve",
                        ),
                        [],
                        [],
                    )
                if reloc_evt:
                    reloc_evt.setdefault("file_path", rel_p)
                    reloc_events.append(reloc_evt)
                resolved_s = a_s
                resolved_e = a_e
            elif not anchor and mut.original:
                clean_orig = mut.original.replace("\r\n", "\n")
                if s_line is not None:
                    if clean_orig.strip() != disk_range.strip() and clean_orig != disk_range:
                        diag = _find_mismatch_context(disk_range, clean_orig)
                        return (
                            False,
                            RejectionDict(
                                code="original_mismatches_disk",
                                reason_text=f"original_mismatches_disk for '{rel_p}'.\n{diag}.",
                                stage="resolve",
                            ),
                            [],
                            [],
                        )
                    resolved_s = s_line
                    resolved_e = act_end
                else:
                    # Snippet matching in disk_text when start_line is omitted
                    matched_slice = None
                    if disk_text and clean_orig in disk_text:
                        matched_slice = clean_orig
                    elif disk_text and clean_orig.strip() in disk_text:
                        matched_slice = clean_orig.strip()
                    elif disk_text:
                        orig_lines = [l.rstrip() for l in clean_orig.splitlines()]
                        curr_lines = [l.rstrip() for l in disk_text.splitlines()]
                        if orig_lines:
                            for i in range(len(curr_lines) - len(orig_lines) + 1):
                                if curr_lines[i : i + len(orig_lines)] == orig_lines:
                                    raw_split = disk_text.splitlines(keepends=True)
                                    matched_slice = "".join(raw_split[i : i + len(orig_lines)])
                                    break
                    if matched_slice is None:
                        diag = _find_mismatch_context(disk_text or "", clean_orig)
                        return (
                            False,
                            RejectionDict(
                                code="original_mismatches_disk",
                                reason_text=f"original_mismatches_disk for '{rel_p}'.\n{diag}.",
                                stage="resolve",
                            ),
                            [],
                            [],
                        )
                    char_idx = (disk_text or "").find(matched_slice)
                    s_calc = (disk_text or "")[:char_idx].count("\n") + 1
                    e_calc = s_calc + max(0, len(matched_slice.strip("\n").splitlines()) - 1)
                    resolved_s = s_calc
                    resolved_e = e_calc
            else:
                resolved_s = s_line
                resolved_e = act_end

            resolved.append(
                ResolvedMutation(
                    mutation=mut,
                    rel_p=rel_p,
                    full_p=full_p,
                    resolved_start=resolved_s,
                    resolved_end=resolved_e,
                    relocation_event=reloc_evt,
                )
            )

    return True, None, resolved, reloc_events


# ── Stage 2: Preflight (AGENT mode) ─────────────────────────────────────────

def stage_preflight(
    resolved_mutations: list[ResolvedMutation],
    initial_texts: dict[str, str],
) -> tuple[bool, Optional[RejectionDict]]:
    """Stage 2: Multi-edit conflict scan and G4 sequence simulation (Phase 12.5 H5.2 + Phase 12.5.1 G4).

    Runs only in AGENT mode. Zero disk writes occur in this stage.
    """
    # Group resolved mutations by file path
    by_file: dict[str, list[ResolvedMutation]] = {}
    for r in resolved_mutations:
        by_file.setdefault(r.rel_p, []).append(r)

    for rel_p, file_muts in by_file.items():
        if len(file_muts) <= 1:
            continue

        # 1. Reject if any subsequent patch (2nd+) is line-only (H5.3)
        for p_idx, r in enumerate(file_muts[1:], start=2):
            if r.mutation.kind == MutationKind.EDIT_RANGE:
                is_line_only = r.mutation.start_line is not None and not r.mutation.anchor
                if is_line_only:
                    return (
                        False,
                        RejectionDict(
                            code="multi_edit_requires_anchors",
                            reason_text=f"Multi-edit turn rejected: multi-edit turns require anchors (patch {p_idx} on '{rel_p}' is line-only).",
                            stage="preflight",
                        ),
                    )

        # 2. G4 sequence simulation across sequential edits (Phase 12.5.1 G4)
        init_text = initial_texts.get(rel_p, "")
        patch_dicts = []
        for r in file_muts:
            patch_dicts.append({
                "path": rel_p,
                "original": r.mutation.original or "",
                "updated": r.mutation.updated or r.mutation.content or r.mutation.new_content,
                "anchor": r.mutation.anchor,
                "start_line": r.resolved_start,
                "end_line": r.resolved_end,
            })
        seq_ranges = [(r.resolved_start, r.resolved_end) for r in file_muts]

        sim_ok, sim_err = _simulate_sequence_anchors(patch_dicts, init_text, seq_ranges, rel_p)
        if not sim_ok:
            if "seq_anchor_ambiguous" in (sim_err or ""):
                rej_code = "seq_anchor_ambiguous"
            elif "seq_anchor_destroyed" in (sim_err or ""):
                rej_code = "seq_anchor_destroyed"
            else:
                rej_code = "overlapping_edits"
            return (
                False,
                RejectionDict(
                    code=rej_code,
                    reason_text=sim_err or "Sequence simulation failed",
                    stage="preflight",
                ),
            )

        # 3. Overlapping edits / nesting scan (H5.2)
        valid_ranges: list[tuple[int, int]] = []
        for r in file_muts:
            if r.resolved_start is not None and r.resolved_end is not None:
                valid_ranges.append((r.resolved_start, r.resolved_end))

        for i in range(len(valid_ranges)):
            s1, e1 = valid_ranges[i]
            for j in range(i + 1, len(valid_ranges)):
                s2, e2 = valid_ranges[j]
                if max(s1, s2) <= min(e1, e2):
                    return (
                        False,
                        RejectionDict(
                            code="overlapping_edits",
                            reason_text=f"Pre-apply conflict scan rejected '{rel_p}': overlapping edits in one turn: split into sequential turns.",
                            stage="preflight",
                        ),
                    )

    return True, None


# ── Stage 3: Validate ───────────────────────────────────────────────────────

def stage_validate(
    resolved_mutations: list[ResolvedMutation],
    initial_texts: dict[str, str],
    mode: str,
) -> tuple[bool, Optional[RejectionDict], dict[str, str], dict[str, str], list[str]]:
    """Stage 3: Layered syntax checks on projected in-memory content (never disk).

    Enforces Phase 12.5.1 G5 5-branch fail-mode contract in AGENT mode.
    In USER_SAVE mode, syntax checks are deliberately SKIPPED to allow human saves.
    Returns (is_ok, rejection, projected_contents, syntax_status, metrics).
    """
    projected_contents: dict[str, str] = {}
    syntax_status: dict[str, str] = {}
    metrics: list[str] = []

    # 1. Compute in-memory projected content per file
    by_file: dict[str, list[ResolvedMutation]] = {}
    for r in resolved_mutations:
        by_file.setdefault(r.rel_p, []).append(r)

    for rel_p, file_muts in by_file.items():
        current_proj = initial_texts.get(rel_p, "")

        for r in file_muts:
            mut = r.mutation
            if mut.kind == MutationKind.CREATE:
                current_proj = mut.content
            elif mut.kind == MutationKind.WRITE_FULL:
                current_proj = mut.new_content
            elif mut.kind == MutationKind.APPEND:
                current_proj = current_proj + mut.content
            elif mut.kind == MutationKind.EDIT_RANGE:
                upd_clean = (mut.updated or "").replace("\r\n", "\n")
                if r.resolved_start is not None and r.resolved_end is not None:
                    lines = current_proj.splitlines()
                    s_idx = r.resolved_start - 1
                    e_idx = r.resolved_end
                    new_lines = lines[:s_idx] + upd_clean.splitlines() + lines[e_idx:]
                    current_proj = "\n".join(new_lines)
                    if initial_texts.get(rel_p, "").endswith("\n") or mut.updated.endswith("\n"):
                        current_proj += "\n"
                else:
                    current_proj = upd_clean

        projected_contents[rel_p] = current_proj

    # 2. Syntax validation
    if mode == "USER_SAVE":
        for rel_p in by_file.keys():
            syntax_status[rel_p] = "skipped_user_save"
            metrics.append("[SYNTAX_SKIPPED_USER_SAVE]")
            print(f"[SYNTAX_SKIPPED_USER_SAVE] path={rel_p}")
            logger.info("syntax: skipped_user_save for path=%s", rel_p)
        return True, None, projected_contents, syntax_status, metrics

    # AGENT mode: Layered checks + G5 5-branch contract
    for rel_p, file_muts in by_file.items():
        orig_text = initial_texts.get(rel_p, "")
        proj_text = projected_contents[rel_p]

        # Check Layer 1 for EDIT_RANGE mutations
        for r in file_muts:
            if r.mutation.kind == MutationKind.EDIT_RANGE:
                slice_ok, slice_err = check_slice_syntax(rel_p, r.mutation.updated)
                if not slice_ok:
                    return (
                        False,
                        RejectionDict(
                            code="slice_syntax_error",
                            reason_text=f"edit introduces slice syntax error in '{rel_p}': {slice_err}.",
                            stage="validate",
                        ),
                        {},
                        {},
                        [],
                    )

        # Check Layer 2 / projected content
        proj_ok, proj_err = check_projected_file_syntax(
            rel_p,
            proj_text,
            original_content=orig_text if orig_text else None,
        )

        if not proj_ok:
            return (
                False,
                RejectionDict(
                    code="projected_syntax_error",
                    reason_text=f"edit introduces syntax error in '{rel_p}': {proj_err}.",
                    stage="validate",
                ),
                {},
                {},
                [],
            )

        # Categorize syntax status and metrics according to G5 contract branches
        norm_l = _normalize_lang(rel_p)
        _, syn_detail = syntax_check(norm_l, proj_text, original_source=orig_text if orig_text else None)

        if norm_l in NON_CODE_EXTENSIONS:
            syntax_status[rel_p] = "checked"
            metrics.append("[SYNTAX_SKIPPED_NONCODE]")
        elif "syntax: unchecked" in syn_detail or norm_l in UNAVAILABLE_CHECKER_EXTENSIONS:
            syntax_status[rel_p] = "unchecked"
            metrics.append("[SYNTAX_SKIP]")
        elif "syntax: file already broken" in syn_detail:
            syntax_status[rel_p] = "preexisting_broken_not_worsened"
            metrics.append("[SYNTAX_PREEXISTING_BROKEN]")
        elif "syntax: internal error" in syn_detail:
            syntax_status[rel_p] = "unchecked"
            metrics.append("[SYNTAX_INTERNAL_ERROR]")
        else:
            syntax_status[rel_p] = "checked"

    return True, None, projected_contents, syntax_status, metrics


# ── Stage 4: Apply ──────────────────────────────────────────────────────────

def stage_apply(
    workspace_root: str | Path,
    projected_contents: dict[str, str],
    initial_snapshots: dict[str, bytes | None],
) -> tuple[bool, Optional[RejectionDict], list[str]]:
    """Stage 4: Atomic file writes with line ending and encoding preservation.

    Writes to temp file in parent directory then calls os.replace.
    Preserves CRLF if original had CRLF; preserves UTF-8 BOM if original had BOM.
    Returns (is_ok, rejection, applied_paths).
    """
    applied_paths: list[str] = []

    for rel_p, proj_text in projected_contents.items():
        try:
            full_p = ensure_within_workspace(str(workspace_root), rel_p)
            snap_bytes = initial_snapshots.get(rel_p)

            # Line ending style determination:
            # - New file: default to LF (\n)
            # - Existing file: preserve CRLF if dominant, otherwise LF (normalizes mixed endings to dominant)
            crlf_count = snap_bytes.count(b"\r\n") if snap_bytes is not None else 0
            bare_lf_count = (snap_bytes.count(b"\n") - crlf_count) if snap_bytes is not None else 0
            use_crlf = crlf_count > bare_lf_count

            clean_text = proj_text.replace("\r\n", "\n")
            if use_crlf:
                final_text = clean_text.replace("\n", "\r\n")
            else:
                final_text = clean_text

            # Preserve UTF-8 BOM if original had BOM
            has_bom = snap_bytes is not None and snap_bytes.startswith(b"\xef\xbb\xbf")
            encoded_bytes = final_text.encode("utf-8")
            if has_bom:
                encoded_bytes = b"\xef\xbb\xbf" + encoded_bytes

            # Atomic write via tempfile in the same parent directory
            parent_dir = full_p.parent
            parent_dir.mkdir(parents=True, exist_ok=True)

            temp_name = ""
            with tempfile.NamedTemporaryFile("wb", dir=str(parent_dir), delete=False) as tf:
                tf.write(encoded_bytes)
                tf.flush()
                temp_name = tf.name

            try:
                os.replace(temp_name, str(full_p))
            except Exception:
                if temp_name and os.path.exists(temp_name):
                    try:
                        os.remove(temp_name)
                    except OSError:
                        pass
                raise

            applied_paths.append(rel_p)

        except Exception as apply_err:
            logger.error("stage_apply error on '%s': %s", rel_p, apply_err)
            return (
                False,
                RejectionDict(
                    code="apply_failed",
                    reason_text=f"Failed writing '{rel_p}': {apply_err}",
                    stage="apply",
                ),
                applied_paths,
            )

    return True, None, applied_paths


# ── Stage 5: Invalidate ─────────────────────────────────────────────────────

def stage_invalidate(
    workspace_root: str | Path,
    applied_paths: list[str],
) -> tuple[bool, Optional[RejectionDict]]:
    """Stage 5: Synchronously invalidate symbol index, file cache, and directory cache hooks."""
    try:
        ws_str = str(workspace_root)
        for rel_p in applied_paths:
            full_p = ensure_within_workspace(ws_str, rel_p)
            invalidate_file(full_p)
            if full_p.is_file():
                _file_read_cache[str(full_p.resolve())] = (
                    full_p.stat().st_mtime,
                    full_p.read_text(encoding="utf-8", errors="replace"),
                )
            else:
                _file_read_cache.pop(str(full_p.resolve()), None)

        for hook in list(_invalidation_hooks.values()):
            try:
                hook(ws_str, applied_paths)
            except Exception as hook_err:
                logger.warning("invalidation hook error: %s", hook_err)

        return True, None
    except Exception as inv_err:
        logger.error("stage_invalidate failed: %s", inv_err)
        return (
            False,
            RejectionDict(
                code="invalidate_failed",
                reason_text=f"Invalidation failed: {inv_err}",
                stage="invalidate",
            ),
        )


# ── Stage 6: Rollback ───────────────────────────────────────────────────────

def stage_rollback(
    workspace_root: str | Path,
    snapshots: dict[str, bytes | None],
) -> tuple[bool, Optional[RejectionDict]]:
    """Stage 6: Restore disk to exact pre-mutation state on S4/S5 failure.

    Restores original bytes for modified files; unlinks newly created files;
    invalidates symbol index again.
    Surfaces failure loudly if restoration of any file fails.
    """
    ws_str = str(workspace_root)
    ws_path = normalize_workspace(ws_str)
    failed_files: list[tuple[str, str]] = []

    for rel_p, snap_bytes in snapshots.items():
        try:
            full_p = ensure_within_workspace(ws_str, rel_p)
            if snap_bytes is None:
                # File was created during this mutation cycle -> delete it
                if full_p.exists():
                    if full_p.is_file():
                        full_p.unlink()
                    parent = full_p.parent
                    while parent != ws_path and parent != ws_path.parent:
                        try:
                            parent.rmdir()
                            parent = parent.parent
                        except OSError:
                            break
                invalidate_file(full_p)
                _file_read_cache.pop(str(full_p.resolve()), None)
            else:
                # Restore exact pre-call bytes
                full_p.parent.mkdir(parents=True, exist_ok=True)
                full_p.write_bytes(snap_bytes)
                invalidate_file(full_p)
                _file_read_cache.pop(str(full_p.resolve()), None)
        except Exception as r_err:
            logger.error("Rollback failed restoring '%s': %s", rel_p, r_err)
            failed_files.append((rel_p, str(r_err)))

    if failed_files:
        return (
            False,
            RejectionDict(
                code="rollback_failed",
                reason_text=f"Rollback failed for files: {failed_files}",
                stage="rollback",
            ),
        )

    return True, None


# ── Public API Coordinator ──────────────────────────────────────────────────

def apply_mutations(
    workspace_root: str | Path,
    mutations: list[Mutation] | list[dict[str, Any]],
    *,
    mode: str = "AGENT",
) -> MutationResult:
    """Consolidated workspace mutation pipeline (Phase 12.6).

    Executes:
      1. S1 resolve (containment, bounds, anchor matching)
      2. S2 preflight (conflict checks, G4 simulation - AGENT mode)
      3. S3 validate (layered syntax check, G5 contract - AGENT mode; skipped in USER_SAVE)
      4. S4 apply (snapshot + atomic write with line-ending / BOM preservation)
      5. S5 invalidate (synchronous symbol index + cache invalidation)
      6. S6 rollback (on S4/S5 failure, restores disk bytes exactly to snapshot)
    """
    if not mutations:
        return MutationResult(success=True)

    # Normalize mutation objects
    typed_mutations: list[Mutation] = []
    for m in mutations:
        if isinstance(m, Mutation):
            typed_mutations.append(m)
        elif isinstance(m, dict):
            typed_mutations.append(
                Mutation(
                    kind=m.get("kind", ""),
                    path=m.get("path", ""),
                    updated=m.get("updated", "") or m.get("new_code", ""),
                    start_line=m.get("start_line"),
                    end_line=m.get("end_line"),
                    anchor=m.get("anchor"),
                    original=m.get("original"),
                    new_content=m.get("new_content", ""),
                    content=m.get("content", ""),
                )
            )

    # S1: Resolve
    s1_ok, s1_rej, resolved, reloc_events = stage_resolve(
        workspace_root, typed_mutations, mode=mode
    )
    if not s1_ok:
        return MutationResult(
            success=False,
            relocation_events=reloc_events,
            rejection=s1_rej,
        )

    # Snapshot initial texts & bytes
    touched_paths = list(dict.fromkeys(r.rel_p for r in resolved))
    initial_snapshots: dict[str, bytes | None] = {}
    initial_texts: dict[str, str] = {}

    for rel_p in touched_paths:
        full_p = ensure_within_workspace(str(workspace_root), rel_p)
        if full_p.is_file():
            b = full_p.read_bytes()
            initial_snapshots[rel_p] = b
            b_dec = b[3:] if b.startswith(b"\xef\xbb\xbf") else b
            initial_texts[rel_p] = b_dec.decode("utf-8", errors="replace").replace("\r\n", "\n")
        else:
            initial_snapshots[rel_p] = None
            initial_texts[rel_p] = ""

    # S2: Preflight (AGENT mode only)
    if mode == "AGENT":
        s2_ok, s2_rej = stage_preflight(resolved, initial_texts)
        if not s2_ok:
            return MutationResult(
                success=False,
                relocation_events=reloc_events,
                rejection=s2_rej,
            )

    # S3: Validate
    s3_ok, s3_rej, projected, syntax_status, metrics = stage_validate(
        resolved, initial_texts, mode=mode
    )
    if not s3_ok:
        return MutationResult(
            success=False,
            relocation_events=reloc_events,
            rejection=s3_rej,
            syntax_status=syntax_status,
            metrics=metrics,
        )

    # S4: Apply (atomic write)
    s4_ok, s4_rej, applied = stage_apply(workspace_root, projected, initial_snapshots)
    if not s4_ok:
        # Trigger rollback on apply failure
        rb_ok, rb_err = stage_rollback(workspace_root, initial_snapshots)
        rej_to_return = rb_err if not rb_ok else s4_rej
        rb_paths = [p for p, b in initial_snapshots.items() if b is not None]
        return MutationResult(
            success=False,
            rolled_back_paths=rb_paths,
            relocation_events=reloc_events,
            rejection=rej_to_return,
            syntax_status=syntax_status,
            metrics=metrics,
        )

    # S5: Invalidate
    s5_ok, s5_rej = stage_invalidate(workspace_root, applied)
    if not s5_ok:
        # Trigger rollback on invalidation failure
        rb_ok, rb_err = stage_rollback(workspace_root, initial_snapshots)
        rej_to_return = rb_err if not rb_ok else s5_rej
        rb_paths = [p for p, b in initial_snapshots.items() if b is not None]
        return MutationResult(
            success=False,
            rolled_back_paths=rb_paths,
            relocation_events=reloc_events,
            rejection=rej_to_return,
            syntax_status=syntax_status,
            metrics=metrics,
        )

    return MutationResult(
        success=True,
        applied_paths=applied,
        relocation_events=reloc_events,
        syntax_status=syntax_status,
        metrics=metrics,
    )
