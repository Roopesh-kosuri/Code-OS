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
import shutil
import tempfile
import uuid
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

DIR_SNAPSHOT_MAX_BYTES = 25 * 1024 * 1024  # 25 MB cap for in-memory directory byte snapshot
DIR_SNAPSHOT_MAX_FILES = 2000              # 2000 file cap for in-memory directory snapshot


class MutationKind(str, Enum):
    EDIT_RANGE = "EDIT_RANGE"
    WRITE_FULL = "WRITE_FULL"
    CREATE = "CREATE"
    APPEND = "APPEND"
    DELETE = "DELETE"
    RENAME_MOVE = "RENAME_MOVE"
    COPY = "COPY"
    MKDIR = "MKDIR"


@dataclass
class Mutation:
    kind: MutationKind | str
    path: str = ""
    updated: str = ""                 # For EDIT_RANGE
    start_line: Optional[int] = None  # For EDIT_RANGE (1-indexed)
    end_line: Optional[int] = None    # For EDIT_RANGE (1-indexed, inclusive)
    anchor: Optional[str] = None      # For EDIT_RANGE
    original: Optional[str] = None    # For EDIT_RANGE (line-only fallback verification)
    new_content: str = ""             # For WRITE_FULL
    content: str = ""                 # For CREATE, APPEND
    # Phase 12.6 Part 3b additions
    missing_ok: bool = False          # For DELETE (silently succeed if path absent)
    old_path: Optional[str] = None    # For RENAME_MOVE
    new_path: Optional[str] = None    # For RENAME_MOVE / COPY
    src_path: Optional[str] = None    # For COPY
    dst_path: Optional[str] = None    # For COPY
    overwrite: bool = False           # For RENAME_MOVE (allow replacing destination)
    raw_bytes: Optional[bytes] = None # For exact byte write (e.g. git checkpoint restore)

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

        # Normalize path aliases for 2-path operations
        if self.kind == MutationKind.RENAME_MOVE:
            if not self.path and self.old_path:
                self.path = self.old_path
            elif not self.old_path and self.path:
                self.old_path = self.path
            if not self.dst_path and self.new_path:
                self.dst_path = self.new_path
            elif not self.new_path and self.dst_path:
                self.new_path = self.dst_path
        elif self.kind == MutationKind.COPY:
            if not self.path and self.src_path:
                self.path = self.src_path
            elif not self.src_path and self.path:
                self.src_path = self.path
            if not self.dst_path and self.new_path:
                self.dst_path = self.new_path
            elif not self.new_path and self.dst_path:
                self.new_path = self.dst_path


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
    rel_p: str = ""
    full_p: Optional[Path] = None
    resolved_start: Optional[int] = None
    resolved_end: Optional[int] = None
    relocation_event: Optional[dict] = None
    rel_p_dst: Optional[str] = None
    full_p_dst: Optional[Path] = None


@dataclass
class DirSnapshot:
    """Snapshot of a deleted or overwritten directory for atomic rollback."""
    rel_p: str
    target_path: Path
    is_trash: bool
    files: dict[str, bytes] = field(default_factory=dict)   # rel_subpath -> bytes
    dirs: list[str] = field(default_factory=list)           # rel_subpath of dirs
    trash_root: Optional[Path] = None
    trash_item: Optional[Path] = None


@dataclass
class ApplyState:
    """Tracks disk state changes during S4 apply for precise rollback and trash cleanup."""
    applied_paths: list[str] = field(default_factory=list)
    file_snapshots: dict[str, bytes | None] = field(default_factory=dict)
    dir_snapshots: dict[str, DirSnapshot] = field(default_factory=dict)
    renamed_items: list[tuple[Path, Path, bool]] = field(default_factory=list)  # (src, dst, was_copy_fallback)
    created_copies: list[tuple[Path, bool]] = field(default_factory=list)       # (dst, is_dir)
    created_dirs: list[Path] = field(default_factory=list)
    symlink_snapshots: dict[str, tuple[str, bool]] = field(default_factory=dict) # rel_p -> (target, is_dir)
    active_trash_roots: list[Path] = field(default_factory=list)



# ── Stage 1: Resolve ────────────────────────────────────────────────────────

# ── Helpers for Stage 1 & Stage 4 ──────────────────────────────────────────

