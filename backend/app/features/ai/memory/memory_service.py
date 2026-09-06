"""
memory_service.py — AI Learns from Mistakes persistent memory and self-improvement feedback loop.

Provides:
- synthesize_lesson(raw_event, category) -> str (concise actionable guideline starting with Always/Never under 25 words)
- log_mistake(workspace, category, raw_event_or_lesson, source_event_id, confidence, lesson) -> dict
- get_relevant_memories(workspace, task_description, top_k) -> list[dict]
- increment_applied(memory_id) -> None
- decay_unused_memories(workspace, days_threshold, decay_rate) -> int
- boost_memory(memory_id, amount) -> dict
- delete_memory(memory_id) -> bool
- list_memories(workspace, category) -> list[dict]
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.api.models.Collection import Collection

from app.db.database import get_db
from app.features.ai.rag.vector_index_service import _get_embedding_function, _normalize_workspace_path

logger = logging.getLogger(__name__)

# Cache of ChromaDB clients and collections per workspace
_memory_clients: Dict[str, chromadb.PersistentClient] = {}
_memory_collections: Dict[str, Collection] = {}

VALID_CATEGORIES = frozenset({
    "rejected_edit",
    "failed_test",
    "repair_loop",
    "user_correction",
    "security_fix",
    "manual",
})


def _get_memory_collection(workspace: str) -> Optional[Collection]:
    """Retrieve or initialize the ChromaDB persistent collection for workspace memories."""
    try:
        norm_ws = _normalize_workspace_path(workspace)
        if norm_ws in _memory_collections:
            return _memory_collections[norm_ws]

        persist_dir = Path(norm_ws) / ".code_os" / "memory"
        persist_dir.mkdir(parents=True, exist_ok=True)

        client = chromadb.PersistentClient(path=str(persist_dir))
        _memory_clients[norm_ws] = client

        ef = _get_embedding_function()
        collection = client.get_or_create_collection(
            name="code_os_memories",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        _memory_collections[norm_ws] = collection
        return collection
    except Exception as exc:
        logger.warning("Could not initialize ChromaDB memory collection for %s: %s", workspace, exc)
        return None


def _format_concise_rule(text: str) -> str:
    """Format and truncate text to a crisp guideline starting with Always or Never under 25 words."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    # Strip quotes if wrapped
    cleaned = cleaned.strip("\"'#-* ")

    if not cleaned.lower().startswith("always") and not cleaned.lower().startswith("never"):
        cleaned = f"Always {cleaned}"

    # Capitalize first word properly
    if cleaned.lower().startswith("always"):
        cleaned = "Always" + cleaned[6:]
    elif cleaned.lower().startswith("never"):
        cleaned = "Never" + cleaned[5:]

    words = cleaned.split()
    if len(words) > 24:
        cleaned = " ".join(words[:24]) + "."
    elif not cleaned.endswith((".", "!", "?")):
        cleaned = cleaned + "."

    return cleaned


