"""Local, encrypted storage and validation for GitHub personal access tokens."""

from __future__ import annotations

import httpx
from fastapi import HTTPException

from ...core.security import decrypt_secret, encrypt_secret
from ...core.config import get_settings


_TOKEN_FILE = "github_pat.enc"
_GITHUB_USER_URL = "https://api.github.com/user"


def _token_path():
    return get_settings().data_dir / _TOKEN_FILE


async def validate_and_store_token(token: str) -> dict[str, str]:
    """Validate a PAT with GitHub before saving only its encrypted form."""
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                _GITHUB_USER_URL,
                headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Unable to validate GitHub token") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="GitHub token is invalid or has expired")

    login = str(response.json().get("login", "GitHub user"))
    token_path = _token_path()
    token_path.write_text(encrypt_secret(token), encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    return {"login": login}


def get_stored_token() -> str | None:
    token_path = _token_path()
    if not token_path.exists():
        return None
    try:
        return decrypt_secret(token_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Stored GitHub token could not be read") from exc
