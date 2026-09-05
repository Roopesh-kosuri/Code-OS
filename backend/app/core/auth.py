"""
core/auth.py — Session-token authentication for the CODE-OS backend API.

On startup the backend generates a cryptographically random token, writes it
to a file with restrictive permissions (mode 0o600) as JSON with expiration,
and prints a single structured line to stdout so the Electron main process can capture it:

    CODE_OS_SESSION_TOKEN=<hex-token>

The token must be present in the Authorization header on ALL mutating API
requests (POST, PUT, PATCH, DELETE) and on sensitive GET requests.

Unauthenticated allowlist:
  - GET /health              — liveness probe
  - GET /api/auth/token      — token verification endpoint
  - GET /api/ai/ollama/*     — Ollama connectivity checks (read-only, non-sensitive)
  - GET /api/health          — liveness probe alias

Design rationale:
  - Token is 32 bytes (256 bits) of secrets.token_hex(32) -> 64 chars.
  - Written to <userData>/session_token with mode 0o600 as JSON containing created_at and expires_at (24h TTL).
  - Legacy plain-text token files are automatically detected and replaced without crashes.
  - CORS headers are removed from auth responses so global CORSMiddleware governs origin security.
"""

import json
import logging
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Module-level token (set once at startup, then read-only).
_SESSION_TOKEN: str | None = None

# Token validity duration: 24 hours
TOKEN_TTL_SECONDS: float = 24 * 3600.0

# Paths that are completely open (no auth required).
_UNAUTHENTICATED_PATHS = frozenset({
    "/health",
    "/api/auth/token",
    "/api/ai/ollama/health",
    "/api/ai/ollama/models",
    "/api/health",
    "/api/system/readiness",
})


def _token_file_path() -> Path:
    """Return the path to the session token file."""
    from .config import get_settings
    return get_settings().data_dir / "session_token"


def load_token() -> str | None:
    """
    Load the session token from disk if valid and unexpired.
    Returns the token string if valid, or None if expired/corrupted/missing.
    Deletes expired, corrupted, or legacy plain-text token files.
    """
    token_path = _token_file_path()
    if not token_path.exists():
        return None

    try:
        content = token_path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        logger.warning("auth: failed to read session token file %s: %s", token_path, exc)
        return None

    # Check if content is valid JSON (v3.1.0+ format)
    try:
        data = json.loads(content)
    except Exception:
        # Legacy plain-text token from v3.0.0 or corrupted file: treat as expired and remove
        logger.info("auth: legacy plain-text or malformed token file detected at %s; removing for rotation", token_path)
        try:
            token_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("auth: could not remove legacy token file %s: %s", token_path, exc)
        return None

    if not isinstance(data, dict):
        try:
            token_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    token = data.get("token")
    expires_at = data.get("expires_at", 0)

    # Validate token structure: 64 hex characters
    if not isinstance(token, str) or len(token) != 64 or not all(c in "0123456789abcdefABCDEF" for c in token):
        try:
            token_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    # Check expiration (24h TTL)
    if not isinstance(expires_at, (int, float)) or time.time() >= expires_at:
        logger.info("auth: session token expired at %s; removing for rotation", token_path)
        try:
            token_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("auth: could not remove expired token file %s: %s", token_path, exc)
        return None

    return token


def generate_and_store_token() -> str:
    """
    Generate a new session token, persist it to disk with expiration JSON, and print it to stdout.
    Called once on backend startup before the first request is handled.
    """
    global _SESSION_TOKEN

    token_path = _token_file_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    # Reuse token across Uvicorn hot-reloads if valid and unexpired
    existing = load_token()
    if existing is not None:
        _SESSION_TOKEN = existing
        print(f"CODE_OS_SESSION_TOKEN={existing}", flush=True)
        logger.info("auth: session token reloaded from %s", token_path)
        return existing

    token = secrets.token_hex(32)  # 256 bits of randomness -> 64 hex chars
    _SESSION_TOKEN = token
    now = time.time()

    token_payload = {
        "token": token,
        "created_at": now,
        "expires_at": now + TOKEN_TTL_SECONDS,
    }

    # Write with restrictive permissions (owner read/write only).
    token_path.write_text(json.dumps(token_payload, indent=2), encoding="utf-8")
    try:
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError as exc:
        logger.debug("auth: os.chmod failed on session token file %s: %s", token_path, exc)

    print(f"CODE_OS_SESSION_TOKEN={token}", flush=True)
    logger.info("auth: session token generated and stored at %s", token_path)
    return token


def get_token() -> str:
    """Return the active session token (must be called after startup)."""
    global _SESSION_TOKEN
    if _SESSION_TOKEN is None:
        loaded = load_token()
        if loaded is not None:
            _SESSION_TOKEN = loaded
        else:
            raise RuntimeError("Session token has not been generated yet or has expired")
    return _SESSION_TOKEN


def _is_exempt(request: Request) -> bool:
    """Return True if the request does not require an auth token."""
    if request.method == "OPTIONS":
        return True
    path = request.url.path
    if path in _UNAUTHENTICATED_PATHS:
        return True
    # WebSocket upgrades are NOT blanket-exempted from auth.
    return False


async def require_token(request: Request, call_next: Callable) -> Response:
    """
    FastAPI middleware that enforces the session token on API requests.
    """
    if _is_exempt(request):
        return await call_next(request)

    req_id = getattr(request.state, "request_id", None)
    auth_headers = {"WWW-Authenticate": "Bearer"}
    if req_id:
        auth_headers["X-Request-ID"] = req_id

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or malformed Authorization header. Expected: Bearer <session-token>"},
            headers=auth_headers,
        )

    provided_token = auth_header.removeprefix("Bearer ").strip()
    try:
        expected = get_token()
    except RuntimeError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Backend not fully initialised yet"},
            headers=auth_headers,
        )

    if not secrets.compare_digest(provided_token, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid session token"},
            headers=auth_headers,
        )

    return await call_next(request)