async def synthesize_lesson(raw_event: str, category: str = "manual") -> str:
    """
    Synthesizes a raw failure, rejected edit, or error event into a concise actionable guideline.
    Must start with 'Always' or 'Never' and be under 25 words.
    Uses LLM when available, with a reliable deterministic heuristic fallback.
    """
    raw_str = (raw_event or "").strip()

    # If the user already provided an Always/Never rule, format and return it directly
    if (raw_str.lower().startswith("always ") or raw_str.lower().startswith("never ")) and len(raw_str.split()) <= 25:
        return _format_concise_rule(raw_str)

    # 1. Attempt LLM synthesis if available
    try:
        from app.features.ai.service import provider_for
        from app.features.ai.schemas import ChatRequest, ChatMessage

        system_instruction = (
            "You are an AI continuous learning synthesizer. Given an agent mistake, test failure, "
            "or error event, summarize it into ONE actionable guideline for future coding tasks.\n"
            "STRICT RULES:\n"
            "1. MUST start with 'Always' or 'Never'.\n"
            "2. Under 25 words total.\n"
            "3. Actionable and concrete.\n"
            "4. Return ONLY the rule sentence, nothing else."
        )

        user_content = f"Category: {category}\nEvent Details:\n{raw_str[:1500]}"
        req = ChatRequest(
            messages=[
                ChatMessage(role="system", content=system_instruction),
                ChatMessage(role="user", content=user_content),
            ],
            model="gpt-4o-mini",
            provider="openai",
        )
        provider = await provider_for(req)
        tokens: List[str] = []
        async for tok in provider.stream_chat(req.model, req.messages, temperature=0.0):
            tokens.append(tok)
        llm_res = "".join(tokens).strip()
        if llm_res and (llm_res.lower().startswith("always") or llm_res.lower().startswith("never")):
            return _format_concise_rule(llm_res)
    except Exception as exc:
        logger.debug("LLM synthesis unavailable or failed, falling back to heuristic: %s", exc)

    # 2. Heuristic extraction based on category and event text
    cat = category.lower() if category in VALID_CATEGORIES else "manual"
    low_event = raw_str.lower()

    if cat == "rejected_edit":
        if "protected" in low_event:
            return "Never modify protected core files without explicit authorization."
        if "syntax" in low_event:
            return "Always verify syntax before proposing diff changes to codebase files."
        return "Always verify diff line alignments and test changes before proposing edits."

    if cat == "failed_test":
        if "assertionerror" in low_event or "assert" in low_event:
            # Extract assertion details if available
            match = re.search(r"assert\w*\s+([^,\n]+)", raw_str, re.IGNORECASE)
            if match:
                snippet = match.group(1).strip()[:40]
                return _format_concise_rule(f"Always verify condition {snippet} before concluding test execution.")
            return "Always ensure test assertions and expected return values match implementation specifications."
        if "typeerror" in low_event:
            return "Never pass mismatched parameter types; always validate type signatures and null checks."
        if "keyerror" in low_event or "indexerror" in low_event:
            return "Always check for key existence or bounds before indexing collections."
        return "Always run and pass unit tests locally before finalizing task implementations."

    if cat == "repair_loop":
        return "Never repeat identical failed patches; always diagnose root cause before attempting repair."

    if cat == "security_fix":
        if "sql" in low_event:
            return "Always use parameterized queries and avoid string interpolation in SQL statements."
        if "xss" in low_event:
            return "Never render raw unescaped user inputs directly into HTML or DOM templates."
        if "secret" in low_event or "token" in low_event or "key" in low_event:
            return "Never commit hardcoded API keys or secrets directly into repository files."
        return "Always validate and sanitize all untrusted inputs before processing or rendering."

    if cat == "user_correction":
        # Extract main guidance from user correction
        clean_msg = re.sub(r"^(please|agent|hey|you should)\s+", "", raw_str, flags=re.IGNORECASE).strip()
        return _format_concise_rule(f"Always {clean_msg}")

    # Default fallback
    return _format_concise_rule(raw_str or "Always verify code modifications against project specifications.")


