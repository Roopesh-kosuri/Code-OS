from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

from app.core.paths import ensure_within_workspace
from app.features.ai.schemas import EditProposalRequest, FileChange
from app.features.ai.service import (
    create_proposal as _svc_create_proposal,
    apply_proposal as _svc_apply_proposal,
    reject_proposal as _svc_reject_proposal,
)
from app.features.ai.indexing.code_intelligence import _scan_for_secrets, _update_architecture_doc
from .approval_coordinator import PendingApproval, _pending_approvals, _ensure_git_checkpoint
from .tool_executor import EDIT_APPROVAL_TIMEOUT_SECONDS
from .activity_logger import _append_activity_log
from .prompt_builder import _evaluate_edit_critique, _discover_and_run_test_snapshot
from .compaction_manager import _generate_diff_summary
from .sse_streamer import (
    _sse_status, _sse_proposal, _sse_approval_request, _sse_command_result,
    _sse_checkpoint, _sse_done, _sse_error, _sse_event
)

logger = logging.getLogger(__name__)

def _get_create_proposal():
    try:
        from app.features.ai import chat_harness
        return getattr(chat_harness, 'create_proposal', _svc_create_proposal)
    except Exception:
        return _svc_create_proposal

def _get_apply_proposal():
    try:
        from app.features.ai import chat_harness
        if hasattr(chat_harness, 'apply_proposal'):
            return getattr(chat_harness, 'apply_proposal')
    except Exception:
        pass
    return _svc_apply_proposal

def _get_reject_proposal():
    try:
        from app.features.ai import chat_harness
        if hasattr(chat_harness, 'reject_proposal'):
            return getattr(chat_harness, 'reject_proposal')
    except Exception:
        pass
    return _svc_reject_proposal

def _get_edit_approval_timeout() -> float:
    try:
        from app.features.ai import chat_harness
        return getattr(chat_harness, 'EDIT_APPROVAL_TIMEOUT_SECONDS', 300.0)
    except Exception:
        return 300.0

