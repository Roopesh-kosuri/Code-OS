"""
Duo Generator/Critic loop engine.

Architecture
------------
- Each DuoSession runs as a background asyncio.Task.
- The Generator produces a code proposal (PROPOSAL format) every round.
- The Critic inspects that proposal and returns structured JSON:
    {"approved": bool, "issues": [...], "reasoning": "..."}
- Rounds persist to SQLite immediately — crash-safe, pollable via GET.
- The loop NEVER calls apply_proposal() — all disk writes go through
  the user-facing DiffViewer approval step.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from ...db.database import get_db
from ..ai.schemas import ChatMessage, ChatRequest, EditProposalRequest, FileChange
from ..ai.service import PROPOSAL_RE, create_proposal, provider_for
from ..ai.context_service import gather_context

from .schemas import (
    CriticIssue,
    CriticVerdict,
    DuoRoundDto,
    DuoSessionDto,
    DuoSessionRequest,
    ModelConfig,
)

logger = logging.getLogger(__name__)

# Active asyncio Tasks keyed by session_id — used for cancellation
_active_tasks: dict[str, asyncio.Task] = {}
_pending_recovery_events: dict[str, asyncio.Event] = {}
_pending_recovery_decisions: dict[str, str] = {}
_pending_recovery_errors: dict[str, str] = {}
_pending_recovery_data: dict[str, dict] = {}

# ── JSON extraction helper ────────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from a (possibly prose-wrapped) LLM response."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown fence ```json … ``` or bare ```  ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # Greedy: find outermost { ... }
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No valid JSON found in critic response: {text[:300]}")


# ── Provider builder ──────────────────────────────────────────────────────────

async def _build_provider(cfg: ModelConfig):
    """Instantiate the correct AI provider for a ModelConfig."""
    req = ChatRequest(
        provider=cfg.provider,
        model=cfg.model,
        messages=[],
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        api_key_provider=cfg.api_key_provider,
    )
    provider = await provider_for(req)
    cfg.model = req.model
    cfg.provider = req.provider
    cfg.base_url = req.base_url
    cfg.api_key_provider = req.api_key_provider
    logger.info("duo.loop.build_provider resolved: provider=%s model=%s (LIVE_PATCH_V2)", cfg.provider, cfg.model)
    return provider


async def _call_model(cfg: ModelConfig, messages: list[ChatMessage], timeout_seconds: float = 45.0) -> str:
    """Call a model and return the full concatenated response text with fallback and bounded timeout."""
    async def _invoke():
        provider = await _build_provider(cfg)
        tokens: list[str] = []
        async for token in provider.stream_chat(cfg.model, messages, cfg.temperature):
            tokens.append(token)
        return "".join(tokens).strip()

    try:
        return await asyncio.wait_for(_invoke(), timeout=timeout_seconds)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        logger.error("duo.call_model.timeout model=%s provider=%s timeout=%.1fs", cfg.model, cfg.provider, timeout_seconds)
        raise TimeoutError(f"Model call timed out after {timeout_seconds:.1f}s")
    except Exception as exc:
        if cfg.provider == "ollama":
            from ..ai.service import get_api_key
            for kid, default_model in [("groq", "llama-3.3-70b-versatile"), ("openai", "gpt-4o"), ("gemini", "gemini-2.5-flash")]:
                key = await get_api_key(kid)
                if key:
                    logger.info("duo.loop.auto_fallback from ollama to %s (%s)", kid, default_model)
                    cfg.provider = "openai-compatible"
                    cfg.model = default_model
                    cfg.api_key_provider = kid
                    cfg.base_url = None
                    provider = await _build_provider(cfg)
                    tokens = []
                    async for token in provider.stream_chat(cfg.model, messages, cfg.temperature):
                        tokens.append(token)
                    return "".join(tokens).strip()
        raise


# ── System prompts ────────────────────────────────────────────────────────────

_GENERATOR_SYSTEM = """\
You are an expert software engineer (Generator).
Your job: implement the requested task by producing EXACTLY ONE edit proposal.
The proposal MUST use this exact format — no other format will be accepted:

