"""service.py — File ingestion and extraction service for Code-OS.

Extracts text, structure, and metadata from PDFs, images (with OCR fallback),
code files, data files, and text files. Stores files locally in
<workspace>/.code_os/uploads/ with UUID naming.
"""
from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Try importing PyMuPDF (fitz)
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    fitz = None  # type: ignore
    PYMUPDF_AVAILABLE = False

# Try importing Pillow
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore
    PILLOW_AVAILABLE = False

# Try importing pytesseract
try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None  # type: ignore
    PYTESSERACT_AVAILABLE = False

# Try importing python-magic
try:
    import magic
    MAGIC_AVAILABLE = True
except Exception:
    magic = None  # type: ignore
    MAGIC_AVAILABLE = False


# Supported extensions by category
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cc", ".cxx",
    ".h", ".hpp", ".go", ".rs", ".rb", ".php", ".html", ".css", ".scss", ".less",
    ".md", ".markdown", ".sh", ".bash", ".zsh", ".bat", ".ps1", ".sql", ".cs",
    ".swift", ".kt", ".scala", ".lua", ".r", ".dart", ".vue", ".svelte"
}

DATA_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".xml", ".csv", ".tsv", ".toml", ".ini", ".env"
}

TEXT_EXTENSIONS = {
    ".txt", ".log", ".text", ".diff", ".patch"
}

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"
}

PDF_EXTENSIONS = {
    ".pdf"
}

SUPPORTED_EXTENSIONS = (
    PDF_EXTENSIONS | IMAGE_EXTENSIONS | CODE_EXTENSIONS | DATA_EXTENSIONS | TEXT_EXTENSIONS
)


def detect_mime_type(file_bytes: bytes, filename: str, fallback_mime: Optional[str] = None) -> str:
    """Detect file MIME type using python-magic, mimetypes, or extension mapping."""
    if fallback_mime and "/" in fallback_mime and fallback_mime != "application/octet-stream":
        return fallback_mime

    ext = Path(filename).suffix.lower()
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed

    if MAGIC_AVAILABLE and magic is not None and file_bytes:
        try:
            detected = magic.from_buffer(file_bytes[:2048], mime=True)
            if detected:
                return detected
        except Exception as exc:
            logger.debug("magic detection error: %s", exc)

    # Extension-based fallbacks
    if ext == ".pdf":
        return "application/pdf"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        return f"image/{ext.lstrip('.')}"
    if ext == ".json":
        return "application/json"
    if ext in {".yaml", ".yml"}:
        return "application/x-yaml"
    if ext == ".xml":
        return "application/xml"
    if ext == ".csv":
        return "text/csv"
    if ext in CODE_EXTENSIONS:
        return "text/x-code"
    if ext in TEXT_EXTENSIONS:
        return "text/plain"

    return "application/octet-stream"


