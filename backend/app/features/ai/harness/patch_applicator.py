from __future__ import annotations

import difflib
import hashlib
import logging
import textwrap
from pathlib import Path
from typing import Any, List, Optional, Tuple, Dict

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.ai.schemas import FileChange
from .checkpoint_manager import _ensure_git_checkpoint, undo_turn_files
from .content_integrity import (
    validate_language_syntax,
    check_slice_syntax,
    check_projected_file_syntax,
)
from .symbol_index import invalidate_file
from .tool_executor import _clean_rel_path, _file_read_cache, _find_mismatch_context

logger = logging.getLogger(__name__)

# Minimum anchor thresholds for relocation fallback (Phase 12.5.1 G1)
MIN_ANCHOR_CHARS = 40
MIN_ANCHOR_LINES = 3


def _is_anchor_size_ok(anchor: str) -> tuple[bool, int, int]:
    """Validate that an anchor meets the minimum size requirements for relocation (Phase 12.5.1 G1).

    Guards relocation fallback against generic/short anchors (< 40 chars AND < 3 lines of normalized text).
    Exact line-range matches remain allowed even with short anchors.
    """
    if not anchor:
        return False, 0, 0
    import re
    dedented = textwrap.dedent(anchor).strip()
    normalized = re.sub(r"\s+", " ", dedented)
    nonblank_lines = [l for l in dedented.splitlines() if l.strip()]
    num_lines = len(nonblank_lines)
    char_count = len(normalized)
    is_ok = char_count >= MIN_ANCHOR_CHARS or num_lines >= MIN_ANCHOR_LINES
    return is_ok, char_count, num_lines


def _anchor_matches(slice_text: str, anchor: str) -> bool:
    """Verify if a candidate slice matches an anchor (verbatim, stripped, or sha256 hash)."""
    clean_a = anchor.replace("\r\n", "\n")
    clean_s = slice_text.replace("\r\n", "\n")
    if clean_s == clean_a or clean_s.strip() == clean_a.strip():
        return True

    # Check sha256 hash if anchor is a 64-character hex string
    if len(clean_a) == 64 and all(c in "0123456789abcdefABCDEF" for c in clean_a):
        h1 = hashlib.sha256(clean_s.encode("utf-8")).hexdigest()
        h2 = hashlib.sha256((clean_s + "\n").encode("utf-8")).hexdigest()
        h3 = hashlib.sha256(clean_s.strip().encode("utf-8")).hexdigest()
        if clean_a.lower() in (h1.lower(), h2.lower(), h3.lower()):
            return True

    return False


def _find_anchor_matches(text: str, lines: list[str], anchor: str) -> list[tuple[int, int]]:
    """Search for unique occurrence of anchor text in disk content.

    Returns list of (1-indexed start_line, 1-indexed end_line) matches.
    """
    clean_a = anchor.replace("\r\n", "\n")
    a_lines = clean_a.splitlines()
    if not a_lines:
        return []

    matches: list[tuple[int, int]] = []
    # 1. Verbatim line slice match
    for i in range(len(lines) - len(a_lines) + 1):
        if lines[i : i + len(a_lines)] == a_lines:
            matches.append((i + 1, i + len(a_lines)))

    # 2. If no verbatim match, try stripped line match (ignoring trailing/leading spaces)
    if not matches and any(l.strip() for l in a_lines):
        stripped_a = [l.strip() for l in a_lines]
        for i in range(len(lines) - len(a_lines) + 1):
            if [l.strip() for l in lines[i : i + len(a_lines)]] == stripped_a:
                matches.append((i + 1, i + len(a_lines)))

    # 3. If still no match and anchor is 64-hex sha256, test sliding windows
    if not matches and len(clean_a) == 64 and all(c in "0123456789abcdefABCDEF" for c in clean_a):
        w_len = len(a_lines)
        for i in range(len(lines) - w_len + 1):
            cand = "\n".join(lines[i : i + w_len])
            cand_h = hashlib.sha256(cand.encode("utf-8")).hexdigest()
            if cand_h.lower() == clean_a.lower():
                matches.append((i + 1, i + w_len))

    return matches


