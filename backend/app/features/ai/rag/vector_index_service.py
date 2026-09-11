"""
vector_index_service.py — Local semantic vector database indexing service using ChromaDB.

Indexes codebase into ~500-token overlapping chunks, generates embeddings using
offline models (all-MiniLM-L6-v2), and provides cosine-similarity semantic search,
incremental file indexing, file context retrieval, and rate-limited auto-indexing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

# Supported code extensions
CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cc", ".cxx",
    ".h", ".hpp", ".go", ".rs", ".rb", ".php", ".html", ".css", ".md",
})

# Ignored directory names during scanning
IGNORED_DIRS = frozenset({
    "node_modules", ".git", ".code_os", "__pycache__", ".pytest_cache",
    ".venv", "venv", "dist", "build", ".next", ".husky", "coverage", ".turbo",
})

# Language mapping by extension
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
}

# In-memory caches for persistent clients, collections, and status
_clients: Dict[str, chromadb.PersistentClient] = {}
_collections: Dict[str, Collection] = {}
_status_cache: Dict[str, Dict[str, Any]] = {}
_embedding_fn = None
_reindex_queue: asyncio.Queue[Tuple[str, str, str]] | None = None
_reindex_worker_task: asyncio.Task | None = None
_last_reindex_time: float = 0.0
_custom_reranker: Optional[Callable[[str, List[Dict[str, Any]]], List[Dict[str, Any]]]] = None


def _get_embedding_function():
    """Obtain offline local embedding function (all-MiniLM-L6-v2)."""
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn

    # 1. Try sentence-transformers if available
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        _embedding_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        logger.info("Using SentenceTransformerEmbeddingFunction(all-MiniLM-L6-v2)")
        return _embedding_fn
    except Exception:
        pass

    # 2. Fall back to ChromaDB's built-in ONNX DefaultEmbeddingFunction
    try:
        _embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        logger.info("Using ChromaDB DefaultEmbeddingFunction(all-MiniLM-L6-v2 ONNX)")
        return _embedding_fn
    except Exception as exc:
        logger.warning("Falling back to dummy embedding function: %s", exc)

    # 3. Fallback dummy function for constrained test environments
    class SimpleEmbeddingFunction(embedding_functions.EmbeddingFunction):
        def __call__(self, input_texts: List[str]) -> List[List[float]]:
            res = []
            for text in input_texts:
                vec = [float(ord(c) % 32) for c in text[:384]]
                if len(vec) < 384:
                    vec.extend([0.0] * (384 - len(vec)))
                res.append(vec)
            return res

    _embedding_fn = SimpleEmbeddingFunction()
    return _embedding_fn


def _normalize_workspace_path(workspace: str) -> str:
    return str(Path(workspace).resolve()).replace("\\", "/")


def _get_relative_path(workspace: str, file_path: str) -> str:
    norm_ws = Path(_normalize_workspace_path(workspace))
    raw_p = Path(file_path)
    if raw_p.is_absolute():
        try:
            return str(raw_p.resolve().relative_to(norm_ws)).replace("\\", "/")
        except ValueError:
            return str(raw_p).replace("\\", "/")
    return str(raw_p).replace("\\", "/")


def init_vector_store(workspace: str, collection_name: str = "codebase_rag") -> Collection:
    """
    Initialize persistent ChromaDB client pointing to <workspace>/.code_os/vector_index/.
    Returns the 'codebase_rag' collection (or specified collection_name).
    """
    norm_ws = _normalize_workspace_path(workspace)
    cache_key = f"{norm_ws}::{collection_name}"
    if cache_key in _collections:
        return _collections[cache_key]

    persist_dir = Path(norm_ws) / ".code_os" / "vector_index"
    persist_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(persist_dir))
    _clients[norm_ws] = client

    ef = _get_embedding_function()
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    _collections[cache_key] = collection
    return collection


def close_vector_store(workspace: Optional[str] = None) -> None:
    """Close and evict ChromaDB PersistentClient and Collection references to release file locks on Windows."""
    global _clients, _collections
    if workspace:
        norm_ws = _normalize_workspace_path(workspace)
        col_keys = [k for k in _collections if k.startswith(f"{norm_ws}::")]
        for k in col_keys:
            _collections.pop(k, None)
        _clients.pop(norm_ws, None)
    else:
        _collections.clear()
        _clients.clear()


def _extract_symbols(text: str) -> str:
    """Extract symbol definitions (functions, classes, variables) from text."""
    symbols = set()
    patterns = [
        r"(?:def|class|function|interface|type|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?:const|let|var|val)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
    ]
    for pat in patterns:
        for match in re.finditer(pat, text):
            symbols.add(match.group(1))
    return ",".join(sorted(symbols))


def _chunk_content(text: str, max_lines: int = 200, overlap_lines: int = 50) -> List[Tuple[str, str, int]]:
    """
    Split text into overlapping line chunks (~200 lines, 50-line overlap).
    Returns list of (chunk_text, line_range_str, chunk_index).
    """
    if not text.strip():
        return []

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    if total_lines <= max_lines:
        return [(text, f"1-{max(1, total_lines)}", 0)]

    chunks = []
    start = 0
    chunk_idx = 0

    while start < total_lines:
        end = min(start + max_lines, total_lines)
        chunk_slice = "".join(lines[start:end])
        line_range = f"{start + 1}-{end}"
        chunks.append((chunk_slice, line_range, chunk_idx))
        chunk_idx += 1

        if end >= total_lines:
            break
        start += max(1, max_lines - overlap_lines)

    return chunks


async def index_file(workspace: str, file_path: str) -> int:
    """
    Index a single file (for incremental updates).
    Deletes existing chunks for file_path, splits file into chunks, and stores in ChromaDB.
    Returns number of chunks indexed.
    """
    norm_ws = _normalize_workspace_path(workspace)
    collection = init_vector_store(norm_ws)
    rel_path = _get_relative_path(norm_ws, file_path)

    # 1. Delete existing chunks for this file
    try:
        collection.delete(where={"file_path": rel_path})
    except Exception as exc:
        logger.debug("index_file: delete previous chunks failed/empty: %s", exc)

    full_p = Path(norm_ws) / rel_path
    if not full_p.is_file():
        return 0

    ext = full_p.suffix.lower()
    if ext not in CODE_EXTENSIONS:
        return 0

    # 2. Read file
    try:
        text = full_p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = full_p.read_text(encoding="latin-1")
        except Exception:
            return 0
    except Exception:
        return 0

    chunks = _chunk_content(text)
    if not chunks:
        return 0

    lang = LANGUAGE_MAP.get(ext, "text")

    ids = []
    documents = []
    metadatas = []
    try:
        mtime = full_p.stat().st_mtime
    except Exception:
        mtime = time.time()

    for chunk_text, line_range, chunk_idx in chunks:
        chunk_id = f"{rel_path}::chunk_{chunk_idx}"
        symbols = _extract_symbols(chunk_text)
        ids.append(chunk_id)
        documents.append(chunk_text)
        metadatas.append({
            "file_path": rel_path,
            "chunk_index": chunk_idx,
            "language": lang,
            "line_range": line_range,
            "symbols": symbols,
            "workspace": norm_ws,
            "mtime": mtime,
        })

    # 3. Upsert to ChromaDB
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(chunks)


async def remove_file(workspace: str, file_path: str) -> bool:
    """Remove a file's chunks from the vector index."""
    norm_ws = _normalize_workspace_path(workspace)
    collection = init_vector_store(norm_ws)
    rel_path = _get_relative_path(norm_ws, file_path)
    try:
        collection.delete(where={"file_path": rel_path})
        return True
    except Exception as exc:
        logger.warning("remove_file failed for %s: %s", rel_path, exc)
        return False