def _is_protected_path(full_p: Path, ws_path: Path, rel_p: str) -> bool:
    """Check if path targets workspace root, .git, or .code_os internals."""
    try:
        if full_p.resolve() == ws_path.resolve():
            return True
    except OSError:
        pass
    norm_rel = rel_p.replace("\\", "/").strip("/")
    if not norm_rel or norm_rel == ".":
        return True
    top_dir = norm_rel.split("/")[0].lower()
    if top_dir in (".git", ".code_os"):
        return True
    return False


def _scan_dir_stats(dir_path: Path) -> tuple[int, int]:
    """Calculate total bytes and file count under dir_path without following symlinks."""
    total_bytes = 0
    total_files = 0
    try:
        for root, dirs, files in os.walk(str(dir_path)):
            for f in files:
                fp = Path(root) / f
                total_files += 1
                try:
                    total_bytes += fp.lstat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total_bytes, total_files


def _resolve_and_check_path(
    ws_root_str: str,
    ws_path: Path,
    path_str: str,
) -> tuple[bool, Optional[RejectionDict], Optional[Path], str]:
    """Resolve path, enforce workspace boundary and symlink safety, and protect root/.git/.code_os."""
    cand_p = Path(path_str) if Path(path_str).is_absolute() else (ws_path / path_str)
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
        full_p = ensure_within_workspace(ws_root_str, path_str)
    except Exception as p_err:
        code = "symlink_escape" if is_symlink else "path_outside_workspace"
        detail = getattr(p_err, "detail", str(p_err))
        return False, RejectionDict(code=code, reason_text=f"Path safety violation: {detail}", stage="resolve"), None, ""

    try:
        rel_p = str(full_p.relative_to(ws_path)).replace("\\", "/")
    except ValueError:
        return False, RejectionDict(code="path_outside_workspace", reason_text=f"Path '{path_str}' resolved outside workspace root.", stage="resolve"), None, ""

    if _is_protected_path(full_p, ws_path, rel_p):
        return False, RejectionDict(
            code="protected_path",
            reason_text=f"Cannot operate on protected path '{rel_p}'. Workspace root, .git, and .code_os are protected.",
            stage="resolve",
        ), None, ""

    return True, None, full_p, rel_p


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
    if mode not in ("AGENT", "USER_SAVE", "FS_OP"):
        return (
            False,
            RejectionDict(
                code="invalid_mode",
                reason_text=f"Unknown or invalid mutation mode: '{mode}'. Allowed modes are 'AGENT', 'USER_SAVE', and 'FS_OP'.",
                stage="resolve",
            ),
            [],
            [],
        )

    try:
        ws_path = normalize_workspace(str(workspace_root))
        ws_root_str = str(workspace_root)
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
        # 1. Kind validity check
        if mut.kind not in (
            MutationKind.EDIT_RANGE,
            MutationKind.WRITE_FULL,
            MutationKind.CREATE,
            MutationKind.APPEND,
            MutationKind.DELETE,
            MutationKind.RENAME_MOVE,
            MutationKind.COPY,
            MutationKind.MKDIR,
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

        # 2. Two-path operations: RENAME_MOVE and COPY
        if mut.kind in (MutationKind.RENAME_MOVE, MutationKind.COPY):
            src_str = str(mut.old_path or mut.src_path or mut.path or "")
            dst_str = str(mut.new_path or mut.dst_path or "")

            ok_s, rej_s, src_p, src_rel = _resolve_and_check_path(ws_root_str, ws_path, src_str)
            if not ok_s:
                return False, rej_s, [], []

            ok_d, rej_d, dst_p, dst_rel = _resolve_and_check_path(ws_root_str, ws_path, dst_str)
            if not ok_d:
                return False, rej_d, [], []

            # Verify source exists
            if not (src_p.exists() or src_p.is_symlink()):
                return (
                    False,
                    RejectionDict(
                        code="path_not_found",
                        reason_text=f"Source path '{src_rel}' not found.",
                        stage="resolve",
                    ),
                    [],
                    [],
                )

            if mut.kind == MutationKind.RENAME_MOVE:
                if (dst_p.exists() or dst_p.is_symlink()) and not mut.overwrite:
                    return (
                        False,
                        RejectionDict(
                            code="destination_exists",
                            reason_text=f"Destination '{dst_rel}' already exists.",
                            stage="resolve",
                        ),
                        [],
                        [],
                    )
                if src_p.is_dir() and not src_p.is_symlink():
                    try:
                        if dst_p.resolve() == src_p.resolve() or dst_p.resolve().is_relative_to(src_p.resolve()):
                            return (
                                False,
                                RejectionDict(
                                    code="cannot_move_into_self",
                                    reason_text=f"Cannot move directory '{src_rel}' into itself or a subdirectory '{dst_rel}'.",
                                    stage="resolve",
                                ),
                                [],
                                [],
                            )
                    except (ValueError, OSError):
                        pass

                resolved.append(
                    ResolvedMutation(
                        mutation=mut,
                        rel_p=src_rel,
                        full_p=src_p,
                        rel_p_dst=dst_rel,
                        full_p_dst=dst_p,
                    )
                )
                continue

            elif mut.kind == MutationKind.COPY:
                if dst_p.exists() or dst_p.is_symlink():
                    return (
                        False,
                        RejectionDict(
                            code="destination_exists",
                            reason_text=f"Destination '{dst_rel}' already exists.",
                            stage="resolve",
                        ),
                        [],
                        [],
                    )
                if src_p.is_dir() and not src_p.is_symlink():
                    try:
                        if dst_p.resolve() == src_p.resolve() or dst_p.resolve().is_relative_to(src_p.resolve()):
                            return (
                                False,
                                RejectionDict(
                                    code="cannot_move_into_self",
                                    reason_text=f"Cannot copy directory '{src_rel}' into itself or a subdirectory '{dst_rel}'.",
                                    stage="resolve",
                                ),
                                [],
                                [],
                            )
                    except (ValueError, OSError):
                        pass

                resolved.append(
                    ResolvedMutation(
                        mutation=mut,
                        rel_p=src_rel,
                        full_p=src_p,
                        rel_p_dst=dst_rel,
                        full_p_dst=dst_p,
                    )
                )
                continue

        # 3. Single-path operations
        target_str = str(mut.path or "")
        ok_t, rej_t, full_p, rel_p = _resolve_and_check_path(ws_root_str, ws_path, target_str)
        if not ok_t:
            return False, rej_t, [], []

        if mut.kind == MutationKind.DELETE:
            if not (full_p.exists() or full_p.is_symlink()) and not mut.missing_ok:
                return (
                    False,
                    RejectionDict(
                        code="path_not_found",
                        reason_text=f"Path '{rel_p}' not found.",
                        stage="resolve",
                    ),
                    [],
                    [],
                )
            resolved.append(ResolvedMutation(mutation=mut, rel_p=rel_p, full_p=full_p))
            continue

        if mut.kind == MutationKind.MKDIR:
            if full_p.is_file() or full_p.is_symlink():
                return (
                    False,
                    RejectionDict(
                        code="destination_exists",
                        reason_text=f"Path '{rel_p}' already exists as a file.",
                        stage="resolve",
                    ),
                    [],
                    [],
                )
            resolved.append(ResolvedMutation(mutation=mut, rel_p=rel_p, full_p=full_p))
            continue

        # WRITE_FULL with raw_bytes skips text decoding checks
        if mut.kind == MutationKind.WRITE_FULL and mut.raw_bytes is not None:
            resolved.append(ResolvedMutation(mutation=mut, rel_p=rel_p, full_p=full_p))
            continue

        # 4. Text/code mutations: read initial disk content if exists
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

        # Per-kind resolve logic for text mutations
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
    """Stage 2: Multi-edit conflict scan and G4 sequence simulation (Phase 12.5 H5.2 + Phase 12.5.1 G4 + Phase 12.6 Part 3b).

    Enforces:
    - Zero batch conflicts (two mutations on same path, delete of parent dir, rename collisions).
    - Sequence simulation and anchor rules for multi-edit turns.
    Zero disk writes occur in this stage.
    """
    # 0. Global batch conflict scan across all mutations
    for idx, r in enumerate(resolved_mutations):
        paths_r = [r.rel_p]
        if r.rel_p_dst:
            paths_r.append(r.rel_p_dst)

        for other_idx in range(idx + 1, len(resolved_mutations)):
            r_other = resolved_mutations[other_idx]
            paths_other = [r_other.rel_p]
            if r_other.rel_p_dst:
                paths_other.append(r_other.rel_p_dst)

            # (a) Check if both mutations touch the exact same path
            common = set(paths_r) & set(paths_other)
            if common:
                # Exception: both mutations are EDIT_RANGE on the same file (handled by G4 sequence simulation)
                if not (r.mutation.kind == MutationKind.EDIT_RANGE and r_other.mutation.kind == MutationKind.EDIT_RANGE):
                    path_str = sorted(list(common))[0]
                    return (
                        False,
                        RejectionDict(
                            code="conflicting_mutations",
                            reason_text=f"Batch contains conflicting mutations on '{path_str}'.",
                            stage="preflight",
                        ),
                    )

            # (b) Check directory containment conflicts (delete of a directory containing another mutation's target)
            for p1 in paths_r:
                for p2 in paths_other:
                    if r.mutation.kind == MutationKind.DELETE and (p2 == p1 or p2.startswith(p1 + "/")):
                        return (
                            False,
                            RejectionDict(
                                code="conflicting_mutations",
                                reason_text=f"Batch contains conflicting mutations: delete of directory '{p1}' conflicts with mutation on '{p2}'.",
                                stage="preflight",
                            ),
                        )
                    if r_other.mutation.kind == MutationKind.DELETE and (p1 == p2 or p1.startswith(p2 + "/")):
                        return (
                            False,
                            RejectionDict(
                                code="conflicting_mutations",
                                reason_text=f"Batch contains conflicting mutations: delete of directory '{p2}' conflicts with mutation on '{p1}'.",
                                stage="preflight",
                            ),
                        )

            # (c) Move into self check
            if r.mutation.kind == MutationKind.RENAME_MOVE and r.rel_p_dst:
                if r.rel_p_dst == r.rel_p or r.rel_p_dst.startswith(r.rel_p + "/"):
                    return (
                        False,
                        RejectionDict(
                            code="cannot_move_into_self",
                            reason_text=f"Cannot move directory '{r.rel_p}' into itself or a subdirectory '{r.rel_p_dst}'.",
                            stage="preflight",
                        ),
                    )

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

    if mode == "FS_OP":
        for rel_p in by_file.keys():
            syntax_status[rel_p] = "skipped_fs_op"
            metrics.append("[SYNTAX_SKIPPED_FS_OP]")
            logger.info("syntax: skipped_fs_op for path=%s", rel_p)
        return True, None, projected_contents, syntax_status, metrics

    # AGENT mode: Layered checks + G5 5-branch contract
    for rel_p, file_muts in by_file.items():
        # If all mutations for this file are non-code/filesystem ops or have raw_bytes, skip syntax
        if all(
            r.mutation.kind in (MutationKind.DELETE, MutationKind.RENAME_MOVE, MutationKind.COPY, MutationKind.MKDIR)
            or r.mutation.raw_bytes is not None
            for r in file_muts
        ):
            syntax_status[rel_p] = "skipped_fs_op"
            metrics.append("[SYNTAX_SKIPPED_FS_OP]")
            continue

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
    resolved_mutations: Optional[list[ResolvedMutation]] = None,
) -> tuple[bool, Optional[RejectionDict], list[str], ApplyState]:
    """Stage 4: Atomic mutation application with line ending and encoding preservation.

    Handles:
    - Text mutations (WRITE_FULL, CREATE, APPEND, EDIT_RANGE) with atomic temp write + replace
    - DELETE: symlinks unlinked; files snapshotted & unlinked; directories under caps byte-snapshotted;
      directories over caps moved to .code_os/trash/<uuid>/
    - RENAME_MOVE: destination snapshotted if overwrite; os.replace with copy-delete cross-volume fallback
    - COPY: temp write / shutil.copy2 or copytree
    - MKDIR: mkdir(parents=True, exist_ok=True)
    Returns (is_ok, rejection, applied_paths, apply_state).
    """
    ws_str = str(workspace_root)
    ws_path = normalize_workspace(ws_str)
    apply_state = ApplyState(file_snapshots=dict(initial_snapshots))
    applied_paths: list[str] = []

    # If resolved_mutations is not supplied (e.g. direct test call to stage_apply),
    # fall back to applying projected_contents
    if resolved_mutations is None:
        for rel_p, proj_text in projected_contents.items():
            try:
                full_p = ensure_within_workspace(ws_str, rel_p)
                snap_bytes = initial_snapshots.get(rel_p)

                crlf_count = snap_bytes.count(b"\r\n") if snap_bytes is not None else 0
                bare_lf_count = (snap_bytes.count(b"\n") - crlf_count) if snap_bytes is not None else 0
                use_crlf = crlf_count > bare_lf_count

                clean_text = proj_text.replace("\r\n", "\n")
                final_text = clean_text.replace("\n", "\r\n") if use_crlf else clean_text

                has_bom = snap_bytes is not None and snap_bytes.startswith(b"\xef\xbb\xbf")
                encoded_bytes = (b"\xef\xbb\xbf" if has_bom else b"") + final_text.encode("utf-8")

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
                apply_state.applied_paths.append(rel_p)

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
                    apply_state,
                )
        return True, None, applied_paths, apply_state

    # Process each resolved mutation in sequence
    written_files: set[str] = set()

    for r in resolved_mutations:
        mut = r.mutation
        full_p = r.full_p
        rel_p = r.rel_p

        try:
            if mut.kind in (MutationKind.EDIT_RANGE, MutationKind.WRITE_FULL, MutationKind.CREATE, MutationKind.APPEND):
                if rel_p in written_files:
                    continue
                written_files.add(rel_p)

                assert full_p is not None
                snap_bytes = initial_snapshots.get(rel_p)

                if mut.raw_bytes is not None:
                    encoded_bytes = mut.raw_bytes
                else:
                    proj_text = projected_contents.get(rel_p, "")
                    crlf_count = snap_bytes.count(b"\r\n") if snap_bytes is not None else 0
                    bare_lf_count = (snap_bytes.count(b"\n") - crlf_count) if snap_bytes is not None else 0
                    use_crlf = crlf_count > bare_lf_count

                    clean_text = proj_text.replace("\r\n", "\n")
                    final_text = clean_text.replace("\n", "\r\n") if use_crlf else clean_text

                    has_bom = snap_bytes is not None and snap_bytes.startswith(b"\xef\xbb\xbf")
                    encoded_bytes = (b"\xef\xbb\xbf" if has_bom else b"") + final_text.encode("utf-8")

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
                apply_state.applied_paths.append(rel_p)

            elif mut.kind == MutationKind.DELETE:
                assert full_p is not None
                if not (full_p.exists() or full_p.is_symlink()):
                    if mut.missing_ok:
                        applied_paths.append(rel_p)
                        apply_state.applied_paths.append(rel_p)
                        continue
                    return (
                        False,
                        RejectionDict(
                            code="path_not_found",
                            reason_text=f"Path '{rel_p}' not found.",
                            stage="apply",
                        ),
                        applied_paths,
                        apply_state,
                    )

                if full_p.is_symlink():
                    link_target = os.readlink(str(full_p))
                    is_d = full_p.is_dir()
                    apply_state.symlink_snapshots[rel_p] = (link_target, is_d)
                    full_p.unlink()
                    applied_paths.append(rel_p)
                    apply_state.applied_paths.append(rel_p)

                elif full_p.is_file():
                    apply_state.file_snapshots[rel_p] = full_p.read_bytes()
                    full_p.unlink()
                    applied_paths.append(rel_p)
                    apply_state.applied_paths.append(rel_p)

                elif full_p.is_dir():
                    tot_bytes, tot_files = _scan_dir_stats(full_p)
                    if tot_bytes <= DIR_SNAPSHOT_MAX_BYTES and tot_files <= DIR_SNAPSHOT_MAX_FILES:
                        # In-memory byte snapshot
                        f_map: dict[str, bytes] = {}
                        d_list: list[str] = []
                        for root, dirs, files in os.walk(str(full_p)):
                            r_path = Path(root)
                            for d in dirs:
                                dp = r_path / d
                                d_list.append(str(dp.relative_to(full_p)).replace("\\", "/"))
                            for f in files:
                                fp = r_path / f
                                rel_sub = str(fp.relative_to(full_p)).replace("\\", "/")
                                try:
                                    f_map[rel_sub] = fp.read_bytes()
                                except OSError:
                                    pass
                        dir_snap = DirSnapshot(
                            rel_p=rel_p,
                            target_path=full_p,
                            is_trash=False,
                            files=f_map,
                            dirs=d_list,
                        )
                        apply_state.dir_snapshots[rel_p] = dir_snap
                        shutil.rmtree(str(full_p))
                        applied_paths.append(rel_p)
                        apply_state.applied_paths.append(rel_p)
                    else:
                        # Above cap: move to trash
                        trash_id = str(uuid.uuid4())
                        trash_root = ws_path / ".code_os" / "trash" / trash_id
                        trash_item = trash_root / full_p.name
                        trash_root.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.move(str(full_p), str(trash_item))
                        except Exception as move_err:
                            return (
                                False,
                                RejectionDict(
                                    code="trash_move_failed",
                                    reason_text=f"Failed moving directory to trash: {move_err}",
                                    stage="apply",
                                ),
                                applied_paths,
                                apply_state,
                            )
                        dir_snap = DirSnapshot(
                            rel_p=rel_p,
                            target_path=full_p,
                            is_trash=True,
                            trash_root=trash_root,
                            trash_item=trash_item,
                        )
                        apply_state.dir_snapshots[rel_p] = dir_snap
                        apply_state.active_trash_roots.append(trash_root)
                        applied_paths.append(rel_p)
                        apply_state.applied_paths.append(rel_p)

            elif mut.kind == MutationKind.RENAME_MOVE:
                assert full_p is not None and r.full_p_dst is not None and r.rel_p_dst is not None
                dst_p = r.full_p_dst
                dst_rel = r.rel_p_dst

                if dst_p.exists() or dst_p.is_symlink():
                    if dst_p.is_file():
                        apply_state.file_snapshots[dst_rel] = dst_p.read_bytes()
                    elif dst_p.is_dir():
                        tot_bytes, tot_files = _scan_dir_stats(dst_p)
                        if tot_bytes <= DIR_SNAPSHOT_MAX_BYTES and tot_files <= DIR_SNAPSHOT_MAX_FILES:
                            f_map = {}
                            d_list = []
                            for root, dirs, files in os.walk(str(dst_p)):
                                r_path = Path(root)
                                for d in dirs:
                                    d_list.append(str((r_path / d).relative_to(dst_p)).replace("\\", "/"))
                                for f in files:
                                    fp = r_path / f
                                    f_map[str(fp.relative_to(dst_p)).replace("\\", "/")] = fp.read_bytes()
                            dir_snap = DirSnapshot(rel_p=dst_rel, target_path=dst_p, is_trash=False, files=f_map, dirs=d_list)
                            apply_state.dir_snapshots[dst_rel] = dir_snap
                        else:
                            trash_id = str(uuid.uuid4())
                            trash_root = ws_path / ".code_os" / "trash" / trash_id
                            trash_item = trash_root / dst_p.name
                            trash_root.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(dst_p), str(trash_item))
                            dir_snap = DirSnapshot(rel_p=dst_rel, target_path=dst_p, is_trash=True, trash_root=trash_root, trash_item=trash_item)
                            apply_state.dir_snapshots[dst_rel] = dir_snap
                            apply_state.active_trash_roots.append(trash_root)

                dst_p.parent.mkdir(parents=True, exist_ok=True)
                was_copy_fallback = False
                try:
                    os.replace(str(full_p), str(dst_p))
                except OSError:
                    if full_p.is_file():
                        shutil.copy2(str(full_p), str(dst_p))
                        full_p.unlink()
                    else:
                        shutil.copytree(str(full_p), str(dst_p))
                        shutil.rmtree(str(full_p))
                    was_copy_fallback = True

                apply_state.renamed_items.append((full_p, dst_p, was_copy_fallback))
                applied_paths.extend([rel_p, dst_rel])
                apply_state.applied_paths.extend([rel_p, dst_rel])

            elif mut.kind == MutationKind.COPY:
                assert full_p is not None and r.full_p_dst is not None and r.rel_p_dst is not None
                dst_p = r.full_p_dst
                dst_rel = r.rel_p_dst
                dst_p.parent.mkdir(parents=True, exist_ok=True)

                if full_p.is_file():
                    temp_name = ""
                    with tempfile.NamedTemporaryFile("wb", dir=str(dst_p.parent), delete=False) as tf:
                        temp_name = tf.name
                    shutil.copy2(str(full_p), temp_name)
                    os.replace(temp_name, str(dst_p))
                    apply_state.created_copies.append((dst_p, False))
                else:
                    shutil.copytree(str(full_p), str(dst_p))
                    apply_state.created_copies.append((dst_p, True))

                applied_paths.append(dst_rel)
                apply_state.applied_paths.append(dst_rel)

            elif mut.kind == MutationKind.MKDIR:
                assert full_p is not None
                if not full_p.exists():
                    apply_state.created_dirs.append(full_p)
                full_p.mkdir(parents=True, exist_ok=True)
                applied_paths.append(rel_p)
                apply_state.applied_paths.append(rel_p)

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
                apply_state,
            )

    return True, None, applied_paths, apply_state


