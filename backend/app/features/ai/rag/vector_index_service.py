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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def init_vector_store(workspace: str) -> Collection:
    """
    Initialize persistent ChromaDB client pointing to <workspace>/.code_os/vector_index/.
    Returns the 'code_os_vector_index' collection.
    """
    norm_ws = _normalize_workspace_path(workspace)
    if norm_ws in _collections:
        return _collections[norm_ws]

    persist_dir = Path(norm_ws) / ".code_os" / "vector_index"
    persist_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(persist_dir))
    _clients[norm_ws] = client

    ef = _get_embedding_function()
    collection = client.get_or_create_collection(
        name="code_os_vector_index",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    _collections[norm_ws] = collection
    return collection


def _chunk_content(text: str, max_lines: int = 60, overlap_lines: int = 15) -> List[Tuple[str, str, int]]:
    """
    Split text into ~500-token segments with overlap.
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

    for chunk_text, line_range, chunk_idx in chunks:
        chunk_id = f"{rel_path}::chunk_{chunk_idx}"
        ids.append(chunk_id)
        documents.append(chunk_text)
        metadatas.append({
            "file_path": rel_path,
            "chunk_index": chunk_idx,
            "language": lang,
            "line_range": line_range,
            "workspace": norm_ws,
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
        "total_chunks": total_chunks,
        "last_indexed_at": now_iso,
    }
    _status_cache[norm_ws] = status
    return status


async def semantic_search(workspace: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Query ChromaDB for semantically similar code chunks, ranked by cosine similarity.
    Returns: [{ "file_path": str, "chunk_text": str, "score": float, "line_range": str, "language": str }]
    """
    if not query.strip():
        return []

    norm_ws = _normalize_workspace_path(workspace)
    collection = init_vector_store(norm_ws)

    count = collection.count()
    if count == 0:
        return []

    n_results = min(top_k, count)
    results = collection.query(
        query_texts=[query.strip()],
        n_results=n_results,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    output = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        # Cosine distance in Chroma: dist in [0.0, 2.0], cosine similarity = 1.0 - dist
        score = round(max(0.0, min(1.0, 1.0 - dist)), 4)
        output.append({
            "file_path": meta.get("file_path", ""),
            "chunk_text": doc,
            "score": score,
            "line_range": meta.get("line_range", ""),
            "language": meta.get("language", ""),
        })

    # Sort descending by score
    output.sort(key=lambda x: x["score"], reverse=True)
    return output


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


def schedule_rag_reindex(workspace: str, file_path: str, event_type: str = "modified") -> None:
    """
    Hook called from file_watcher to schedule rate-limited re-indexing of changed code files.
    """
    global _reindex_queue, _reindex_worker_task

    ext = Path(file_path).suffix.lower()
    if ext not in CODE_EXTENSIONS:
        return

    if _reindex_queue is None:
        _reindex_queue = asyncio.Queue()

    try:
        loop = asyncio.get_running_loop()
        if _reindex_worker_task is None or _reindex_worker_task.done():
            _reindex_worker_task = loop.create_task(_reindex_worker())
        _reindex_queue.put_nowait((workspace, file_path, event_type))
    except RuntimeError:
        pass