async def index_workspace(workspace: str) -> Dict[str, Any]:
    """
    Scan all code files in workspace and store chunks in ChromaDB.
    Returns status: { "indexed_files": int, "total_chunks": int, "last_indexed_at": str }.
    """
    norm_ws = _normalize_workspace_path(workspace)
    ws_path = Path(norm_ws)
    if not ws_path.is_dir():
        return {"indexed_files": 0, "total_chunks": 0, "last_indexed_at": None}

    # Reset / get collection
    collection = init_vector_store(norm_ws)

    # Collect matching files
    files_to_index: List[Path] = []
    for root, dirs, files in os.walk(ws_path):
        # Exclude ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in CODE_EXTENSIONS:
                files_to_index.append(p)

    total_chunks = 0
    indexed_files = 0

    for file_p in files_to_index:
        chunks_count = await index_file(norm_ws, str(file_p))
        if chunks_count > 0:
            indexed_files += 1
            total_chunks += chunks_count

    now_iso = datetime.now(timezone.utc).isoformat()
    status = {
        "indexed_files": indexed_files,
        "files_indexed": indexed_files,
        "total_chunks": total_chunks,
        "last_indexed_at": now_iso,
    }
    _status_cache[norm_ws] = status
    return status


def set_reranker(reranker_fn: Optional[Callable[[str, List[Dict[str, Any]]], List[Dict[str, Any]]]]) -> None:
    """Set custom reranker for testing or model swapping."""
    global _custom_reranker
    _custom_reranker = reranker_fn