async def _finalize_staged_changes(
    staged_changes: list[FileChange],
    workspace: str,
    tier: int = 1,
    turn_number: int = 1,
    user_query: str = "",
) -> AsyncIterator[str]:
    """Convert staged file changes into an edit proposal, run self-critique (Tier 2), and verify on disk after approval."""
    if not staged_changes:
        return
    
    try:
        # Tier 2 Self-Critique pass before showing approval card
        if tier == 2:
            yield _sse_status("self_critique", f"Self-critique pass: verifying {len(staged_changes)} staged change(s)...")
            is_clean, critique_fb = _evaluate_edit_critique(workspace, staged_changes, user_query)
            if not is_clean:
                yield _sse_status("self_critique", f"⚠️ {critique_fb}", outcome="rejected")
                _append_activity_log(workspace, {
                    "action_type": "self_critique",
                    "target": ", ".join(c.path for c in staged_changes),
                    "outcome": "rejected",
                    "tier": 2,
                    "details": critique_fb,
                })
                yield _sse_command_result("self_critique", critique_fb, 1, False)
                yield _sse_event("finalization", {"success": False, "reason": "self_critique_rejected"})
                return
            else:
                yield _sse_status("self_critique", "✓ Self-critique passed: surgical changes match request intent.", outcome="passed")
                _append_activity_log(workspace, {
                    "action_type": "self_critique",
                    "target": ", ".join(c.path for c in staged_changes),
                    "outcome": "passed",
                    "tier": 2,
                    "details": "Surgical diff verified",
                })

        # Secret Scanning Pass (Entropy + Regex Scan)
        has_secret, secret_err = _scan_for_secrets(staged_changes)
        if has_secret:
            yield _sse_status("secret_scan", f"🚫 {secret_err}", outcome="rejected")
            _append_activity_log(workspace, {
                "action_type": "secret_scan",
                "target": ", ".join(c.path for c in staged_changes),
                "outcome": "rejected",
                "tier": tier,
                "token_count": 0,
                "details": secret_err,
            })
            yield _sse_command_result("secret_scan", secret_err, 1, False)
            yield _sse_error(secret_err)
            yield _sse_event("finalization", {"success": False, "reason": "secret_scan_rejected"})
            return

        proposal_payload = EditProposalRequest(
            workspace=workspace,
            summary=f"Rony Agent: {len(staged_changes)} file(s) created/modified",
            changes=staged_changes,
        )
        create_proposal_fn = _get_create_proposal()
        proposal = await create_proposal_fn(proposal_payload)
        proposal_id = proposal.id if hasattr(proposal, "id") else str(proposal)
        
        for change in staged_changes:
            path_str = change.path if hasattr(change, "path") else str(change)
            yield _sse_proposal(proposal_id, path_str, summary=f"Changes for {path_str}", changes_count=len(staged_changes))
        
        summary_paths = ", ".join(c.path for c in staged_changes)
        diff_summary = "\n".join(_generate_diff_summary(c) for c in staged_changes)
        action_id = str(uuid.uuid4())
        reason = f"Rony Agent wants to create/modify {summary_paths}"

        pending = PendingApproval(
            action_id=action_id,
            action_type="edit",
            detail=summary_paths,
            reason=reason,
            proposal_id=proposal_id,
            path=summary_paths,
            diff_summary=diff_summary,
            workspace=workspace,
        )
        _pending_approvals[action_id] = pending

        yield _sse_approval_request(
            action_id=action_id,
            action_type="edit",
            detail=summary_paths,
            reason=reason,
            proposal_id=proposal_id,
            path=summary_paths,
            diff_summary=diff_summary,
        )
        yield _sse_status(
            "approval_required",
            f"Approval needed to apply changes to: {summary_paths}",
            detail=summary_paths,
            proposal_id=proposal_id,
        )

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=_get_edit_approval_timeout())
            if pending.approved:
                # Pre-apply checkpoint commit
                touched_paths = [c.path for c in staged_changes]
                new_init, commit_h, err = _ensure_git_checkpoint(workspace, turn_number, touched_files=touched_paths)
                if err and "sensitive file" in err.lower():
                    yield _sse_error(err)
                    yield _sse_done(False, err)
                    yield _sse_event("finalization", {"success": False, "reason": "checkpoint_failed"})
                    return
                if new_init:
                    yield _sse_status("checkpoint", "initialized git repo for turn checkpoints")
                if commit_h:
                    yield _sse_status("checkpoint", f"Created pre-turn checkpoint commit: rony-turn-{turn_number}-pre ({commit_h[:7]})", commit_hash=commit_h)

                # Regression Guard: Baseline test snapshot before applying
                ran_test_before, p_before, f_before, sum_before = await _discover_and_run_test_snapshot(workspace, touched_paths)
                if ran_test_before:
                    yield _sse_status("regression_guard", f"Baseline tests before apply: {sum_before}", phase="before", passed=p_before, failed=f_before)

                apply_proposal_fn = _get_apply_proposal()
                await apply_proposal_fn(proposal_id)
                yield _sse_status("tool", f"Approved: Applied changes to {summary_paths}", tool="edit_file", detail=summary_paths)
                yield _sse_command_result(f"edit {summary_paths}", f"Successfully applied changes to {summary_paths} (Proposal: {proposal_id})", 0, True)

                # Regression Guard: Post-apply test snapshot
                if ran_test_before:
                    ran_test_after, p_after, f_after, sum_after = await _discover_and_run_test_snapshot(workspace, touched_paths)
                    if ran_test_after:
                        has_regression = (f_after > f_before) or (p_after < p_before)
                        if has_regression:
                            reg_msg = f"Tests before: {p_before} passed → Tests after: {p_after} passed, {f_after} failed — ⚠️ REGRESSION DETECTED."
                            yield _sse_status("regression_guard", reg_msg, phase="after", regression=True, before={"passed": p_before, "failed": f_before}, after={"passed": p_after, "failed": f_after})
                            _append_activity_log(workspace, {
                                "action_type": "regression_guard",
                                "target": summary_paths,
                                "outcome": "regression_detected",
                                "tier": tier,
                                "details": reg_msg,
                            })
                        else:
                            reg_msg = f"Tests before: {p_before} passed → Tests after: {p_after} passed (0 regressions)."
                            yield _sse_status("regression_guard", reg_msg, phase="after", regression=False, before={"passed": p_before, "failed": f_before}, after={"passed": p_after, "failed": f_after})
                            _append_activity_log(workspace, {
                                "action_type": "regression_guard",
                                "target": summary_paths,
                                "outcome": "passed",
                                "tier": tier,
                                "details": reg_msg,
                            })

                # Post-Apply Read-Back: Confirm modified files exist on disk with updated content
                read_back_verified = True
                for c in staged_changes:
                    try:
                        full_p = ensure_within_workspace(workspace, c.path)
                        if full_p.is_file():
                            disk_content = full_p.read_text(encoding="utf-8", errors="replace")
                            target_updated = c.updated.strip()
                            if not target_updated:
                                matched = True
                            elif len(target_updated) <= 2000:
                                matched = target_updated in disk_content
                            else:
                                head_chunk = target_updated[:200]
                                mid_idx = len(target_updated) // 2
                                mid_chunk = target_updated[mid_idx:mid_idx + 200]
                                tail_chunk = target_updated[-200:]
                                matched = (head_chunk in disk_content) and (mid_chunk in disk_content) and (tail_chunk in disk_content)

                            if matched:
                                yield _sse_status("verified_disk", f"✓ change verified on disk: '{c.path}'", path=c.path, confirmed=True)
                            else:
                                read_back_verified = False
                                yield _sse_status("verified_disk", f"⚠️ Warning: Target content not fully confirmed on disk for '{c.path}'", path=c.path, confirmed=False)
                        else:
                            read_back_verified = False
                            yield _sse_status("verified_disk", f"⚠️ Target file missing after apply: '{c.path}'", path=c.path, confirmed=False)
                    except Exception as rb_exc:
                        read_back_verified = False
                        logger.warning("chat_harness: post-apply read-back failed for %s: %s", c.path, rb_exc)

                # Living Architecture Document: Auto-update on multi-file changes or new modules
                if len(staged_changes) > 1 or any(c.original == "" for c in staged_changes):
                    try:
                        _update_architecture_doc(workspace, reason=f"Applied changes to {summary_paths}")
                    except Exception:
                        pass

                _append_activity_log(workspace, {
                    "action_type": "edit_proposal",
                    "target": summary_paths,
                    "outcome": "approved",
                    "tier": tier,
                    "details": f"Applied {len(staged_changes)} file change(s) (Proposal: {proposal_id[:8]})",
                })

                if commit_h:
                    yield _sse_checkpoint(turn_number, commit_h, touched_paths)

                regressed = bool(ran_test_before and 'has_regression' in locals() and has_regression)
                final_reason = "verified"
                if not read_back_verified:
                    final_reason = "read_back_failed"
                elif regressed:
                    final_reason = "test_regression"

                yield _sse_event("finalization", {
                    "success": read_back_verified and not regressed,
                    "reason": final_reason,
                })
            else:
                reject_proposal_fn = _get_reject_proposal()
                try:
                    await reject_proposal_fn(proposal_id)
                except Exception:
                    pass
                _append_activity_log(workspace, {
                    "action_type": "edit_proposal",
                    "target": summary_paths,
                    "outcome": "rejected",
                    "tier": tier,
                    "details": f"User rejected changes to {summary_paths}",
                })
                yield _sse_command_result(f"edit {summary_paths}", f"User rejected changes to {summary_paths}.", 1, False)
                yield _sse_event("finalization", {"success": False, "reason": "user_rejected"})
        except asyncio.TimeoutError:
            _append_activity_log(workspace, {
                "action_type": "edit_proposal",
                "target": summary_paths,
                "outcome": "timed_out",
                "tier": tier,
                "details": f"Approval timed out after {int(_get_edit_approval_timeout())}s",
            })
            yield _sse_command_result(f"edit {summary_paths}", f"Edit approval timed out after {int(_get_edit_approval_timeout())}s.", 1, False)
            yield _sse_event("finalization", {"success": False, "reason": "approval_timeout"})
        finally:
            _pending_approvals.pop(action_id, None)

    except Exception as exc:
        logger.exception("chat_harness: failed to create edit proposal: %s", exc)
        yield _sse_error(f"Failed to create edit proposal: {exc}")
        yield _sse_event("finalization", {"success": False, "reason": "finalizer_exception", "detail": str(exc)[:200]})