def _resolve_patch_anchor(
    current_text: str,
    disk_lines: list[str],
    start_line: int,
    actual_end: int,
    anchor: str,
    rel_p: str = "",
) -> tuple[bool, int, int, str | None, dict | None]:
    """Resolve an anchor against disk content (Phase 12.5 H1.2 + Phase 12.5.1 G1).

    Order of resolution:
    (a) try line range; if disk slice == anchor -> apply (short anchors allowed for exact match).
    (b) slice != anchor -> RELOCATE: search for anchor in file.
        (c) 0 matches -> reject 'anchor not found: file drifted'.
        (d) >1 matches -> reject 'anchor ambiguous'.
        (e) 1 match -> guard relocation against generic/short anchors (G1).
            If ok, relocate and return relocation_event.
    """
    total_lines = len(disk_lines)
    disk_range = "\n".join(disk_lines[start_line - 1 : actual_end]) if start_line <= total_lines else ""

    if start_line <= total_lines and _anchor_matches(disk_range, anchor):
        return True, start_line, actual_end, None, None

    # Slice != anchor -> RELOCATE: search for anchor in file
    matches = _find_anchor_matches(current_text, disk_lines, anchor)
    if len(matches) == 0:
        return False, start_line, actual_end, "anchor not found: file drifted", None
    elif len(matches) > 1:
        return False, start_line, actual_end, "anchor ambiguous", None
    else:
        # Exactly 1 match found elsewhere -> guard relocation against generic/short anchors (Phase 12.5.1 G1)
        is_ok, c_count, l_count = _is_anchor_size_ok(anchor)
        if not is_ok:
            return (
                False,
                start_line,
                actual_end,
                f"anchor_too_short: anchor too short for safe relocation (<{MIN_ANCHOR_CHARS} chars, <{MIN_ANCHOR_LINES} lines): risk of matching wrong site. Use read_range to obtain a longer anchor.",
                None,
            )
        new_start, new_end = matches[0]
        logger.info(
            "[EDIT_RELOCATED] path=%s old_lines=%d-%d new_lines=%d-%d",
            rel_p, start_line, actual_end, new_start, new_end
        )
        print(f"[EDIT_RELOCATED] path={rel_p} old_lines={start_line}-{actual_end} new_lines={new_start}-{new_end}")
        relocation_event = {
            "relocated": True,
            "old_range": [start_line, actual_end],
            "new_range": [new_start, new_end],
            "reason": "relocated",
            "reason_text": f"File drifted — edit relocated from lines {start_line}-{actual_end} to lines {new_start}-{new_end}",
        }
        return True, new_start, new_end, None, relocation_event


def _simulate_sequence_anchors(
    file_patches: list[dict],
    initial_text: str,
    resolved_ranges: list[tuple[int | None, int | None]],
    rel_p: str,
) -> tuple[bool, str | None]:
    """Simulate applying patches sequentially in memory to verify subsequent anchors (Phase 12.5.1 G4).

    Verifies subsequent patch anchors are neither destroyed nor made ambiguous.
    """
    sim_text = initial_text
    for k in range(len(file_patches) - 1):
        p_curr = file_patches[k]
        r_curr = resolved_ranges[k]

        # Record match count before for all subsequent anchored patches
        subsequent_anchors: list[tuple[int, str, int]] = []
        for j in range(k + 1, len(file_patches)):
            p_next = file_patches[j]
            anch_next = p_next.get("anchor")
            if anch_next:
                matches_before = len(_find_anchor_matches(sim_text, sim_text.splitlines(), anch_next))
                subsequent_anchors.append((j, anch_next, matches_before))

        # Simulate applying patch k on sim_text in-memory
        anch_curr = p_curr.get("anchor")
        if anch_curr:
            m_sim = _find_anchor_matches(sim_text, sim_text.splitlines(), anch_curr)
            if len(m_sim) == 1:
                r_curr = m_sim[0]

        upd = p_curr.get("updated", "")
        if r_curr[0] is not None and r_curr[1] is not None:
            s_k, e_k = r_curr
            curr_lines = sim_text.splitlines()
            new_lines = curr_lines[: s_k - 1] + upd.splitlines() + curr_lines[e_k:]
            sim_text = "\n".join(new_lines)
            if initial_text.endswith("\n"):
                sim_text += "\n"
        else:
            orig = p_curr.get("original", "").replace("\r\n", "\n")
            if orig in sim_text:
                sim_text = sim_text.replace(orig, upd, 1)

        # Verify subsequent patch anchors after simulated apply
        sim_lines = sim_text.splitlines()
        for j, anch_next, count_before in subsequent_anchors:
            count_after = len(_find_anchor_matches(sim_text, sim_lines, anch_next))
            if count_before == 1 and count_after > 1:
                return False, f"Pre-apply conflict scan rejected '{rel_p}': seq_anchor_ambiguous: subsequent patch would become ambiguous after earlier patch."
            if count_before == 1 and count_after == 0:
                return False, f"Pre-apply conflict scan rejected '{rel_p}': overlapping edits in one turn: split into sequential turns (seq_anchor_destroyed: subsequent patch anchor would be destroyed by earlier patch)."

    return True, None


