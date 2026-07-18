from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.features.ai.schemas import ChatRequest, EditProposalDto, EditProposalRequest, ModelDto, ProviderHealth, ContextRequest
from backend.app.features.ai.service import apply_proposal, create_proposal, get_proposal, ollama_health, ollama_models, stream_chat, reject_proposal, list_proposals
from backend.app.features.ai.context_service import gather_context

router = APIRouter()


@router.get("/ollama/health", response_model=ProviderHealth)
async def ollama_health_route(base_url: str | None = Query(default=None)) -> ProviderHealth:
    return await ollama_health(base_url)


@router.get("/ollama/models", response_model=list[ModelDto])
async def ollama_models_route(base_url: str | None = Query(default=None)) -> list[ModelDto]:
    return await ollama_models(base_url)


@router.get("/models", response_model=list[ModelDto])
async def list_provider_models(
    provider: str = Query(...),
    base_url: str = Query(...),
    api_key_provider: str | None = Query(default=None),
) -> list[ModelDto]:
    from fastapi import HTTPException
    from backend.app.features.settings.service import get_api_key
    from backend.app.features.ai.providers.ollama import OllamaProvider
    from backend.app.features.ai.providers.openai_compatible import OpenAICompatibleProvider
    
    try:
        if provider == "ollama":
            return await OllamaProvider(base_url).models()
        elif provider == "openai-compatible":
            key_id = api_key_provider or "openai-compatible"
            api_key = await get_api_key(key_id)
            return await OpenAICompatibleProvider(base_url, api_key).models()
        raise HTTPException(status_code=400, detail="Unknown provider")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    return StreamingResponse(stream_chat(payload), media_type="text/plain")


@router.get("/edit-proposals", response_model=list[EditProposalDto])
async def get_proposals(workspace: str = Query(...)) -> list[EditProposalDto]:
    return await list_proposals(workspace)


@router.post("/edit-proposals", response_model=EditProposalDto)
async def propose_edit(payload: EditProposalRequest) -> EditProposalDto:
    from fastapi import HTTPException
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(payload.workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. File modifications are disabled.")
    return await create_proposal(payload)


@router.get("/edit-proposals/{proposal_id}", response_model=EditProposalDto)
async def read_proposal(proposal_id: str) -> EditProposalDto:
    return await get_proposal(proposal_id)


@router.post("/edit-proposals/{proposal_id}/apply", response_model=EditProposalDto)
async def approve_and_apply(proposal_id: str) -> EditProposalDto:
    from fastapi import HTTPException
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    proposal = await get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    trust = await get_workspace_trust(proposal.workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. File modifications are disabled.")
    return await apply_proposal(proposal_id)


class RejectProposalPayload(BaseModel):
    feedback: str | None = None

@router.post("/edit-proposals/{proposal_id}/reject", response_model=EditProposalDto)
async def reject_and_close(proposal_id: str, payload: RejectProposalPayload | None = None) -> EditProposalDto:
    feedback = payload.feedback if payload else None
    return await reject_proposal(proposal_id, feedback=feedback)


@router.post("/context")
async def get_context(payload: ContextRequest) -> dict:
    return await gather_context(
        payload.workspace,
        payload.active_path,
        payload.selection,
        payload.open_tabs,
        payload.query
    )


# ── Chat History Threading Endpoints ──────────────────────────────────────────

import json
from datetime import datetime, timezone
from backend.app.db.database import get_connection
from .schemas import ChatThreadDto, ThreadCreateRequest, ThreadRenameRequest, ChatMessageExtendedDto, MessageSyncRequest

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

@router.get("/threads", response_model=list[ChatThreadDto])
async def list_threads(workspace: str = Query(...)) -> list[ChatThreadDto]:
    db = await get_connection()
    try:
        cur = await db.execute(
            "SELECT * FROM chat_threads WHERE workspace = ? ORDER BY updated_at DESC",
            (workspace,),
        )
        rows = await cur.fetchall()
        return [
            ChatThreadDto(
                id=r["id"],
                workspace=r["workspace"],
                title=r["title"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]
    finally:
        await db.close()

@router.post("/threads", response_model=ChatThreadDto, status_code=201)
async def create_thread(payload: ThreadCreateRequest) -> ChatThreadDto:
    db = await get_connection()
    now = _now_iso()
    try:
        await db.execute(
            "INSERT INTO chat_threads (id, workspace, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (payload.id, payload.workspace, payload.title, now, now),
        )
        await db.commit()
        return ChatThreadDto(
            id=payload.id,
            workspace=payload.workspace,
            title=payload.title,
            created_at=now,
            updated_at=now,
        )
    finally:
        await db.close()

@router.put("/threads/{thread_id}", response_model=ChatThreadDto)
async def rename_thread(thread_id: str, payload: ThreadRenameRequest) -> ChatThreadDto:
    db = await get_connection()
    now = _now_iso()
    try:
        await db.execute(
            "UPDATE chat_threads SET title = ?, updated_at = ? WHERE id = ?",
            (payload.title, now, thread_id),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,))
        r = await cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Thread not found")
        return ChatThreadDto(
            id=r["id"],
            workspace=r["workspace"],
            title=r["title"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
    finally:
        await db.close()

@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str) -> dict:
    db = await get_connection()
    try:
        await db.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()

@router.get("/threads/{thread_id}/messages", response_model=list[ChatMessageExtendedDto])
async def load_messages(thread_id: str) -> list[ChatMessageExtendedDto]:
    db = await get_connection()
    try:
        cur = await db.execute(
            "SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY id ASC",
            (thread_id,),
        )
        rows = await cur.fetchall()
        return [
            ChatMessageExtendedDto(
                role=r["role"],
                content=r["content"],
                model=r["model"],
                attached_paths=json.loads(r["attached_paths"] or "[]"),
                created_at=r["created_at"],
            )
            for r in rows
        ]
    finally:
        await db.close()

@router.post("/threads/{thread_id}/messages")
async def sync_messages(thread_id: str, payload: MessageSyncRequest) -> dict:
    """Sync the full list of messages for a thread (handles edit/regenerate trashing)."""
    db = await get_connection()
    now = _now_iso()
    try:
        # Clear existing messages in the thread and overwrite
        await db.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
        for msg in payload.messages:
            await db.execute(
                """
                INSERT INTO chat_messages (thread_id, role, content, model, attached_paths, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    msg.role,
                    msg.content,
                    msg.model,
                    json.dumps(msg.attached_paths),
                    msg.created_at or now,
                ),
            )
        # Update thread's updated_at
        await db.execute(
            "UPDATE chat_threads SET updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
        await db.commit()
        return {"status": "synced"}
    finally:
        await db.close()
