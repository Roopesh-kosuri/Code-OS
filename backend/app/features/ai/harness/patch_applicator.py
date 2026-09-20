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
    
    Enforces Phase 10.20 Part E3:
    1. Checkpoints all touched paths prior to applying any patch.
    2. Re-reads on-disk bytes between patches so patch N's original matches
       the file as modified by patch N-1.
    3. Any mismatch in any patch rejects that patch, rolls back the entire unit
       to the pre-turn checkpoint, and returns an honest reason.
    4. If all patches succeed, leaves them committed on disk and synchronizes
       staged_changes if provided.
    """
    if not patches:
        return True, "No patches to apply", []

    ws_path = normalize_workspace(workspace)

    # 1. Normalize and identify all touched files
    touched_paths: list[str] = []
    normalized_patches: list[dict[str, str]] = []

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

    if not normalized_patches:
        return False, "No valid patch payloads provided", []

    # 2. Checkpoint: snapshot disk bytes for all touched files
    initial_snapshots: dict[str, bytes | None] = {}
    initial_texts: dict[str, str] = {}

    for rel_p in touched_paths:
        try:
            full_p = ensure_within_workspace(workspace, rel_p)
            if full_p.is_file():
                b = full_p.read_bytes()
                initial_snapshots[rel_p] = b
                initial_texts[rel_p] = b.decode("utf-8", errors="replace").replace("\r\n", "\n")
            else:
                initial_snapshots[rel_p] = None
                initial_texts[rel_p] = ""
        except Exception as snap_err:
            return False, f"Failed to inspect target file '{rel_p}': {snap_err}", []

    # Step 2b: PRE-APPLY CONFLICT SCAN (Phase 12.5 H5.2, H5.3)
    # Group patches by file path. If multiple patches touch the same file:
    # 1. Reject if any subsequent patch (2nd+) is line-only (no anchor): "multi-edit turns require anchors"
    # 2. Reject if any two patches' resolved ranges overlap or nest: "overlapping edits in one turn: split into sequential turns"
    for rel_p in touched_paths:
        file_patches = [p for p in normalized_patches if p["path"] == rel_p]
        if len(file_patches) > 1:
            # Check H5.3: second+ patch must be anchored if it is a line-range patch
            for p_idx, p in enumerate(file_patches[1:], start=2):
                is_line_only = (p.get("start_line") is not None and not p.get("anchor"))
                if is_line_only:
                    return False, f"Multi-edit turn rejected: multi-edit turns require anchors (patch {p_idx} on '{rel_p}' is line-only).", []

            # Check H5.2: pre-apply range conflict scan
            initial_text = initial_texts.get(rel_p, "")
            initial_lines = initial_text.splitlines()
            resolved_ranges: list[tuple[int | None, int | None]] = []
            for p in file_patches:
                s = p.get("start_line")
                e = p.get("end_line")
                anch = p.get("anchor")
                if s is None or e is None:
                    # Snippet patch with original
                    orig = p.get("original", "").replace("\r\n", "\n")
                    if orig and orig in initial_text:
                        char_idx = initial_text.find(orig)
                        s_line = initial_text[:char_idx].count("\n") + 1
                        e_line = s_line + max(0, orig.count("\n"))
                        resolved_ranges.append((s_line, e_line))
                    else:
                        resolved_ranges.append((None, None))
                    continue
                if anch:
                    act_e = min(e, len(initial_lines))
                    a_ok, a_s, a_e, a_err, _ = _resolve_patch_anchor(
                        initial_text, initial_lines, s, act_e, anch, rel_p
                    )
                    if not a_ok:
                        return False, f"Pre-apply conflict scan rejected '{rel_p}': {a_err}.", []
                    resolved_ranges.append((a_s, a_e))
                else:
                    resolved_ranges.append((s, min(e, len(initial_lines))))

            # G4: Mid-sequence anchor invalidation scan (Phase 12.5.1 G4)
            sim_ok, sim_err = _simulate_sequence_anchors(file_patches, initial_text, resolved_ranges, rel_p)
            if not sim_ok:
                return False, sim_err or "", []

            # Scan all pairs for overlap or nesting: max(s1, s2) <= min(e1, e2)
            valid_ranges = [r for r in resolved_ranges if r[0] is not None and r[1] is not None]
            for i in range(len(valid_ranges)):
                s1, e1 = valid_ranges[i]
                for j in range(i + 1, len(valid_ranges)):
                    s2, e2 = valid_ranges[j]
                    if max(s1, s2) <= min(e1, e2):
                        return False, f"Pre-apply conflict scan rejected '{rel_p}': overlapping edits in one turn: split into sequential turns.", []

    # Optional Git checkpoint if repo exists
    git_commit = ""
    try:
        _, git_commit, _ = _ensure_git_checkpoint(workspace, turn_number, touched_files=touched_paths)
    except Exception as git_err:
        logger.debug("Git checkpoint creation skipped: %s", git_err)

    def _rollback(failure_msg: str, failing_patch_index: int) -> tuple[bool, str, list[str]]:
        logger.warning(
            "patch_applicator: atomic rollback triggered at patch %d/%d: %s",
            failing_patch_index + 1, len(normalized_patches), failure_msg
        )
        restored: list[str] = []
        for p_rel, snap_bytes in initial_snapshots.items():
            try:
                full_p = ensure_within_workspace(workspace, p_rel)
                if snap_bytes is None:
                    if full_p.exists():
                        if full_p.is_file():
                            full_p.unlink()
                        # Cleanup empty parent dirs up to workspace root
                        parent = full_p.parent
                        while parent != ws_path and parent != ws_path.parent:
                            try:
                                parent.rmdir()
                                parent = parent.parent
                            except OSError:
                                break
                    invalidate_file(full_p)
                else:
                    full_p.parent.mkdir(parents=True, exist_ok=True)
                    full_p.write_bytes(snap_bytes)
                    restored.append(p_rel)
                    invalidate_file(full_p)
                # Invalidate file read cache
                _file_read_cache.pop(str(full_p.resolve()), None)
            except Exception as r_err:
                logger.error("Failed to restore %s during rollback: %s", p_rel, r_err)

        if git_commit:
            try:
                undo_turn_files(workspace, git_commit, touched_paths)
            except Exception:
                pass

        full_reason = f"{failure_msg} Entire patch sequence was rolled back to checkpoint."
        return False, full_reason, restored

    # 3. Sequentially apply patches with intermediate on-disk reads
    for idx, patch in enumerate(normalized_patches):
        rel_p = patch["path"]
        raw_orig = patch["original"]
        raw_upd = patch["updated"]
        clean_orig = raw_orig.replace("\r\n", "\n")
        clean_upd = raw_upd.replace("\r\n", "\n")

        try:
            full_p = ensure_within_workspace(workspace, rel_p)
        except Exception as path_err:
            return _rollback(f"Patch {idx+1} rejected: path error: {path_err}.", idx)

        # UPDATED must not be empty
        if not clean_upd.strip():
            return _rollback(
                f"Patch {idx+1} rejected: updated_empty_or_equal: 'updated' content cannot be empty for '{rel_p}'.",
                idx
            )
        if clean_orig and clean_orig.strip() == clean_upd.strip():
            return _rollback(
                f"Patch {idx+1} rejected: updated_empty_or_equal: 'updated' is identical to 'original' for '{rel_p}'.",
                idx
            )

        # Step E3.2: Re-read on-disk bytes between patches
        if full_p.exists() and full_p.is_file():
            try:
                current_bytes = full_p.read_bytes()
                current_text = current_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
            except Exception as r_err:
                return _rollback(f"Patch {idx+1} rejected: disk_read_error on '{rel_p}': {r_err}.", idx)
        else:
            current_text = None

        start_line = patch.get("start_line")
        end_line = patch.get("end_line")
        anchor = patch.get("anchor")

        if start_line is not None and end_line is not None:
            # Surgical range edit
            if current_text is None:
                return _rollback(
                    f"Patch {idx+1} rejected: file does not exist: '{rel_p}'.",
                    idx
                )
            disk_lines = current_text.splitlines()
            total_lines = len(disk_lines)
            if (start_line < 1 or start_line > total_lines) and not anchor:
                return _rollback(
                    f"Patch {idx+1} rejected: start_line ({start_line}) out of bounds (file has {total_lines} lines).",
                    idx
                )

            actual_end = min(end_line, total_lines)
            disk_range = "\n".join(disk_lines[start_line - 1 : actual_end]) if start_line <= total_lines else ""

            if anchor:
                # Content anchor resolution order (Phase 12.5 H1.2 + Phase 12.5.1 G1)
                a_ok, a_s, a_e, a_err, reloc_event = _resolve_patch_anchor(
                    current_text, disk_lines, start_line, actual_end, anchor, rel_p
                )
                if not a_ok:
                    return _rollback(f"Patch {idx+1} rejected: {a_err} for '{rel_p}'.", idx)
                if reloc_event:
                    patch["relocation_event"] = reloc_event
                start_line, actual_end = a_s, a_e
            else:
                # No anchor provided -> line-only behavior: validate slice against disk range
                if clean_orig and clean_orig.strip() != disk_range.strip() and clean_orig != disk_range:
                    diagnostic = _find_mismatch_context(disk_range, clean_orig)
                    return _rollback(
                        f"Patch {idx+1} rejected: original_mismatches_disk for '{rel_p}'.\n{diagnostic}.",
                        idx
                    )

            # Layered syntax checks (Phase 12.5 H2 + Phase 12.5.1 G5)
            # Layer 1: Check slice in isolation
            slice_ok, slice_err = check_slice_syntax(rel_p, clean_upd)
            if not slice_ok:
                return _rollback(
                    f"Patch {idx+1} rejected: edit introduces slice syntax error in '{rel_p}': {slice_err}.",
                    idx
                )

            # Layer 2: Check projected full file in memory with pre-existing breakage tolerance (G5)
            projected_lines = disk_lines[: start_line - 1] + clean_upd.splitlines() + disk_lines[actual_end:]
            projected_content = "\n".join(projected_lines)
            if current_text.endswith("\n"):
                projected_content += "\n"

            proj_ok, proj_err = check_projected_file_syntax(rel_p, projected_content, original_content=current_text)
            if not proj_ok:
                return _rollback(
                    f"Patch {idx+1} rejected: edit introduces syntax error in '{rel_p}': {proj_err}.",
                    idx
                )

            try:
                full_p.write_text(projected_content, encoding="utf-8")
                _file_read_cache[str(full_p.resolve())] = (full_p.stat().st_mtime, projected_content)
                invalidate_file(full_p)
            except Exception as w_err:
                return _rollback(f"Patch {idx+1} rejected: failed writing '{rel_p}': {w_err}.", idx)
        elif not clean_orig:
            # New file creation
            if current_text is not None and current_text.strip() != "":
                return _rollback(
                    f"Patch {idx+1} rejected: original_must_be_empty: file '{rel_p}' already exists on disk. Use original snippet to edit.",
                    idx
                )
            syn_ok, syn_err = validate_language_syntax(rel_p, clean_upd)
            if not syn_ok:
                return _rollback(
                    f"Patch {idx+1} rejected: syntax error in '{rel_p}': {syn_err}.",
                    idx
                )
            try:
                full_p.parent.mkdir(parents=True, exist_ok=True)
                full_p.write_text(clean_upd, encoding="utf-8")
                _file_read_cache[str(full_p.resolve())] = (full_p.stat().st_mtime, clean_upd)
                invalidate_file(full_p)
            except Exception as w_err:
                return _rollback(f"Patch {idx+1} rejected: failed writing '{rel_p}': {w_err}.", idx)
        else:
            # Existing file modification
            if current_text is None:
                return _rollback(
                    f"Patch {idx+1} rejected: file does not exist: '{rel_p}'. To create a new file, pass original=''.",
                    idx
                )

            # Match original snippet verbatim in current on-disk content
            matched_slice = None
            if clean_orig in current_text:
                matched_slice = clean_orig
            elif clean_orig.strip() in current_text:
                matched_slice = clean_orig.strip()
            else:
                # Contiguous line match ignoring trailing spaces
                orig_lines = [l.rstrip() for l in clean_orig.splitlines()]
                curr_lines = [l.rstrip() for l in current_text.splitlines()]
                if orig_lines:
                    for i in range(len(curr_lines) - len(orig_lines) + 1):
                        if curr_lines[i : i + len(orig_lines)] == orig_lines:
                            raw_split = current_text.splitlines(keepends=True)
                            matched_slice = "".join(raw_split[i : i + len(orig_lines)])
                            break

            if matched_slice is None:
                diagnostic = _find_mismatch_context(current_text, clean_orig)
                return _rollback(
                    f"Patch {idx+1} rejected: original_mismatches_disk for '{rel_p}'.\n{diagnostic}.",
                    idx
                )

            projected_content = current_text.replace(matched_slice, clean_upd, 1)
            syn_ok, syn_err = validate_language_syntax(rel_p, projected_content, original_content=current_text)
            if not syn_ok:
                return _rollback(
                    f"Patch {idx+1} rejected: edit introduces syntax error in '{rel_p}': {syn_err}.",
                    idx
                )

            try:
                full_p.write_text(projected_content, encoding="utf-8")
                _file_read_cache[str(full_p.resolve())] = (full_p.stat().st_mtime, projected_content)
                invalidate_file(full_p)
            except Exception as w_err:
                return _rollback(f"Patch {idx+1} rejected: failed writing '{rel_p}': {w_err}.", idx)

    # 4. Synchronize staged_changes if provided
    if staged_changes is not None:
        for rel_p in touched_paths:
            full_p = ensure_within_workspace(workspace, rel_p)
            final_upd = full_p.read_text(encoding="utf-8", errors="replace") if full_p.exists() else ""
            orig_before = initial_texts.get(rel_p, "")
            existing = next((c for c in staged_changes if c.path == rel_p), None)
            reloc_evt = next((p.get("relocation_event") for p in normalized_patches if p.get("path") == rel_p and p.get("relocation_event")), None)
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
    # F3: Release in-memory byte snapshots immediately after success — these can be large.
    initial_snapshots.clear()
    initial_texts.clear()
    return True, success_msg, touched_paths