def apply_atomic_patch_sequence(
    workspace: str,
    patches: list[dict | Any],
    turn_number: int = 1,
    staged_changes: list[FileChange] | None = None,
) -> tuple[bool, str, list[str]]:
    """Apply multiple sequential edit_file patches as ONE atomic unit.

    Routes through mutation_pipeline.apply_mutations (Phase 12.6 Part 3).
    Preserves exact return shape: (success: bool, message: str, paths: list[str]).
    """
    if not patches:
        return True, "No patches to apply", []

    from .mutation_pipeline import Mutation, MutationKind, apply_mutations

    # 1. Normalize patches into Mutation objects
    mutations: list[Mutation] = []
    touched_paths: list[str] = []
    normalized_patches: list[dict] = []

    for p in patches:
        start_line = None
        end_line = None
        anchor = None
        if isinstance(p, dict):
            raw_path = str(p.get("path") or "")
            orig = str(p.get("original") or "")
            upd = str(p.get("updated") or p.get("new_code") or p.get("content") or "")
            start_line = p.get("start_line")
            end_line = p.get("end_line")
            anchor = p.get("anchor")
        elif hasattr(p, "arguments") and isinstance(p.arguments, dict):
            raw_path = str(p.arguments.get("path") or "")
            orig = str(p.arguments.get("original") or "")
            upd = str(p.arguments.get("updated") or p.arguments.get("new_code") or p.arguments.get("content") or "")
            start_line = p.arguments.get("start_line")
            end_line = p.arguments.get("end_line")
            anchor = p.arguments.get("anchor")
        elif hasattr(p, "path"):
            raw_path = str(getattr(p, "path") or "")
            orig = str(getattr(p, "original", "") or "")
            upd = str(getattr(p, "updated", "") or getattr(p, "new_code", "") or "")
            start_line = getattr(p, "start_line", None)
            end_line = getattr(p, "end_line", None)
            anchor = getattr(p, "anchor", None)
        else:
            continue

        rel_p = _clean_rel_path(raw_path)
        if not rel_p:
            continue
        if rel_p not in touched_paths:
            touched_paths.append(rel_p)

        entry = {
            "path": rel_p,
            "original": orig,
            "updated": upd,
            "anchor": str(anchor) if anchor is not None else None,
        }
        if start_line is not None and end_line is not None:
            try:
                entry["start_line"] = int(start_line)
                entry["end_line"] = int(end_line)
            except (ValueError, TypeError):
                pass
        normalized_patches.append(entry)

        if entry.get("start_line") is not None and entry.get("end_line") is not None:
            mut = Mutation(
                kind=MutationKind.EDIT_RANGE,
                path=rel_p,
                start_line=entry["start_line"],
                end_line=entry["end_line"],
                anchor=entry.get("anchor"),
                original=orig,
                updated=upd,
            )
        elif not orig:
            mut = Mutation(
                kind=MutationKind.CREATE,
                path=rel_p,
                content=upd,
            )
        else:
            mut = Mutation(
                kind=MutationKind.EDIT_RANGE,
                path=rel_p,
                anchor=entry.get("anchor"),
                original=orig,
                updated=upd,
            )
        mutations.append(mut)

    if not normalized_patches:
        return False, "No valid patch payloads provided", []

    # Optional Git checkpoint if repo exists
    git_commit = ""
    try:
        _, git_commit, _ = _ensure_git_checkpoint(workspace, turn_number, touched_files=touched_paths)
    except Exception as git_err:
        logger.debug("Git checkpoint creation skipped: %s", git_err)

    # Pre-mutation texts for staged_changes sync
    initial_texts: dict[str, str] = {}
    if staged_changes is not None:
        for rel_p in touched_paths:
            try:
                full_p = ensure_within_workspace(workspace, rel_p)
                if full_p.is_file():
                    initial_texts[rel_p] = full_p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                else:
                    initial_texts[rel_p] = ""
            except Exception:
                initial_texts[rel_p] = ""

    res = apply_mutations(workspace, mutations, mode="AGENT")

    if not res.success:
        if git_commit:
            try:
                undo_turn_files(workspace, git_commit, touched_paths)
            except Exception:
                pass
        failure_msg = res.rejection.reason_text if res.rejection else "Patch sequence rejected."
        full_reason = f"{failure_msg} Entire patch sequence was rolled back to checkpoint."
        return False, full_reason, res.rolled_back_paths

    # Synchronize staged_changes if provided
    if staged_changes is not None:
        for rel_p in touched_paths:
            try:
                full_p = ensure_within_workspace(workspace, rel_p)
                final_upd = full_p.read_text(encoding="utf-8", errors="replace") if full_p.exists() else ""
            except Exception:
                final_upd = ""
            orig_before = initial_texts.get(rel_p, "")
            existing = next((c for c in staged_changes if c.path == rel_p), None)
            reloc_evt = next((evt for evt in res.relocation_events if evt.get("file_path") == rel_p or evt.get("relocated")), None)
            if existing:
                existing.updated = final_upd
                if reloc_evt:
                    existing.relocation_event = reloc_evt
            else:
                new_c = FileChange(path=rel_p, original=orig_before, updated=final_upd)
                if reloc_evt:
                    new_c.relocation_event = reloc_evt
                staged_changes.append(new_c)

    success_msg = f"✓ Successfully applied {len(normalized_patches)} patch(es) atomically across {len(touched_paths)} file(s)."
    return True, success_msg, res.applied_paths