def reset_reranker() -> None:
    """Reset custom reranker."""
    global _custom_reranker
    _custom_reranker = None


def _keyword_search_chunks(collection: Collection, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Keyword and symbol overlap matching across indexed chunks in ChromaDB.
    Returns list of chunks ranked by keyword overlap score (0.0 to 1.0).
    """
    if not query.strip():
        return []

    tokens = [t.lower() for t in re.findall(r"\b[A-Za-z0-9_$]+\b", query) if len(t) > 1]
    if not tokens:
        return []

    try:
        data = collection.get(include=["documents", "metadatas"])
    except Exception as exc:
        logger.debug("keyword search collection.get error: %s", exc)
        return []

    docs = data.get("documents", []) or []
    metas = data.get("metadatas", []) or []
    if not docs:
        return []

    scored_chunks = []
    for doc, meta in zip(docs, metas):
        if not doc:
            continue
        doc_lower = doc.lower()
        meta_symbols = (meta.get("symbols", "") or "").lower().split(",")
        meta_symbols_set = {s.strip() for s in meta_symbols if s.strip()}

        # 1. Symbol matching
        symbol_hits = sum(1 for t in tokens if t in meta_symbols_set)
        symbol_score = min(1.0, symbol_hits / max(1, len(tokens)))

        # 2. Token overlap matching in chunk text
        token_hits = sum(1 for t in tokens if t in doc_lower)
        token_score = min(1.0, token_hits / max(1, len(tokens)))

        # Combined keyword score (60% symbol, 40% text overlap)
        kw_score = round(0.6 * symbol_score + 0.4 * token_score, 4)
        if kw_score > 0:
            scored_chunks.append({
                "file_path": meta.get("file_path", ""),
                "relative_path": meta.get("file_path", ""),
                "path": meta.get("file_path", ""),
                "chunk_text": doc,
                "content": doc,
                "score": kw_score,
                "keyword_score": kw_score,
                "semantic_score": 0.0,
                "line_range": meta.get("line_range", ""),
                "symbols": meta.get("symbols", ""),
                "language": meta.get("language", ""),
                "chunk_index": meta.get("chunk_index", 0),
            })

    scored_chunks.sort(key=lambda x: x["keyword_score"], reverse=True)
    return scored_chunks[:top_k]


def _merge_hybrid_scores(
    semantic_results: List[Dict[str, Any]],
    keyword_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merge semantic (70%) and keyword (30%) results by (file_path, chunk_index).
    Formula: score = 0.70 * semantic_score + 0.30 * keyword_score.
    """
    merged: Dict[Tuple[str, int], Dict[str, Any]] = {}

    for s_item in semantic_results:
        key = (s_item.get("file_path", ""), s_item.get("chunk_index", 0))
        item = dict(s_item)
        item["semantic_score"] = s_item.get("score", 0.0)
        item["keyword_score"] = 0.0
        merged[key] = item

    for k_item in keyword_results:
        key = (k_item.get("file_path", ""), k_item.get("chunk_index", 0))
        kw_s = k_item.get("keyword_score", k_item.get("score", 0.0))
        if key in merged:
            merged[key]["keyword_score"] = kw_s
        else:
            item = dict(k_item)
            item["semantic_score"] = 0.0
            item["keyword_score"] = kw_s
            merged[key] = item

    results = []
    for item in merged.values():
        sem = item.get("semantic_score", 0.0)
        kw = item.get("keyword_score", 0.0)
        final_score = round(0.70 * sem + 0.30 * kw, 4)
        item["score"] = final_score
        item["similarity_score"] = final_score
        results.append(item)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _rerank_chunks(query: str, candidates: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Rerank top candidates using cross-encoder for top-5 precision.
    Supports injected custom reranker (test/mock), sentence-transformers CrossEncoder,
    or deterministic cross-scoring fallback.
    """
    if not candidates:
        return []

    global _custom_reranker
    if _custom_reranker is not None:
        reranked = _custom_reranker(query, candidates)
        return reranked[:top_k]

    # Try sentence-transformers CrossEncoder if available
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        pairs = [(query, c.get("chunk_text", "")) for c in candidates]
        scores = model.predict(pairs)
        for cand, score in zip(candidates, scores):
            cand["rerank_score"] = float(score)
            cand["score"] = round(float(score), 4)
        candidates.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return candidates[:top_k]
    except Exception:
        pass

    # Deterministic fallback: cross-feature alignment
    q_tokens = set(re.findall(r"\b\w+\b", query.lower()))
    for cand in candidates:
        text = (cand.get("chunk_text", "")).lower()
        symbols = (cand.get("symbols", "")).lower()
        sym_match_count = sum(1 for t in q_tokens if t in symbols)
        exact_phrase_bonus = 0.2 if query.lower() in text else 0.0
        raw_score = cand.get("score", 0.0)
        boosted = raw_score + (0.15 * sym_match_count / max(1, len(q_tokens))) + exact_phrase_bonus
        cand["rerank_score"] = round(boosted, 4)

    candidates.sort(key=lambda x: x.get("rerank_score", x.get("score", 0.0)), reverse=True)
    return candidates[:top_k]


async def semantic_search(
    workspace: str,
    query: str,
    top_k: int = 5,
    limit: Optional[int] = None,
    use_semantic: Optional[bool] = None,
    collection_name: str = "codebase_rag",
) -> List[Dict[str, Any]]:
    """
    Hybrid semantic code search combining ChromaDB MiniLM-L6-v2 embeddings (70%)
    and keyword/symbol overlap (30%) with cross-encoder reranking.
    When use_semantic is False, falls back to keyword-only retrieval.
    """
    if not query.strip():
        return []

    target_k = limit if limit is not None else top_k

    if use_semantic is None:
        try:
            from app.core.config import get_settings
            use_semantic = get_settings().use_semantic_rag
        except Exception:
            use_semantic = True

    norm_ws = _normalize_workspace_path(workspace)
    collection = init_vector_store(norm_ws, collection_name=collection_name)

    count = collection.count()
    if count == 0:
        return []

    # 1. Keyword path (top 10)
    keyword_matches = _keyword_search_chunks(collection, query, top_k=10)

    # 2. If semantic is disabled (settings toggle), return keyword-only
    if not use_semantic:
        for km in keyword_matches:
            km["score"] = km.get("keyword_score", 0.0)
        return keyword_matches[:target_k]

    # 3. Semantic path: ChromaDB cosine similarity (top 10)
    n_results = min(10, count)
    results = collection.query(
        query_texts=[query.strip()],
        n_results=n_results,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    semantic_matches = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        # Chroma cosine distance in [0.0, 2.0], cosine similarity = 1.0 - dist
        score = round(max(0.0, min(1.0, 1.0 - dist)), 4)
        semantic_matches.append({
            "file_path": meta.get("file_path", ""),
            "relative_path": meta.get("file_path", ""),
            "path": meta.get("file_path", ""),
            "chunk_text": doc,
            "content": doc,
            "score": score,
            "semantic_score": score,
            "keyword_score": 0.0,
            "line_range": meta.get("line_range", ""),
            "symbols": meta.get("symbols", ""),
            "language": meta.get("language", ""),
            "chunk_index": meta.get("chunk_index", 0),
        })

    # 4. Merge scores (70% semantic + 30% keyword)
    merged_candidates = _merge_hybrid_scores(semantic_matches, keyword_matches)

    # 5. Cross-encoder reranking down to target_k
    final_results = _rerank_chunks(query, merged_candidates, top_k=target_k)
    return final_results


async def get_file_context(workspace: str, file_path: str) -> List[Dict[str, Any]]:
    """
    Retrieve all indexed chunks for a file (for 'explain this file' queries),
    sorted by chunk_index.
    """
    norm_ws = _normalize_workspace_path(workspace)
    collection = init_vector_store(norm_ws)
    rel_path = _get_relative_path(norm_ws, file_path)

    try:
        res = collection.get(where={"file_path": rel_path})
    except Exception as exc:
        logger.debug("get_file_context error: %s", exc)
        return []

    docs = res.get("documents", [])
    metas = res.get("metadatas", [])

    items = []
    for doc, meta in zip(docs, metas):
        items.append({
            "file_path": meta.get("file_path", rel_path),
            "chunk_text": doc,
            "line_range": meta.get("line_range", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "language": meta.get("language", ""),
        })

    items.sort(key=lambda x: x["chunk_index"])
    return items


async def get_indexing_status(workspace: str) -> Dict[str, Any]:
    """Return status of vector index for workspace."""
    norm_ws = _normalize_workspace_path(workspace)
    if norm_ws in _status_cache:
        return _status_cache[norm_ws]

    # Inspect collection count
    try:
        collection = init_vector_store(norm_ws)
        total_chunks = collection.count()
        # Retrieve unique file paths if chunks exist
        indexed_files = 0
        if total_chunks > 0:
            res = collection.get()
            unique_files = {m.get("file_path") for m in res.get("metadatas", []) if m.get("file_path")}
            indexed_files = len(unique_files)
        status = {
            "indexed_files": indexed_files,
            "total_chunks": total_chunks,
            "last_indexed_at": None,
        }
    except Exception:
        status = {"indexed_files": 0, "total_chunks": 0, "last_indexed_at": None}

    _status_cache[norm_ws] = status
    return status


# ── Auto-indexing Rate-Limited Queue ──────────────────────────────────────────

async def _reindex_worker():
    """Background worker processing file change events with max 1 file per 2 seconds."""
    global _last_reindex_time
    while True:
        try:
            workspace, file_path, event_type = await _reindex_queue.get()
            now = time.time()
            elapsed = now - _last_reindex_time
            if elapsed < 2.0:
                await asyncio.sleep(2.0 - elapsed)

            if event_type == "deleted":
                await remove_file(workspace, file_path)
            else:
                await index_file(workspace, file_path)

            _last_reindex_time = time.time()
            _reindex_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Error in reindex worker: %s", exc)


def schedule_rag_reindex(
    workspace: str,
    file_path: str,
    event_type: str = "modified",
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> None:
    """
    Hook called from file_watcher or background threads to schedule rate-limited re-indexing of changed code files.
    """
    global _reindex_queue, _reindex_worker_task

    ext = Path(file_path).suffix.lower()
    if ext not in CODE_EXTENSIONS:
        return

    # Determine the target asyncio event loop
    target_loop = loop
    if target_loop is None or not target_loop.is_running():
        try:
            target_loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                target_loop = asyncio.get_event_loop()
            except RuntimeError:
                target_loop = None

    if target_loop is None or not target_loop.is_running():
        logger.debug("schedule_rag_reindex: no active event loop available to schedule reindex of %s", file_path)
        return

    def _enqueue():
        global _reindex_queue, _reindex_worker_task
        if _reindex_queue is None:
            _reindex_queue = asyncio.Queue()
        if _reindex_worker_task is None or _reindex_worker_task.done():
            _reindex_worker_task = target_loop.create_task(_reindex_worker())
        _reindex_queue.put_nowait((workspace, file_path, event_type))

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is target_loop:
        _enqueue()
    else:
        target_loop.call_soon_threadsafe(_enqueue)


async def reindex_workspace_now(workspace: str) -> Dict[str, Any]:
    """
    Manual, immediately-executed reindexing of all workspace files with visible logging.
    """
    logger.info("reindex_workspace_now: starting manual full reindex for workspace '%s'", workspace)
    status = await index_workspace(workspace)
    logger.info(
        "reindex_workspace_now: manual reindex complete for '%s' — %d files indexed, %d total chunks",
        workspace,
        status.get("files_indexed", 0),
        status.get("total_chunks", 0),
    )
    return status


async def reconcile_workspace_index(workspace: str, loop: Optional[asyncio.AbstractEventLoop] = None) -> Dict[str, Any]:
    """
    Reconcile pre-existing workspace files with codebase_rag ChromaDB index.
    Diffs disk files (path + mtime) against collection metadata:
    - Indexes missing files.
    - Re-indexes modified files.
    - Removes deleted files.
    """
    norm_ws = _normalize_workspace_path(workspace)
    ws_path = Path(norm_ws)
    if not ws_path.is_dir():
        return {"workspace": norm_ws, "files_indexed": 0, "total_chunks": 0, "missing_files_sample": []}

    collection = init_vector_store(norm_ws)

    # Retrieve current collection metadata
    existing_file_meta: Dict[str, float] = {}
    try:
        data = collection.get(include=["metadatas"])
        for meta in data.get("metadatas") or []:
            fp = meta.get("file_path")
            if fp:
                mt = float(meta.get("mtime") or 0.0)
                existing_file_meta[fp] = max(existing_file_meta.get(fp, 0.0), mt)
    except Exception as exc:
        logger.debug("reconcile_workspace_index: failed to load existing metadatas: %s", exc)

    # Scan disk files
    disk_files: Dict[str, Path] = {}
    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in CODE_EXTENSIONS:
                rel_p = _get_relative_path(norm_ws, str(p))
                disk_files[rel_p] = p

    missing_or_modified: List[Tuple[str, Path]] = []
    for rel_p, p in disk_files.items():
        if rel_p not in existing_file_meta:
            missing_or_modified.append((rel_p, p))
        else:
            try:
                disk_mtime = p.stat().st_mtime
                if disk_mtime > existing_file_meta[rel_p] + 1e-3:
                    missing_or_modified.append((rel_p, p))
            except Exception:
                pass

    # Deleted files to prune
    deleted_files = [fp for fp in existing_file_meta if fp not in disk_files]
    for df in deleted_files:
        try:
            await remove_file(norm_ws, df)
        except Exception as exc:
            logger.debug("reconcile_workspace_index: error removing deleted file %s: %s", df, exc)

    # Index missing or modified
    files_indexed = 0
    total_new_chunks = 0
    for rel_p, p in missing_or_modified:
        try:
            chunks = await index_file(norm_ws, str(p))
            if chunks > 0:
                files_indexed += 1
                total_new_chunks += chunks
        except Exception as exc:
            logger.warning("reconcile_workspace_index: failed to index %s: %s", rel_p, exc)

    chunk_cnt = collection.count()
    now_iso = datetime.now(timezone.utc).isoformat()
    status = {
        "workspace": norm_ws,
        "files_indexed": files_indexed,
        "files_reconciled": len(missing_or_modified),
        "files_removed": len(deleted_files),
        "total_chunks": chunk_cnt,
        "last_indexed_at": now_iso,
    }
    _status_cache[norm_ws] = status
    logger.info(
        "reconcile_workspace_index: completed for '%s' — %d new/updated files indexed, %d removed, %d total chunks",
        norm_ws, files_indexed, len(deleted_files), chunk_cnt
    )
    return status


async def get_rag_stats(workspace: str) -> Dict[str, Any]:
    """
    Diagnostic endpoint handler for GET /api/rag/stats?workspace=...
    Returns {
        "indexed_files": list[str],
        "chunk_count": int,
        "last_index_at": float | str | None,
        "missing_files_sample": list[str]
    }
    """
    norm_ws = _normalize_workspace_path(workspace)
    ws_path = Path(norm_ws)
    if not ws_path.is_dir():
        return {
            "indexed_files": [],
            "chunk_count": 0,
            "last_index_at": None,
            "missing_files_sample": [],
        }

    collection = init_vector_store(norm_ws)
    indexed_files: set[str] = set()
    last_mtime: float | None = None

    try:
        data = collection.get(include=["metadatas"])
        for m in data.get("metadatas") or []:
            fp = m.get("file_path")
            if fp:
                indexed_files.add(fp)
            mt = m.get("mtime")
            if mt is not None:
                try:
                    last_mtime = max(last_mtime or 0.0, float(mt))
                except (ValueError, TypeError):
                    pass
    except Exception as exc:
        logger.warning("get_rag_stats: error querying collection: %s", exc)

    # Disk scan for missing files sample
    missing_files: list[str] = []
    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in CODE_EXTENSIONS:
                rel_p = _get_relative_path(norm_ws, str(p))
                if rel_p not in indexed_files:
                    missing_files.append(rel_p)
                    if len(missing_files) >= 10:
                        break
        if len(missing_files) >= 10:
            break

    cached_status = _status_cache.get(norm_ws, {})
    last_index_at = cached_status.get("last_indexed_at") or (last_mtime if last_mtime else None)

    return {
        "indexed_files": sorted(list(indexed_files)),
        "chunk_count": collection.count(),
        "last_index_at": last_index_at,
        "missing_files_sample": missing_files[:10],
    }

