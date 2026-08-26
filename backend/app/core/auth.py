"""
core/auth.py — Session-token authentication for the CODE-OS backend API.

On startup the backend generates a cryptographically random token, writes it
to a file with restrictive permissions (mode 0o600), and prints a single
structured line to stdout so the Electron main process can capture it:

    CODE_OS_SESSION_TOKEN=<hex-token>

The token must be present in the Authorization header on ALL mutating API
requests (POST, PUT, PATCH, DELETE) and on sensitive GET requests.

Unauthenticated allowlist:
  - GET /health              — liveness probe
  - GET /api/ai/ollama/*     — Ollama connectivity checks (read-only, non-sensitive)

Design rationale:
  - Token is 32 bytes (256 bits) of os.urandom(), formatted as hex → 64 chars.
  - Written to <userData>/session_token with mode 0o600 so only the owning
    user can read it.  This prevents other user accounts on the same machine
    from stealing the token.
  - The token is not an env-var at runtime; it is read back from the file by
    the health endpoint so the Electron side can verify it received the right
    value.
  - CORS is already restricted to localhost origins; the token provides defence
    in depth against DNS-rebinding attacks where the CORS origin check can be
    bypassed.
"""

import os
import secrets
import stat
import logging
from pathlib import Path
from typing import Callable

from fastapi import Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

# Module-level token (set once at startup, then read-only).
_SESSION_TOKEN: str | None = None

# Paths that are completely open (no auth required).
_UNAUTHENTICATED_PATHS = frozenset({
    "/health",
    "/api/auth/token",
    "/api/ai/ollama/health",
    "/api/ai/ollama/models",
    "/api/health",
})



def _token_file_path() -> Path:
    """Return the path to the session token file."""
    from .config import get_settings
    return get_settings().data_dir / "session_token"


def generate_and_store_token() -> str:
    """
    Generate a new session token, persist it to disk, and print it to stdout.
    Called once on backend startup before the first request is handled.
    """
    global _SESSION_TOKEN

    token_path = _token_file_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    # Reuse token across Uvicorn hot-reloads if available to prevent invalidating browser sessions
    if token_path.exists():
        try:
            existing = token_path.read_text(encoding="utf-8").strip()
            if len(existing) == 64 and all(c in "0123456789abcdefABCDEF" for c in existing):
                _SESSION_TOKEN = existing
                print(f"CODE_OS_SESSION_TOKEN={existing}", flush=True)
                logger.info("auth: session token reloaded from %s", token_path)
                return existing
        except Exception:
            pass

    token = secrets.token_hex(32)  # 256 bits of randomness
    _SESSION_TOKEN = token

    # Write with restrictive permissions (owner read/write only).
    token_path.write_text(token, encoding="utf-8")
    try:
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass

    print(f"CODE_OS_SESSION_TOKEN={token}", flush=True)
    logger.info("auth: session token generated and stored at %s", token_path)
    return token


def get_token() -> str:
    """Return the active session token (must be called after startup)."""
    global _SESSION_TOKEN
    if _SESSION_TOKEN is None:
        path = _token_file_path()
        if path.exists():
            _SESSION_TOKEN = path.read_text(encoding="utf-8").strip()
        else:
            raise RuntimeError("Session token has not been generated yet")
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


_CORS_AUTH_HEADERS = {
    "WWW-Authenticate": "Bearer",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "*",
    "Access-Control-Allow-Headers": "*",
}


async def require_token(request: Request, call_next: Callable) -> Response:
    """
    FastAPI middleware that enforces the session token on API requests.
    """
    if _is_exempt(request):
        return await call_next(request)

    from fastapi.responses import JSONResponse
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or malformed Authorization header. Expected: Bearer <session-token>"},
            headers=_CORS_AUTH_HEADERS,
        )

    provided_token = auth_header.removeprefix("Bearer ").strip()
    try:
        expected = get_token()
    except RuntimeError:
        return JSONResponse(status_code=503, content={"detail": "Backend not fully initialised yet"}, headers=_CORS_AUTH_HEADERS)

    if not secrets.compare_digest(provided_token, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid session token"},
            headers=_CORS_AUTH_HEADERS,
        )

    return await call_next(request)
