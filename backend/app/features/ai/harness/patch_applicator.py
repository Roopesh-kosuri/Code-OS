from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any, List, Optional, Tuple, Dict

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.ai.schemas import FileChange
from .checkpoint_manager import _ensure_git_checkpoint, undo_turn_files
from .content_integrity import validate_language_syntax
from .tool_executor import _clean_rel_path, _file_read_cache, _find_mismatch_context

logger = logging.getLogger(__name__)


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
        if isinstance(p, dict):
            raw_path = str(p.get("path") or "")
            orig = str(p.get("original") or "")
            upd = str(p.get("updated") or p.get("content") or "")
        elif hasattr(p, "arguments") and isinstance(p.arguments, dict):
            raw_path = str(p.arguments.get("path") or "")
            orig = str(p.arguments.get("original") or "")
            upd = str(p.arguments.get("updated") or p.arguments.get("content") or "")
        elif hasattr(p, "path"):
            raw_path = str(getattr(p, "path") or "")
            orig = str(getattr(p, "original", "") or "")
            upd = str(getattr(p, "updated", "") or "")
        else:
            continue

        rel_p = _clean_rel_path(raw_path)
        if not rel_p:
            continue
        if rel_p not in touched_paths:
            touched_paths.append(rel_p)
        normalized_patches.append({
            "path": rel_p,
            "original": orig,
            "updated": upd,
        })

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
                else:
                    full_p.parent.mkdir(parents=True, exist_ok=True)
                    full_p.write_bytes(snap_bytes)
                    restored.append(p_rel)
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

        if not clean_orig:
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
            syn_ok, syn_err = validate_language_syntax(rel_p, projected_content)
            if not syn_ok:
                return _rollback(
                    f"Patch {idx+1} rejected: edit introduces syntax error in '{rel_p}': {syn_err}.",
                    idx
                )

            try:
                full_p.write_text(projected_content, encoding="utf-8")
                _file_read_cache[str(full_p.resolve())] = (full_p.stat().st_mtime, projected_content)
            except Exception as w_err:
                return _rollback(f"Patch {idx+1} rejected: failed writing '{rel_p}': {w_err}.", idx)

    # 4. Synchronize staged_changes if provided
    if staged_changes is not None:
        for rel_p in touched_paths:
            full_p = ensure_within_workspace(workspace, rel_p)
            final_upd = full_p.read_text(encoding="utf-8", errors="replace") if full_p.exists() else ""
            orig_before = initial_texts.get(rel_p, "")
            existing = next((c for c in staged_changes if c.path == rel_p), None)
            if existing:
                existing.updated = final_upd
            else:
                staged_changes.append(FileChange(path=rel_p, original=orig_before, updated=final_upd))

    success_msg = f"✓ Successfully applied {len(normalized_patches)} patch(es) atomically across {len(touched_paths)} file(s)."
    return True, success_msg, touched_paths