async def log_mistake(
    workspace: str,
    category: str,
    raw_event_or_lesson: str,
    source_event_id: Optional[str] = None,
    confidence: int = 100,
    lesson: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Persists a mistake/lesson in SQLite and the ChromaDB workspace collection.
    """
    if category not in VALID_CATEGORIES:
        category = "manual"

    norm_ws = _normalize_workspace_path(workspace)
    confidence = max(0, min(100, int(confidence)))

    if not lesson:
        lesson = await synthesize_lesson(raw_event_or_lesson, category=category)

    mem_id = f"mem_{uuid.uuid4().hex[:12]}"
    now_ts = datetime.now(timezone.utc).isoformat()

    db = await get_db()
    await db.execute(
        """
        INSERT INTO agent_memories (id, workspace, category, lesson, source_event_id, confidence, times_applied, created_at, last_applied_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL)
        """,
        (mem_id, norm_ws, category, lesson, source_event_id, confidence, now_ts),
    )
    await db.commit()

    # ChromaDB indexing
    try:
        coll = _get_memory_collection(norm_ws)
        if coll is not None:
            coll.upsert(
                ids=[mem_id],
                documents=[lesson],
                metadatas=[{
                    "workspace": norm_ws,
                    "category": category,
                    "confidence": confidence,
                    "source_event_id": source_event_id or "",
                }],
            )
    except Exception as exc:
        logger.warning("Failed to index memory %s in ChromaDB: %s", mem_id, exc)

    return {
        "id": mem_id,
        "workspace": norm_ws,
        "category": category,
        "lesson": lesson,
        "source_event_id": source_event_id,
        "confidence": confidence,
        "times_applied": 0,
        "created_at": now_ts,
        "last_applied_at": None,
    }


async def get_relevant_memories(
    workspace: str,
    task_description: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Retrieves the most semantically relevant lessons learned for a task.
    Queries ChromaDB vector collection with fallback to SQLite ranking.
    Excludes memories with confidence <= 0.
    """
    norm_ws = _normalize_workspace_path(workspace)
    matched_ids: List[str] = []

    # 1. Try vector similarity query
    task_text = (task_description or "").strip()
    if task_text:
        try:
            coll = _get_memory_collection(norm_ws)
            if coll is not None and coll.count() > 0:
                n = min(top_k * 2, coll.count())
                results = coll.query(
                    query_texts=[task_text],
                    n_results=n,
                )
                if results and "ids" in results and results["ids"] and results["ids"][0]:
                    matched_ids = [str(i) for i in results["ids"][0]]
        except Exception as exc:
            logger.debug("Chroma query failed, falling back to SQL: %s", exc)

    db = await get_db()
    memories: List[Dict[str, Any]] = []

    if matched_ids:
        # Fetch from DB preserving matched order
        placeholders = ",".join("?" for _ in matched_ids)
        query = f"""
            SELECT * FROM agent_memories
            WHERE workspace = ? AND id IN ({placeholders}) AND confidence > 0
        """
        cursor = await db.execute(query, [norm_ws] + matched_ids)
        rows = await cursor.fetchall()
        row_map = {r["id"]: dict(r) for r in rows}
        for mid in matched_ids:
            if mid in row_map and len(memories) < top_k:
                memories.append(row_map[mid])

    # 2. If vector search yielded fewer than top_k, supplement with highest-confidence lessons
    if len(memories) < top_k:
        existing_ids = {m["id"] for m in memories}
        needed = top_k - len(memories)
        if existing_ids:
            ex_placeholders = ",".join("?" for _ in existing_ids)
            query = f"""
                SELECT * FROM agent_memories
                WHERE workspace = ? AND confidence > 0 AND id NOT IN ({ex_placeholders})
                ORDER BY confidence DESC, times_applied DESC, created_at DESC
                LIMIT ?
            """
            cursor = await db.execute(query, [norm_ws] + list(existing_ids) + [needed])
        else:
            query = """
                SELECT * FROM agent_memories
                WHERE workspace = ? AND confidence > 0
                ORDER BY confidence DESC, times_applied DESC, created_at DESC
                LIMIT ?
            """
            cursor = await db.execute(query, (norm_ws, needed))

        supp_rows = await cursor.fetchall()
        for r in supp_rows:
            memories.append(dict(r))

    return memories[:top_k]


async def increment_applied(memory_id: str) -> None:
    """Increment times_applied count and update last_applied_at timestamp."""
    db = await get_db()
    now_ts = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        UPDATE agent_memories
        SET times_applied = times_applied + 1, last_applied_at = ?
        WHERE id = ?
        """,
        (now_ts, memory_id),
    )
    await db.commit()


async def decay_unused_memories(
    workspace: str,
    days_threshold: int = 30,
    decay_rate: int = 5,
) -> int:
    """
    Decays confidence by `decay_rate` for memories unapplied for more than `days_threshold` days.
    Returns number of decayed records.
    """
    norm_ws = _normalize_workspace_path(workspace)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_threshold)).isoformat()

    db = await get_db()
    # Find candidate IDs
    cursor = await db.execute(
        """
        SELECT id FROM agent_memories
        WHERE workspace = ?
          AND confidence > 0
          AND (
            (last_applied_at IS NOT NULL AND last_applied_at < ?)
            OR (last_applied_at IS NULL AND created_at < ?)
          )
        """,
        (norm_ws, cutoff, cutoff),
    )
    rows = await cursor.fetchall()
    if not rows:
        return 0

    ids = [r["id"] for r in rows]
    placeholders = ",".join("?" for _ in ids)
    await db.execute(
        f"""
        UPDATE agent_memories
        SET confidence = MAX(0, confidence - ?)
        WHERE id IN ({placeholders})
        """,
        [decay_rate] + ids,
    )
    await db.commit()
    return len(ids)


async def boost_memory(memory_id: str, amount: int = 10) -> Optional[Dict[str, Any]]:
    """Increase memory confidence up to max 100%."""
    db = await get_db()
    await db.execute(
        """
        UPDATE agent_memories
        SET confidence = MIN(100, confidence + ?)
        WHERE id = ?
        """,
        (amount, memory_id),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM agent_memories WHERE id = ?", (memory_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    return dict(row)


async def delete_memory(memory_id: str) -> bool:
    """Delete a memory from SQLite and ChromaDB."""
    db = await get_db()
    cursor = await db.execute("SELECT workspace FROM agent_memories WHERE id = ?", (memory_id,))
    row = await cursor.fetchone()
    if not row:
        return False

    ws = row["workspace"]
    await db.execute("DELETE FROM agent_memories WHERE id = ?", (memory_id,))
    await db.commit()

    try:
        coll = _get_memory_collection(ws)
        if coll is not None:
            coll.delete(ids=[memory_id])
    except Exception as exc:
        logger.debug("Failed to delete memory %s from ChromaDB: %s", memory_id, exc)

    return True


async def list_memories(
    workspace: str,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List memories for a workspace, optionally filtered by category, sorted by confidence."""
    norm_ws = _normalize_workspace_path(workspace)
    db = await get_db()

    if category and category.lower() != "all" and category in VALID_CATEGORIES:
        cursor = await db.execute(
            """
            SELECT * FROM agent_memories
            WHERE workspace = ? AND category = ?
            ORDER BY confidence DESC, created_at DESC
            """,
            (norm_ws, category),
        )
    else:
        cursor = await db.execute(
            """
            SELECT * FROM agent_memories
            WHERE workspace = ?
            ORDER BY confidence DESC, created_at DESC
            """,
            (norm_ws,),
        )

    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
