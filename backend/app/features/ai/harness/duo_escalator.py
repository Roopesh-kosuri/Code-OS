from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Dict, Optional

from typing import Any
from .approval_coordinator import PendingApproval, _pending_approvals
from .tool_executor import EDIT_APPROVAL_TIMEOUT_SECONDS
from .failure_handler import log_and_flag_failure
from .sse_streamer import (
    _sse_status, _sse_proposal, _sse_approval_request, _sse_command_result,
    _sse_done, _sse_error
)

logger = logging.getLogger(__name__)

def _get_edit_approval_timeout() -> float:
    try:
        from app.features.ai import chat_harness
        return getattr(chat_harness, "EDIT_APPROVAL_TIMEOUT_SECONDS", 300.0)
    except Exception:
        return 300.0

async def _escalate_to_duo(
    request: Any,
    task_description: str,
) -> AsyncIterator[str]:
    """Escalate a difficult task to the Duo Generator/Critic loop."""
    from ..duo.service import start_session as duo_start_session, get_session as duo_get_session
    from ..duo.schemas import DuoSessionRequest, ModelConfig
    
    yield _sse_status("duo_escalation", "Starting Duo Loop adversarial refinement...")
    
    try:
        duo_req = DuoSessionRequest(
            workspace=request.workspace,
            task_description=task_description,
            generator=ModelConfig(
                provider=request.provider or "auto",
                model=request.model or "",
                base_url=request.base_url,
                api_key_provider=request.api_key_provider,
            ),
            critic=ModelConfig(
                provider=request.provider or "auto",
                model=request.model or "",
                base_url=request.base_url,
                api_key_provider=request.api_key_provider,
            ),
            max_rounds=5,
            internal=True,
        )
        
        session = await duo_start_session(duo_req)
        session_id = session.id
        
        yield _sse_status("duo_escalation", f"Duo Loop active (session {session_id[:8]})...")
        
        for _ in range(60):
            await asyncio.sleep(5)
            session = await duo_get_session(session_id)
            
            if session.status in ("approved", "unresolved", "error", "cancelled"):
                break
            
            round_num = session.current_round
            yield _sse_status("duo_escalation", f"Duo Loop: Round {round_num}/{session.max_rounds} (Critic reviewing)...")
        
        target_prop_id = session.final_proposal_id or (session.rounds[-1].proposal_id if session.rounds and session.rounds[-1].proposal_id else None)
        if target_prop_id:
            from .service import get_proposal
            prop = await get_proposal(target_prop_id)
            if prop:
                action_id = f"duo-proposal-{uuid.uuid4().hex[:8]}"
                summary_paths = ", ".join([c.path for c in prop.changes]) if prop.changes else "files"
                diff_summary = prop.diff or f"Changes to {summary_paths}"

                pending = PendingApproval(
                    action_id=action_id,
                    action_type="edit",
                    detail=summary_paths,
                    reason=f"Duo Loop ({session.status}): Review proposed changes",
                    proposal_id=target_prop_id,
                    path=summary_paths,
                    diff_summary=diff_summary,
                )
                _pending_approvals[action_id] = pending

                yield _sse_proposal(target_prop_id, "Duo Loop result", summary=f"Duo Loop proposed changes to {summary_paths}")
                yield _sse_approval_request(
                    action_id=action_id,
                    action_type="edit",
                    detail=summary_paths,
                    reason=f"Duo Loop ({session.status}): Review proposed changes",
                    proposal_id=target_prop_id,
                    path=summary_paths,
                    diff_summary=diff_summary,
                )
                yield _sse_status(
                    "approval_required",
                    f"Duo Loop proposal ready for approval: {summary_paths}",
                    detail=summary_paths,
                    proposal_id=target_prop_id,
                )

                try:
                    await asyncio.wait_for(pending.event.wait(), timeout=_get_edit_approval_timeout())
                    if pending.approved:
                        from .service import apply_proposal
                        await apply_proposal(target_prop_id)
                        yield _sse_status("tool", f"Approved: Applied Duo Loop changes to {summary_paths}", tool="edit_file", detail=summary_paths)
                        yield _sse_command_result(f"edit {summary_paths}", f"Successfully applied Duo Loop changes to {summary_paths} (Proposal: {target_prop_id})", 0, True)
                        yield _sse_done(True, f"Duo Loop changes approved and applied to {summary_paths}.")
                    else:
                        from .service import reject_proposal
                        try:
                            await reject_proposal(target_prop_id)
                        except Exception as exc:
                            log_and_flag_failure("reject_proposal", exc, {"target_prop_id": target_prop_id})
                        yield _sse_command_result(f"edit {summary_paths}", f"User rejected Duo Loop changes to {summary_paths}.", 1, False)
                        yield _sse_done(False, "Duo Loop proposal rejected by user.")
                except asyncio.TimeoutError:
                    yield _sse_command_result(f"edit {summary_paths}", f"Edit approval timed out after {int(_get_edit_approval_timeout())}s.", 1, False)
                    yield _sse_done(False, "Duo Loop proposal timed out waiting for user approval.")
                finally:
                    _pending_approvals.pop(action_id, None)
                return

        if session.status == "approved" and session.final_proposal_id:
            yield _sse_proposal(session.final_proposal_id, "Duo Loop result", summary="Duo Loop approved changes")
            yield _sse_status("duo_escalation", "Duo Loop approved — proposal ready in Diff Inspector")
            yield _sse_done(True, "Duo Loop completed with verified approval. Review changes in Diff Inspector.")
        elif session.status == "unresolved":
            yield _sse_done(False, "Duo Loop reached round limit without valid proposal.")
        else:
            yield _sse_done(False, f"Duo Loop finished with status: {session.status}")
    
    except Exception as exc:
        logger.error("chat_harness: Duo Loop escalation failed: %s", exc)
        yield _sse_error(f"Duo Loop escalation error: {exc}")
        yield _sse_done(False, f"Escalation error: {exc}")
