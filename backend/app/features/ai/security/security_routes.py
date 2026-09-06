"""
security_routes.py — REST API router for Workspace Security Scanner and AI Auto-Fix.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.features.ai.security.scanner_service import scan_workspace, check_python_dependencies, check_npm_dependencies
from app.features.ai.security.fix_service import generate_fix, apply_fix, verify_fix, GENERATED_FIXES

logger = logging.getLogger(__name__)

router = APIRouter()


class ScanRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace path to scan")


class GenerateFixRequest(BaseModel):
    vulnerability_id: str = Field(..., description="ID of vulnerability to fix")
    vulnerability: Optional[Dict[str, Any]] = Field(None, description="Vulnerability metadata if not cached")
    workspace: Optional[str] = Field(None, description="Workspace path")


class ApplyFixRequest(BaseModel):
    vulnerability_id: str = Field(..., description="ID of vulnerability to fix")
    patch: str = Field(..., description="Patch diff string")
    workspace: Optional[str] = Field(None, description="Workspace path")


@router.post("/scan")
async def scan_endpoint(req: ScanRequest) -> Dict[str, Any]:
    """Scans the entire workspace for code vulnerabilities and dependency issues."""
    try:
        results = scan_workspace(req.workspace)
        return results
    except Exception as exc:
        logger.error("Security scan failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")


@router.post("/generate-fix")
async def generate_fix_endpoint(req: GenerateFixRequest) -> Dict[str, Any]:
    """Generates an AI-suggested secure patch diff for a given vulnerability."""
    vuln_data = req.vulnerability
    if not vuln_data and req.vulnerability_id in GENERATED_FIXES:
        vuln_data = GENERATED_FIXES[req.vulnerability_id].get("vulnerability")

    if not vuln_data:
        raise HTTPException(status_code=404, detail=f"Vulnerability {req.vulnerability_id} details not found")

    ws = req.workspace or vuln_data.get("workspace")
    if not ws:
        raise HTTPException(status_code=400, detail="Workspace path is required")

    try:
        res = await generate_fix(vuln_data, ws)
        return res
    except Exception as exc:
        logger.error("Fix generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Fix generation failed: {exc}")


@router.post("/apply-fix")
async def apply_fix_endpoint(req: ApplyFixRequest) -> Dict[str, Any]:
    """Applies patch to target file and runs verification checks."""
    try:
        success = apply_fix(req.vulnerability_id, req.patch, req.workspace)
        if not success:
            raise HTTPException(status_code=400, detail="Fix application failed or broke existing tests")

        # Verify fix
        resolved = verify_fix(req.vulnerability_id, req.workspace)
        return {
            "success": True,
            "resolved": resolved,
            "status": "resolved" if resolved else "pending",
        }
    except Exception as exc:
        logger.error("Apply fix failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Apply fix failed: {exc}")


@router.get("/dependencies")
async def get_dependencies_endpoint(workspace: str = Query(...)) -> Dict[str, Any]:
    """Returns list of outdated / vulnerable packages in workspace."""
    from pathlib import Path
    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return {"dependencies": []}

    dep_issues = []
    dep_issues.extend(check_python_dependencies(ws_path))
    dep_issues.extend(check_npm_dependencies(ws_path))
    return {"dependencies": dep_issues}