[PROPOSAL: path/to/file.ext]
<<<<
<exact original code to replace, or empty string for new files>
====
<new code>
>>>>

Rules:
- Output reasoning FIRST, then the proposal block at the end.
- The proposal must be complete and syntactically correct.
- If you are creating a new file, leave the original section empty.
- Do NOT apply changes directly; only output the proposal block.
"""

_GENERATOR_REVISION_SYSTEM = """\
You are an expert software engineer (Generator) in revision mode.
The Critic has reviewed your previous proposal and found issues.
Fix ALL reported issues and produce a revised proposal using the EXACT same format:

[PROPOSAL: path/to/file.ext]
<<<<
<exact original code to replace>
====
<revised code>
>>>>

Address every issue listed by the Critic. Be thorough.
"""

_CRITIC_SYSTEM = """\
You are a strict senior code reviewer (Critic).
You will receive a code change proposal and the original task description.
Evaluate whether the proposal fully and correctly solves the task.

Respond with ONLY a JSON object — no markdown, no prose before or after:
{
  "approved": true | false,
  "reasoning": "one sentence summary of your decision",
  "issues": [
    {
      "description": "what is wrong",
      "severity": "high" | "medium" | "low",
      "suggested_fix": "how to fix it (optional)"
    }
  ]
}

If the code is correct and complete, return approved=true with an empty issues array.
If there are problems, return approved=false with a non-empty issues array.
Be specific. Be concise.
"""


# ── DB helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def _db_create_session(
    session_id: str,
    req: DuoSessionRequest,
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO duo_sessions
            (id, workspace, task_description, status, current_round, max_rounds,
             final_proposal_id, generator_config, critic_config, created_at, updated_at)
        VALUES (?, ?, ?, 'running', 0, ?, NULL, ?, ?, ?, ?)
        """,
        (
            session_id,
            req.workspace,
            req.task_description,
            req.max_rounds,
            req.generator.model_dump_json(),
            req.critic.model_dump_json(),
            _now_iso(),
            _now_iso(),
        ),
    )
    await db.commit()

async def _db_update_config(
    session_id: str,
    generator_config: str,
    critic_config: str
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE duo_sessions SET generator_config=?, critic_config=?, updated_at=? WHERE id=?",
        (generator_config, critic_config, _now_iso(), session_id),
    )
    await db.commit()