def ingest_file(
    file_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
    image_rel_path: Optional[str] = None,
) -> dict[str, Any]:
    """Ingest file bytes and extract text content, metadata, and page/word counts.

    Returns:
        {
            "content": str,
            "metadata": {
                "filename": str,
                "size_bytes": int,
                "mime_type": str,
                "page_count": int | None,
                "word_count": int,
                "extracted_at": str (ISO)
            },
            "error": str | None
        }
    """
    ext = Path(filename).suffix.lower()
    effective_mime = detect_mime_type(file_bytes, filename, mime_type)
    extracted_at = datetime.now(timezone.utc).isoformat()
    size_bytes = len(file_bytes)

    # Check for unsupported extensions
    if ext not in SUPPORTED_EXTENSIONS and not effective_mime.startswith(("text/", "image/", "application/pdf", "application/json")):
        error_msg = f"Unsupported file format: {ext or effective_mime}"
        return {
            "content": "",
            "metadata": {
                "filename": filename,
                "size_bytes": size_bytes,
                "mime_type": effective_mime,
                "page_count": None,
                "word_count": 0,
                "extracted_at": extracted_at,
            },
            "error": error_msg,
        }

    content = ""
    page_count: Optional[int] = None
    error: Optional[str] = None

    try:
        # 1. PDF extraction via PyMuPDF
        if ext in PDF_EXTENSIONS or effective_mime == "application/pdf":
            if not PYMUPDF_AVAILABLE or fitz is None:
                error = "PyMuPDF not available for PDF extraction"
                content = ""
            else:
                try:
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    page_count = doc.page_count
                    pages_text: list[str] = []
                    for idx, page in enumerate(doc):
                        page_text = page.get_text()
                        if doc.page_count > 1:
                            pages_text.append(f"--- Page {idx + 1} ---\n{page_text.strip()}")
                        else:
                            pages_text.append(page_text.strip())
                    content = "\n\n".join(pages_text).strip()
                    doc.close()
                except Exception as pdf_exc:
                    error = f"Failed to extract PDF text: {pdf_exc}"
                    content = ""

        # 2. Image files (Pillow + pytesseract OCR)
        elif ext in IMAGE_EXTENSIONS or effective_mime.startswith("image/"):
            display_path = image_rel_path or filename
            ocr_text = ""
            ocr_succeeded = False

            if PYTESSERACT_AVAILABLE and PILLOW_AVAILABLE and pytesseract is not None and Image is not None:
                try:
                    img = Image.open(io.BytesIO(file_bytes))
                    # Quick check if tesseract binary can execute
                    raw_ocr = pytesseract.image_to_string(img).strip()
                    if raw_ocr:
                        ocr_text = raw_ocr
                        ocr_succeeded = True
                except Exception as ocr_exc:
                    logger.debug("Tesseract OCR fallback: %s", ocr_exc)

            if ocr_succeeded and ocr_text:
                content = ocr_text
            else:
                content = f"{display_path}\nImage file (OCR not available)"

        # 3. Data files (JSON, YAML, XML, CSV)
        elif ext in DATA_EXTENSIONS or effective_mime in {"application/json", "application/xml", "text/csv"}:
            try:
                raw_text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raw_text = file_bytes.decode("latin-1", errors="replace")

            if ext == ".json" or effective_mime == "application/json":
                try:
                    parsed = json.loads(raw_text)
                    content = json.dumps(parsed, indent=2)
                except Exception:
                    content = raw_text
            else:
                content = raw_text

        # 4. Code & text files
        else:
            try:
                content = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                content = file_bytes.decode("latin-1", errors="replace")

    except Exception as exc:
        logger.error("Error ingesting file %s: %s", filename, exc)
        error = str(exc)
        content = ""

    word_count = len(content.split()) if content else 0

    metadata = {
        "filename": filename,
        "size_bytes": size_bytes,
        "mime_type": effective_mime,
        "page_count": page_count,
        "word_count": word_count,
        "extracted_at": extracted_at,
    }

    return {
        "content": content,
        "metadata": metadata,
        "error": error,
    }


def get_candidate_upload_dirs(workspace: str = "") -> list[Path]:
    """Return all candidate directories where uploaded files and metadata might exist."""
    candidates: list[Path] = []

    # 1. Explicit workspace path
    if workspace:
        try:
            candidates.append(Path(workspace).resolve() / ".code_os" / "uploads")
        except Exception:
            pass

    # 2. Current working directory
    candidates.append(Path(".").resolve() / ".code_os" / "uploads")

    # 3. Parent directory (critical when backend process runs with CWD='backend')
    candidates.append(Path("..").resolve() / ".code_os" / "uploads")

    # 4. Global application roaming directory (near code-os.sqlite3)
    try:
        from app.core.config import get_settings
        settings = get_settings()
        if hasattr(settings, "database_path") and settings.database_path:
            candidates.append(Path(settings.database_path).resolve().parent / "uploads")
            candidates.append(Path(settings.database_path).resolve().parent / ".code_os" / "uploads")
    except Exception:
        pass

    seen: set[str] = set()
    deduped: list[Path] = []
    for c in candidates:
        norm = str(c.resolve()) if c.is_absolute() else str(c)
        if norm not in seen:
            seen.add(norm)
            deduped.append(c)

    return deduped