# ── Stage 5: Invalidate ─────────────────────────────────────────────────────

def stage_invalidate(
    workspace_root: str | Path,
    applied_paths: list[str],
) -> tuple[bool, Optional[RejectionDict]]:
    """Stage 5: Synchronously invalidate symbol index, file cache, and directory cache hooks."""
    try:
        ws_str = str(workspace_root)
        ws_path = normalize_workspace(ws_str)

        all_paths_to_invalidate: list[Path] = []
        for rel_p in applied_paths:
            try:
                full_p = ensure_within_workspace(ws_str, rel_p)
                all_paths_to_invalidate.append(full_p)
                if full_p.is_dir():
                    for root, _, files in os.walk(str(full_p)):
                        for f in files:
                            all_paths_to_invalidate.append(Path(root) / f)
            except Exception:
                cand = ws_path / rel_p
                all_paths_to_invalidate.append(cand)

        for p in all_paths_to_invalidate:
            invalidate_file(p)
            if p.is_file():
                try:
                    _file_read_cache[str(p.resolve())] = (
                        p.stat().st_mtime,
                        p.read_text(encoding="utf-8", errors="replace"),
                    )
                except OSError:
                    _file_read_cache.pop(str(p.resolve()), None)
            else:
                _file_read_cache.pop(str(p.resolve()), None)

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
    snapshots: dict[str, bytes | None] | ApplyState,
) -> tuple[bool, Optional[RejectionDict]]:
    """Stage 6: Restore disk to exact pre-mutation state on S4/S5 failure.

    Handles:
    - Restores byte snapshots for modified files; unlinks newly created files.
    - Reverts RENAME_MOVE, COPY, MKDIR, and DELETE operations.
    - Moves trash directories back or recreates from in-memory byte snapshots.
    - Invalidates symbol index and caches again.
    """
    ws_str = str(workspace_root)
    ws_path = normalize_workspace(ws_str)
    failed_files: list[tuple[str, str]] = []

    # If legacy dict is passed:
    if isinstance(snapshots, dict):
        for rel_p, snap_bytes in snapshots.items():
            try:
                full_p = ensure_within_workspace(ws_str, rel_p)
                if snap_bytes is None:
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

    # ApplyState rollback
    state = snapshots

    # 1. Remove created copies
    for dst_p, is_d in reversed(state.created_copies):
        try:
            if dst_p.exists():
                if is_d:
                    shutil.rmtree(str(dst_p), ignore_errors=True)
                else:
                    dst_p.unlink(missing_ok=True)
            invalidate_file(dst_p)
            _file_read_cache.pop(str(dst_p.resolve()), None)
        except Exception as err:
            failed_files.append((str(dst_p), str(err)))

    # 2. Reverse renames
    for src_p, dst_p, was_copy in reversed(state.renamed_items):
        try:
            if dst_p.exists():
                src_p.parent.mkdir(parents=True, exist_ok=True)
                if was_copy:
                    if dst_p.is_file():
                        shutil.copy2(str(dst_p), str(src_p))
                        dst_p.unlink(missing_ok=True)
                    else:
                        shutil.copytree(str(dst_p), str(src_p))
                        shutil.rmtree(str(dst_p), ignore_errors=True)
                else:
                    os.replace(str(dst_p), str(src_p))
            invalidate_file(src_p)
            invalidate_file(dst_p)
            _file_read_cache.pop(str(dst_p.resolve()), None)
        except Exception as err:
            failed_files.append((str(dst_p), str(err)))

    # 3. Restore directory snapshots (trash move back or in-memory byte recreation)
    for rel_p, dir_snap in state.dir_snapshots.items():
        try:
            if dir_snap.is_trash:
                if dir_snap.trash_item and dir_snap.trash_item.exists():
                    dir_snap.target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dir_snap.trash_item), str(dir_snap.target_path))
            else:
                dir_snap.target_path.mkdir(parents=True, exist_ok=True)
                for d in dir_snap.dirs:
                    (dir_snap.target_path / d).mkdir(parents=True, exist_ok=True)
                for rel_f, b in dir_snap.files.items():
                    fp = dir_snap.target_path / rel_f
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_bytes(b)
                    invalidate_file(fp)
            invalidate_file(dir_snap.target_path)
        except Exception as err:
            failed_files.append((rel_p, str(err)))

    # 4. Restore symlinks
    for rel_p, (target, is_d) in state.symlink_snapshots.items():
        try:
            p = ensure_within_workspace(ws_str, rel_p)
            if p.exists() or p.is_symlink():
                p.unlink(missing_ok=True)
            os.symlink(target, str(p), target_is_directory=is_d)
            invalidate_file(p)
        except Exception as err:
            failed_files.append((rel_p, str(err)))

    # 5. Restore file snapshots
    for rel_p, snap_bytes in state.file_snapshots.items():
        if rel_p in state.dir_snapshots:
            continue
        try:
            full_p = ensure_within_workspace(ws_str, rel_p)
            if snap_bytes is None:
                if full_p.exists() and full_p.is_file():
                    full_p.unlink(missing_ok=True)
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
                full_p.parent.mkdir(parents=True, exist_ok=True)
                full_p.write_bytes(snap_bytes)
                invalidate_file(full_p)
                _file_read_cache.pop(str(full_p.resolve()), None)
        except Exception as err:
            failed_files.append((rel_p, str(err)))

    # 6. Clean up created directories
    for d in reversed(state.created_dirs):
        try:
            if d.exists() and d.is_dir():
                d.rmdir()
        except OSError:
            pass

    if failed_files:
        return (
            False,
            RejectionDict(
                code="rollback_failed",
                reason_text=f"Rollback failed for items: {failed_files}",
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
      3. S3 validate (layered syntax check, G5 contract - AGENT mode; skipped in USER_SAVE / FS_OP)
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
                    missing_ok=m.get("missing_ok", False),
                    old_path=m.get("old_path"),
                    new_path=m.get("new_path"),
                    src_path=m.get("src_path"),
                    dst_path=m.get("dst_path"),
                    overwrite=m.get("overwrite", False),
                    raw_bytes=m.get("raw_bytes"),
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

    # Snapshot initial texts & bytes for text/code mutations
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

    # S2: Preflight (Batch conflict check across all modes; sequence simulation in AGENT mode)
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

    # S4: Apply (atomic write / FS operations)
    s4_ok, s4_rej, applied, apply_state = stage_apply(
        workspace_root, projected, initial_snapshots, resolved_mutations=resolved
    )
    if not s4_ok:
        # Trigger rollback on apply failure
        rb_ok, rb_err = stage_rollback(workspace_root, apply_state)
        rej_to_return = rb_err if not rb_ok else s4_rej
        rb_paths = list(dict.fromkeys(apply_state.applied_paths))
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
        rb_ok, rb_err = stage_rollback(workspace_root, apply_state)
        rej_to_return = rb_err if not rb_ok else s5_rej
        rb_paths = list(dict.fromkeys(apply_state.applied_paths))
        return MutationResult(
            success=False,
            rolled_back_paths=rb_paths,
            relocation_events=reloc_events,
            rejection=rej_to_return,
            syntax_status=syntax_status,
            metrics=metrics,
        )

    # Commit success: purge active trash directories best effort
    for trash_root in apply_state.active_trash_roots:
        try:
            if trash_root.exists():
                shutil.rmtree(str(trash_root), ignore_errors=True)
        except Exception as purge_err:
            logger.warning("Failed to purge trash entry '%s': %s", trash_root, purge_err)

    return MutationResult(
        success=True,
        applied_paths=applied,
        relocation_events=reloc_events,
        syntax_status=syntax_status,
        metrics=metrics,
    )

