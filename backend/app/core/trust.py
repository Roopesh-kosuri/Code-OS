"""
trust.py - Shared workspace trust enforcement dependency.

Centralizes the _ensure_trusted guard used across API route handlers.
Prevents circular dependencies by only importing from trust_service.
"""
from __future__ import annotations

from fastapi import HTTPException
from ..features.workspaces.trust_service import get_workspace_trust


async def ensure_workspace_trusted(workspace: str, custom_message: str | None = None) -> None:
    """Ensure workspace is trusted; raise HTTP 403 if in Restricted Mode."""
    trust = await get_workspace_trust(workspace)
    if not trust.get("trusted", False):
        detail = custom_message or "Workspace is in Restricted Mode."
        raise HTTPException(status_code=403, detail=detail)


# Backward-compatible alias
_ensure_trusted = ensure_workspace_trusted