async def _db_add_round(
    session_id: str,
    round_number: int,
    generator_output: str,
    proposal_id: str | None,
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO duo_rounds (session_id, round_number, generator_output, proposal_id, critic_verdict, created_at)
        VALUES (?, ?, ?, ?, NULL, ?)
        """,
        (session_id, round_number, generator_output, proposal_id, _now_iso()),
    )
    await db.execute(
        "UPDATE duo_sessions SET current_round=?, updated_at=? WHERE id=?",
        (round_number, _now_iso(), session_id),
    )
    await db.commit()


async def _db_update_round_verdict(
    session_id: str,
    round_number: int,
    verdict: CriticVerdict,
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE duo_rounds SET critic_verdict=? WHERE session_id=? AND round_number=?",
        (verdict.model_dump_json(), session_id, round_number),
    )
    await db.execute(
        "UPDATE duo_sessions SET updated_at=? WHERE id=?",
        (_now_iso(), session_id),
    )
    await db.commit()


async def _db_finish_session(
    session_id: str,
    status: str,
    final_proposal_id: str | None,
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE duo_sessions SET status=?, final_proposal_id=?, updated_at=? WHERE id=?",
        (status, final_proposal_id, _now_iso(), session_id),
    )
    await db.commit()


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_session(session_id: str) -> DuoSessionDto:
    db = await get_db()
    cur = await db.execute("SELECT * FROM duo_sessions WHERE id=?", (session_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Duo session not found")

    rounds_cur = await db.execute(
        "SELECT * FROM duo_rounds WHERE session_id=? ORDER BY round_number ASC",
        (session_id,),
    )
    round_rows = await rounds_cur.fetchall()

    rounds: list[DuoRoundDto] = []
    for r in round_rows:
        verdict = None
        if r["critic_verdict"]:
            try:
                verdict = CriticVerdict.model_validate_json(r["critic_verdict"])
            except Exception:
                pass
        rounds.append(
            DuoRoundDto(
                round_number=r["round_number"],
                generator_output=r["generator_output"],
                proposal_id=r["proposal_id"],
                critic_verdict=verdict,
                created_at=r["created_at"],
            )
        )

    pending_action = None
    if row["status"] == "waiting_for_recovery" and session_id in _pending_recovery_errors:
        pending_action = {
            "type": "llm_failure",
            "details": _pending_recovery_errors[session_id]
        }

    return DuoSessionDto(
        id=row["id"],
        workspace=row["workspace"],
        task_description=row["task_description"],
        status=row["status"],
        current_round=row["current_round"],
        max_rounds=row["max_rounds"],
        rounds=rounds,
        final_proposal_id=row["final_proposal_id"],
        generator=ModelConfig.model_validate_json(row["generator_config"]),
        critic=ModelConfig.model_validate_json(row["critic_config"]),
        created_at=row["created_at"],
        pending_action=pending_action
    )


async def list_sessions(workspace: str) -> list[DuoSessionDto]:
    db = await get_db()
    cur = await db.execute(
        "SELECT id FROM duo_sessions WHERE workspace=? ORDER BY created_at DESC LIMIT 50",
        (workspace,),
    )
    rows = await cur.fetchall()
    results = []
    for row in rows:
        try:
            results.append(await get_session(row["id"]))
        except Exception:
            pass
    return results


# ── Core loop ─────────────────────────────────────────────────────────────────

async def _handle_duo_llm_failure(session_id: str, exc: Exception) -> dict:
    """Pauses Duo loop on LLM failure and waits for user decision."""
    event = asyncio.Event()
    _pending_recovery_events[session_id] = event
    _pending_recovery_errors[session_id] = str(exc)
    
    # Set status to waiting_for_recovery
    db = await get_db()
    await db.execute("UPDATE duo_sessions SET status='waiting_for_recovery', updated_at=? WHERE id=?", (_now_iso(), session_id))
    await db.commit()
        
    await event.wait()
    
    _pending_recovery_events.pop(session_id, None)
    _pending_recovery_errors.pop(session_id, None)
    decision = _pending_recovery_decisions.pop(session_id, "cancel")
    recovery_data = _pending_recovery_data.pop(session_id, {})
    
    db = await get_db()
    await db.execute("UPDATE duo_sessions SET status='running', updated_at=? WHERE id=?", (_now_iso(), session_id))
    await db.commit()
        
    return {
        "action": decision,
        "provider": recovery_data.get("provider"),
        "model": recovery_data.get("model"),
        "api_key_provider": recovery_data.get("api_key_provider"),
    }



async def _run_loop(session_id: str, req: DuoSessionRequest) -> None:
    """Background task: runs the Generator→Critic loop."""
    logger.info("duo.loop.start session_id=%s max_rounds=%d", session_id, req.max_rounds)

    # Scoped context for critic (workspace README, git status, dependencies)
    try:
        ctx = await gather_context(req.workspace, query=req.task_description[:200])
        context_text = (
            f"Workspace: {ctx.get('workspace', req.workspace)}\n"
            f"Branch: {ctx.get('git_status', {}).get('branch', 'unknown')}\n"
            f"README (excerpt): {(ctx.get('readme') or '')[:2000]}\n"
            f"Dependencies: {', '.join(d['name'] for d in ctx.get('dependencies', [])[:20]) or 'none listed'}"
        )
    except Exception as exc:
        logger.warning("duo.loop context gather failed: %s", exc)
        context_text = f"Workspace: {req.workspace}"

    last_proposal_id: str | None = None
    critic_issues_text = ""          # fed back to generator on revision

    for round_num in range(1, req.max_rounds + 1):
        logger.info("duo.loop.round session_id=%s round=%d", session_id, round_num)

        # ── 1. Generator ──────────────────────────────────────────────────────
        if round_num == 1:
            system_prompt = _GENERATOR_SYSTEM
            user_content = f"Task:\n{req.task_description}"
        else:
            system_prompt = _GENERATOR_REVISION_SYSTEM
            user_content = (
                f"Task:\n{req.task_description}\n\n"
                f"Critic issues from round {round_num - 1}:\n{critic_issues_text}"
            )

        gen_messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]

        try:
            auto_retries = 0
            MAX_AUTO_RETRIES = 2
            while auto_retries <= MAX_AUTO_RETRIES:
                try:
                    gen_output = await _call_model(req.generator, gen_messages, timeout_seconds=45.0)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("duo.loop.generator_error session_id=%s round=%d (auto-retry %d/%d): %s", session_id, round_num, auto_retries, MAX_AUTO_RETRIES, exc)
                    if req.internal:
                        # Agent-invoked internal loop: limited auto-retries, then fail
                        if auto_retries >= MAX_AUTO_RETRIES:
                            logger.warning("duo.loop.internal_failure session_id=%s round=%d: exhausted retries", session_id, round_num)
                            await _db_finish_session(session_id, "error", last_proposal_id)
                            return
                        auto_retries += 1
                        await asyncio.sleep(1.5 * auto_retries)
                        continue
                    # External (user-facing) mode: escalate after auto-retries
                    if auto_retries >= MAX_AUTO_RETRIES:
                        decision_res = await _handle_duo_llm_failure(session_id, exc)
                        action = decision_res.get("action", "cancel")
                        if action == "retry":
                            auto_retries = 0
                            continue
                        elif action in ("switch_to_api", "change_model"):
                            auto_retries = 0
                            new_provider = decision_res.get("provider") or "groq"
                            new_model = decision_res.get("model") or ("llama-3.3-70b-versatile" if new_provider == "groq" else "gpt-4o")
                            new_key_provider = decision_res.get("api_key_provider") or new_provider
                            req.generator.provider = new_provider
                            req.generator.model = new_model
                            req.generator.api_key_provider = new_key_provider
                            req.generator.base_url = None
                            await _db_update_config(session_id, req.generator.model_dump_json(), req.critic.model_dump_json())
                            continue
                        else:
                            await _db_finish_session(session_id, "error", last_proposal_id)
                            return
                    else:
                        auto_retries += 1
                        await asyncio.sleep(1.5 * auto_retries)
        except asyncio.CancelledError:
            await _db_finish_session(session_id, "cancelled", last_proposal_id)
            logger.info("duo.loop.cancelled session_id=%s at round %d", session_id, round_num)
            return

        # Extract proposal changes
        proposal_id: str | None = None
        changes: list[FileChange] = []
        for match in PROPOSAL_RE.finditer(gen_output):
            filepath = match.group("path").strip()
            original = match.group("original")
            updated = match.group("updated")
            try:
                from pathlib import Path
                workspace_path = Path(req.workspace)
                resolved = Path(filepath)
                if not resolved.is_absolute():
                    resolved = (workspace_path / filepath).resolve()
                if not resolved.exists():
                    original = ""
                changes.append(FileChange(path=str(resolved), original=original, updated=updated))
            except Exception as exc:
                logger.warning("duo.loop.path_error round=%d: %s", round_num, exc)

        if changes:
            try:
                proposal = await create_proposal(
                    EditProposalRequest(
                        workspace=req.workspace,
                        summary=f"[Duo Round {round_num}] {req.task_description[:80]}",
                        changes=changes,
                    )
                )
                proposal_id = proposal.id
                last_proposal_id = proposal_id
                logger.info("duo.loop.proposal_created id=%s round=%d changes=%d", proposal_id, round_num, len(changes))
            except Exception as exc:
                logger.warning("duo.loop.proposal_error round=%d: %s", round_num, exc)

        # Persist round (without verdict yet)
        await _db_add_round(session_id, round_num, gen_output, proposal_id)

        # ── 2. Critic ─────────────────────────────────────────────────────────
        critic_user = (
            f"Original task:\n{req.task_description}\n\n"
            f"Context:\n{context_text}\n\n"
            f"Generator output (round {round_num}):\n{gen_output}"
        )
        critic_messages = [
            ChatMessage(role="system", content=_CRITIC_SYSTEM),
            ChatMessage(role="user", content=critic_user),
        ]

        try:
            auto_retries = 0
            while auto_retries <= MAX_AUTO_RETRIES:
                try:
                    critic_raw = await _call_model(req.critic, critic_messages, timeout_seconds=45.0)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("duo.loop.critic_error session_id=%s round=%d (auto-retry %d/%d): %s", session_id, round_num, auto_retries, MAX_AUTO_RETRIES, exc)
                    if req.internal:
                        if auto_retries >= MAX_AUTO_RETRIES:
                            logger.warning("duo.loop.critic_internal_fallback round=%d: treating failure as rejection", round_num)
                            critic_raw = ""
                            verdict = CriticVerdict(
                                approved=False,
                                reasoning=f"Critic call failed: {exc}",
                                issues=[CriticIssue(description=str(exc), severity="high")],
                            )
                            break
                        auto_retries += 1
                        await asyncio.sleep(1.5 * auto_retries)
                        continue
                    # External mode: escalate after auto-retries
                    if auto_retries >= MAX_AUTO_RETRIES:
                        decision_res = await _handle_duo_llm_failure(session_id, exc)
                        action = decision_res.get("action", "cancel")
                        if action == "retry":
                            auto_retries = 0
                            continue
                        elif action in ("switch_to_api", "change_model"):
                            auto_retries = 0
                            new_provider = decision_res.get("provider") or "groq"
                            new_model = decision_res.get("model") or ("llama-3.3-70b-versatile" if new_provider == "groq" else "gpt-4o")
                            new_key_provider = decision_res.get("api_key_provider") or new_provider
                            req.critic.provider = new_provider
                            req.critic.model = new_model
                            req.critic.api_key_provider = new_key_provider
                            req.critic.base_url = None
                            await _db_update_config(session_id, req.generator.model_dump_json(), req.critic.model_dump_json())
                            continue
                        else:
                            critic_raw = ""
                            verdict = CriticVerdict(
                                approved=False,
                                reasoning=f"Critic call failed: {exc}",
                                issues=[CriticIssue(description=str(exc), severity="high")],
                            )
                            break
                    else:
                        auto_retries += 1
                        await asyncio.sleep(1.5 * auto_retries)
        except asyncio.CancelledError:
            await _db_finish_session(session_id, "cancelled", last_proposal_id)
            return
        except Exception as exc:
            pass  # Handled above or loop continues

        if critic_raw:
            # Parse JSON verdict with robust fallback
            try:
                raw_dict = _extract_json(critic_raw)
                verdict = CriticVerdict(
                    approved=bool(raw_dict.get("approved", False)),
                    reasoning=str(raw_dict.get("reasoning", "")),
                    issues=[
                        CriticIssue(
                            description=i.get("description", ""),
                            severity=i.get("severity", "medium"),
                            suggested_fix=i.get("suggested_fix"),
                        )
                        for i in raw_dict.get("issues", [])
                    ],
                )
            except Exception as parse_exc:
                logger.warning("duo.loop.critic_parse_error round=%d: %s", round_num, parse_exc)
                # Fallback: treat unparseable response as rejection
                verdict = CriticVerdict(
                    approved=False,
                    reasoning="Critic response could not be parsed — treated as rejection.",
                    issues=[
                        CriticIssue(
                            description=f"Could not parse critic JSON. Raw: {critic_raw[:500]}",
                            severity="medium",
                        )
                    ],
                )

        # Persist verdict
        await _db_update_round_verdict(session_id, round_num, verdict)
        logger.info(
            "duo.loop.verdict session_id=%s round=%d approved=%s issues=%d",
            session_id, round_num, verdict.approved, len(verdict.issues),
        )

        # ── 3. Decision ───────────────────────────────────────────────────────
        if verdict.approved:
            await _db_finish_session(session_id, "approved", last_proposal_id)
            logger.info("duo.loop.approved session_id=%s round=%d", session_id, round_num)
            return

        # Build issues text for next generator round
        issue_lines = []
        for i, issue in enumerate(verdict.issues, 1):
            line = f"{i}. [{issue.severity.upper()}] {issue.description}"
            if issue.suggested_fix:
                line += f"\n   Suggested fix: {issue.suggested_fix}"
            issue_lines.append(line)
        critic_issues_text = verdict.reasoning + "\n\n" + "\n".join(issue_lines)

    # Max rounds exhausted without approval
    await _db_finish_session(session_id, "unresolved", last_proposal_id)
    logger.info("duo.loop.unresolved session_id=%s after %d rounds", session_id, req.max_rounds)


from ..settings.service import list_settings

async def _resolve_model_config(cfg: ModelConfig) -> None:
    if not cfg.model or cfg.model.strip() == "" or cfg.model == "auto":
        settings = await list_settings()
        
        # 1. Ollama provider fallback
        if cfg.provider == "ollama" or not cfg.api_key_provider:
            cfg.model = settings.get("ollama.model") or "llama3"
            return
            
        # 2. Key-based provider defaults (all 9 providers)
        presets = {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-5",
            "gemini": "gemini-2.5-flash",
            "groq": "llama-3.3-70b-versatile",
            "deepseek": "deepseek-chat",
            "mistral": "mistral-large-latest",
            "openrouter": "openai/gpt-4o",
            "nvidia-nim": "meta/llama-3.3-70b-instruct",
            "custom": "gpt-4o"
        }
        provider_id = cfg.api_key_provider or "openai"
        cfg.model = settings.get(f"{provider_id}.model") or presets.get(provider_id) or "gpt-4o"


# ── Public API ────────────────────────────────────────────────────────────────

async def start_session(req: DuoSessionRequest) -> DuoSessionDto:
    """Create a new Duo session and launch the loop as a background task."""
    session_id = str(uuid.uuid4())
    
    # Resolve fallback models for both generator and critic if they are empty
    await _resolve_model_config(req.generator)
    await _resolve_model_config(req.critic)
    
    await _db_create_session(session_id, req)

    loop = asyncio.get_event_loop()
    task = loop.create_task(_run_loop(session_id, req))
    _active_tasks[session_id] = task

    # Clean up task reference when done
    def _on_done(t: asyncio.Task) -> None:
        _active_tasks.pop(session_id, None)
        if not t.cancelled() and t.exception():
            logger.error("duo.loop.unhandled_exception session_id=%s: %s", session_id, t.exception())

    task.add_done_callback(_on_done)

    return await get_session(session_id)


async def cancel_session(session_id: str) -> DuoSessionDto:
    """Cancel a running Duo session."""
    task = _active_tasks.get(session_id)
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Ensure DB reflects cancelled state even if the task didn't write it
    db = await get_db()
    cur = await db.execute("SELECT status FROM duo_sessions WHERE id=?", (session_id,))
    row = await cur.fetchone()
    if row and row["status"] == "running":
        await db.execute(
            "UPDATE duo_sessions SET status='cancelled', updated_at=? WHERE id=?",
            (_now_iso(), session_id),
        )
        await db.commit()

    return await get_session(session_id)