def get_uploads_dir(workspace: str) -> Path:
    """Return the primary absolute path to <workspace>/.code_os/uploads."""
    if workspace:
        ws = Path(workspace).resolve()
    else:
        # Detect if running from 'backend/' subdirectory of project root
        if (Path("..") / "package.json").exists() or (Path("..") / ".code_os").exists():
            ws = Path("..").resolve()
        else:
            ws = Path(".").resolve()
    uploads_dir = ws / ".code_os" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


def save_uploaded_file(
    workspace: str,
    file_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
) -> dict[str, Any]:
    """Ingest, assign a UUID, and persist file and metadata in <workspace>/.code_os/uploads/."""
    file_id = str(uuid.uuid4())
    uploads_dir = get_uploads_dir(workspace)

    # Sanitize filename
    clean_name = re.sub(r'[^\w\.-]', '_', Path(filename).name)
    raw_file_path = uploads_dir / f"{file_id}_{clean_name}"
    meta_file_path = uploads_dir / f"{file_id}_meta.json"

    # Save raw bytes to disk
    raw_file_path.write_bytes(file_bytes)

    # Ingest text & metadata
    rel_image_path = f".code_os/uploads/{file_id}_{clean_name}"
    result = ingest_file(file_bytes, filename, mime_type, image_rel_path=rel_image_path)

    content = result["content"]
    content_preview = content[:100] if content else ""
    metadata = result["metadata"]
    metadata["stored_path"] = str(raw_file_path)
    metadata["relative_path"] = rel_image_path
    error = result["error"]

    record = {
        "file_id": file_id,
        "filename": filename,
        "stored_filename": f"{file_id}_{clean_name}",
        "content_preview": content_preview,
        "content": content,
        "metadata": metadata,
        "error": error,
    }

    # Persist metadata sidecar
    meta_file_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    # Invalidate / update in-memory cache
    _FILE_RECORD_CACHE[file_id] = record
    if workspace:
        _FILE_RECORD_CACHE[f"{file_id}:{workspace}"] = record

    return record


_FILE_RECORD_CACHE: dict[str, dict[str, Any]] = {}


def get_uploaded_file(file_id: str, workspace: str = "") -> Optional[dict[str, Any]]:
    """Retrieve full uploaded file content and metadata by UUID from any valid candidate root, with in-memory caching."""
    cache_key = f"{file_id}:{workspace}" if workspace else file_id
    if cache_key in _FILE_RECORD_CACHE:
        return _FILE_RECORD_CACHE[cache_key]
    if file_id in _FILE_RECORD_CACHE:
        return _FILE_RECORD_CACHE[file_id]

    for uploads_dir in get_candidate_upload_dirs(workspace):
        if not uploads_dir.exists():
            continue
        meta_file = uploads_dir / f"{file_id}_meta.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                _FILE_RECORD_CACHE[cache_key] = data
                _FILE_RECORD_CACHE[file_id] = data
                return data
            except Exception as exc:
                logger.error("Failed to read meta file %s: %s", meta_file, exc)

    return None


