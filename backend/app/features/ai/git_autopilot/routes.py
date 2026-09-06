"""
routes.py — FastAPI routes for Git Autopilot.

Endpoints:
- GET  /api/git-autopilot/analyze?workspace=
- POST /api/git-autopilot/generate-commit
- POST /api/git-autopilot/generate-pr
- POST /api/git-autopilot/branch
- POST /api/git-autopilot/commit
- POST /api/git-autopilot/push
- POST /api/git-autopilot/pr
- GET  /api/git-autopilot/github-token
- PUT  /api/git-autopilot/github-token
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.trust import ensure_workspace_trusted
from .service import (
    analyze_changes,
    generate_commit_message,
    generate_pr_description,
    create_branch,
    stage_and_commit,
    push_branch,
    create_pull_request,
    get_github_token,
    save_github_token,
)

router = APIRouter()


# ── Request Models ────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    workspace: Optional[str] = None


class GenerateCommitRequest(BaseModel):
    workspace: str
    provider_config: Optional[Dict[str, Any]] = None


class GeneratePRRequest(BaseModel):
    workspace: str
    provider_config: Optional[Dict[str, Any]] = None
    commit_message: Optional[str] = None


class CreateBranchRequest(BaseModel):
    workspace: str
    branch_name: str


class CommitRequest(BaseModel):
    workspace: str
    message: Optional[str] = None
    commit_message: Optional[str] = None
    file_paths: Optional[List[str]] = None


class PushRequest(BaseModel):
    workspace: str
    branch: Optional[str] = None
    branch_name: Optional[str] = None


class CreatePRRequest(BaseModel):
    workspace: str
    title: str
    body: str
    base: str = "main"
    base_branch: Optional[str] = None
    head: Optional[str] = None
    head_branch: Optional[str] = None
    token: Optional[str] = None


class SaveTokenRequest(BaseModel):
    token: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/analyze")
@router.post("/analyze")
async def handle_analyze_changes(
    req: Optional[AnalyzeRequest] = None,
    workspace: Optional[str] = Query(None, description="Workspace directory path"),
):
    """Analyze uncommitted git changes and categorize files."""
    ws = (req.workspace if req and req.workspace else None) or workspace
    if not ws:
        raise HTTPException(status_code=400, detail="workspace is required")
    analysis = await analyze_changes(ws)
    return {"ok": True, **analysis}


@router.post("/generate-commit")
async def handle_generate_commit(req: GenerateCommitRequest):
    """Generate Conventional Commits message based on diff analysis."""
    commit_msg = await generate_commit_message(req.workspace, req.provider_config)
    return {"ok": True, "commit_message": commit_msg}


@router.post("/generate-pr")
async def handle_generate_pr(req: GeneratePRRequest):
    """Generate structured Pull Request title and description."""
    pr_data = await generate_pr_description(req.workspace, req.provider_config, req.commit_message)
    return {"ok": True, **pr_data}


@router.post("/branch")
async def handle_create_branch(req: CreateBranchRequest):
    """Create and checkout a new branch (requires workspace trust)."""
    await ensure_workspace_trusted(req.workspace)
    res = await create_branch(req.workspace, req.branch_name)
    return res


@router.post("/commit")
async def handle_commit(req: CommitRequest):
    """Stage files and create a git commit (requires workspace trust)."""
    await ensure_workspace_trusted(req.workspace)
    final_msg = (req.commit_message or req.message or "").strip()
    if not final_msg:
        raise HTTPException(status_code=400, detail="Commit message cannot be empty")
    commit_hash = await stage_and_commit(req.workspace, final_msg, req.file_paths)
    return {"ok": True, "commit_hash": commit_hash}


@router.post("/push")
async def handle_push(req: PushRequest):
    """Push branch to origin (plain push only, requires workspace trust)."""
    await ensure_workspace_trusted(req.workspace)
    branch = req.branch or req.branch_name or "main"
    res = await push_branch(req.workspace, branch)
    return res


@router.post("/pr")
async def handle_create_pr(req: CreatePRRequest):
    """Create GitHub Pull Request via REST API (requires workspace trust and GitHub token)."""
    await ensure_workspace_trusted(req.workspace)
    res = await create_pull_request(
        workspace=req.workspace,
        title=req.title,
        body=req.body,
        base=req.base_branch or req.base,
        head=req.head_branch or req.head,
        token=req.token,
    )
    return res


@router.get("/github-token")
async def handle_get_token():
    """Check if GitHub Personal Access Token is configured."""
    token = await get_github_token()
    has_token = bool(token and token.strip())
    masked = f"{token[:4]}...{token[-4:]}" if has_token and len(token) > 8 else ("configured" if has_token else None)
    return {"ok": True, "has_token": has_token, "masked_token": masked}


@router.post("/github-token")
@router.put("/github-token")
async def handle_save_token(req: SaveTokenRequest):
    """Save GitHub Personal Access Token to settings table."""
    success = await save_github_token(req.token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save GitHub token")
    return {"ok": True, "saved": True}