def format_attached_files_xml(
    attached_files: list[dict[str, Any]],
    max_chars_per_file: int = 12000,
    max_total_chars: int = 24000,
) -> str:
    """Format attached files as an XML block with deterministic head+tail truncation.

    Prevents oversized prompts from blowing provider TPM limits (e.g. Groq 8,000 TPM limit)
    or triggering HTTP 413 Context Overflow errors, while preserving document headers,
    structure, and conclusions.
    """
    if not attached_files:
        return ""

    file_elements: list[str] = []
    current_total_chars = 0

    for f in attached_files:
        fid = f.get("id") or f.get("file_id", "file")
        fname = f.get("filename") or f.get("name", "attachment")
        fmeta = f.get("metadata") or {}
        mtype = f.get("mime_type") or f.get("type") or fmeta.get("mime_type", "text/plain")
        pcount = f.get("page_count") or f.get("pages") or fmeta.get("page_count", "")
        wcount = f.get("word_count") or f.get("words") or fmeta.get("word_count", "")
        fcontent = str(f.get("content", ""))

        if not fcontent.strip():
            continue

        # Single-file budget check (head + tail)
        is_truncated = False
        if len(fcontent) > max_chars_per_file:
            is_truncated = True
            omitted = len(fcontent) - max_chars_per_file
            head_len = int(max_chars_per_file * 0.6)
            tail_len = int(max_chars_per_file * 0.4)
            head = fcontent[:head_len]
            tail = fcontent[-tail_len:]
            fcontent = (
                f"{head}\n\n"
                f"[... middle truncated — {omitted} characters omitted to stay within model context / TPM limits. Full content available in preview. ...]\n\n"
                f"{tail}"
            )

        # Multi-file budget check
        if current_total_chars + len(fcontent) > max_total_chars:
            avail = max(1000, max_total_chars - current_total_chars)
            if len(fcontent) > avail:
                is_truncated = True
                omitted = len(fcontent) - avail
                fcontent = f"{fcontent[:avail]}\n\n[... {omitted} characters omitted for multi-attachment context budget ...]"

        current_total_chars += len(fcontent)
        trunc_attr = ' truncated="true"' if is_truncated else ""
        file_elements.append(
            f'<file id="{fid}" name="{fname}" type="{mtype}" pages="{pcount}" words="{wcount}"{trunc_attr}>\n{fcontent}\n</file>'
        )

    if not file_elements:
        return ""

    return f'<attached_files count="{len(file_elements)}">\n' + "\n".join(file_elements) + "\n</attached_files>"


def list_uploaded_files(workspace: str) -> list[dict[str, Any]]:
    """List all uploaded files in candidate upload directories."""
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for uploads_dir in get_candidate_upload_dirs(workspace):
        if not uploads_dir.exists():
            continue

        for meta_file in sorted(uploads_dir.glob("*_meta.json"), key=os.path.getmtime, reverse=True):
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                fid = data.get("file_id")
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    results.append({
                        "file_id": fid,
                        "filename": data.get("filename"),
                        "content_preview": data.get("content_preview", ""),
                        "metadata": data.get("metadata", {}),
                        "error": data.get("error"),
                    })
            except Exception as exc:
                logger.debug("Failed reading upload meta %s: %s", meta_file, exc)

    return results


def delete_uploaded_file(file_id: str, workspace: str = "") -> bool:
    """Delete uploaded raw file and metadata sidecar from all candidate disks."""
    deleted_any = False

    for uploads_dir in get_candidate_upload_dirs(workspace):
        if not uploads_dir.exists():
            continue
        meta_file = uploads_dir / f"{file_id}_meta.json"
        if meta_file.exists():
            try:
                meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
                stored_filename = meta_data.get("stored_filename")
                if stored_filename:
                    raw_file = uploads_dir / stored_filename
                    if raw_file.exists():
                        raw_file.unlink(missing_ok=True)
            except Exception:
                pass
            meta_file.unlink(missing_ok=True)
            deleted_any = True

        # Check for any remaining files matching file_id_*
        for f in uploads_dir.glob(f"{file_id}_*"):
            f.unlink(missing_ok=True)
            deleted_any = True

    # Evict from in-memory cache
    _FILE_RECORD_CACHE.pop(file_id, None)
    if workspace:
        _FILE_RECORD_CACHE.pop(f"{file_id}:{workspace}", None)

    return deleted_any
