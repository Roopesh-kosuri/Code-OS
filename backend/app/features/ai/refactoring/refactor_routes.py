"""refactor_routes.py — FastApi REST router for AI-powered safe code refactoring."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.features.ai.refactoring.analyze_service import (
    analyze_complexity,
    detect_code_smells,
    find_duplicates,
)
from app.features.ai.refactoring.pattern_applier import apply_refactor
from app.features.ai.refactoring.verify_service import verify_refactor_safety

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/refactor", tags=["refactoring"])


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace directory path")
    file_paths: Optional[List[str]] = Field(None, description="Optional subset of files to scan")


class PreviewRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace directory path")
    refactor_type: str = Field(..., description="Type of refactoring to perform")
    file: Optional[str] = Field(None, description="Primary target file")
    params: Dict[str, Any] = Field(default_factory=dict, description="Refactoring specific parameters")


class VerifyRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace directory path")
    changes: List[Dict[str, Any]] = Field(..., description="List of file changes to verify")


class ApplyRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace directory path")
    changes: List[Dict[str, Any]] = Field(..., description="List of file changes to apply")
    verified: bool = Field(False, description="Whether changes were pre-verified")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_workspace(req: AnalyzeRequest) -> Dict[str, Any]:
    """Analyzes codebase for 8 categories of code smells, duplicates, and AST complexity."""
    try:
        smells = detect_code_smells(req.workspace, req.file_paths)
        duplicates = find_duplicates(req.workspace)
        complexity = analyze_complexity(req.workspace)

        critical_count = sum(1 for s in smells if s.get("severity") == "Critical")
        warning_count = sum(1 for s in smells if s.get("severity") == "Warning")
        info_count = sum(1 for s in smells if s.get("severity") == "Info")

        return {
            "smells": smells,
            "duplicates": duplicates,
            "complexity": complexity,
            "summary": {
                "total_smells": len(smells),
                "critical": critical_count,
                "warning": warning_count,
                "info": info_count,
                "duplicate_groups": len(duplicates),
            },
        }
    except Exception as exc:
        logger.error("Analyze error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to analyze workspace: {exc}")


@router.post("/preview")
async def preview_refactoring(req: PreviewRequest) -> Dict[str, Any]:
    """Generates unified diff preview and impact estimation for a requested refactor pattern."""
    try:
        request_data = {
            "refactor_type": req.refactor_type,
            "file": req.file,
            "params": req.params,
        }
        result = apply_refactor(request_data, req.workspace)
        return result
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.error("Preview error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate refactor preview: {exc}")


@router.post("/verify")
async def verify_refactoring(req: VerifyRequest) -> Dict[str, Any]:
    """Runs tests on candidate changes in a sandboxed temporary workspace copy."""
    try:
        result = verify_refactor_safety(req.changes, req.workspace)
        return result
    except Exception as exc:
        logger.error("Verify error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Verification failed: {exc}")


@router.post("/apply")
async def apply_refactoring_changes(req: ApplyRequest) -> Dict[str, Any]:
    """Applies refactored changes to actual workspace only after verifying test suite safety."""
    # Enforce safety verification gate: all refactors MUST pass tests before being applied
    if not req.verified:
        verify_result = verify_refactor_safety(req.changes, req.workspace)
        if not verify_result.get("safe", False):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Refactor verification failed. Changes were blocked to prevent regressions.",
                    "test_results": verify_result.get("test_results"),
                },
            )

    ws_path = Path(req.workspace).resolve()
    applied_files = []

    try:
        for change in req.changes:
            rel_file = change.get("file", "")
            content = change.get("updated_content", "")
            target_path = ws_path / rel_file
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            applied_files.append(rel_file)

        return {
            "success": True,
            "applied_files": applied_files,
            "message": f"Successfully applied refactor to {len(applied_files)} file(s).",
        }
    except Exception as exc:
        logger.error("Apply error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed applying changes to workspace: {exc}")


@router.get("/suggestions")
async def get_suggestions(workspace: str = Query(..., description="Root workspace path")) -> Dict[str, Any]:
    """Generates intelligent refactoring suggestions based on code smell analysis."""
    try:
        smells = detect_code_smells(workspace)
        duplicates = find_duplicates(workspace)

        suggestions = []
        # Group smells into actionable suggestions
        for idx, smell in enumerate(smells[:25]):
            stype = smell.get("type", "")
            loc = smell.get("location", {})
            file = loc.get("file", "")

            refactor_type = "extract_function"
            title = f"Refactor: {stype.replace('_', ' ').title()}"

            if stype == "long_function":
                refactor_type = "extract_function"
                title = f"Extract helper functions in {file}"
            elif stype == "deep_nesting":
                refactor_type = "flatten_conditionals"
                title = f"Flatten conditionals in {file}"
            elif stype == "duplicated_code":
                refactor_type = "deduplicate"
                title = f"Deduplicate repeated logic in {file}"
            elif stype == "god_class":
                refactor_type = "extract_class"
                title = f"Split god class in {file}"
            elif stype == "complex_conditional":
                refactor_type = "apply_strategy_pattern"
                title = f"Apply strategy pattern in {file}"
            elif stype in ("dead_code", "unused_imports"):
                refactor_type = "remove_dead_code"
                title = f"Clean up dead code / unused imports in {file}"
            elif stype == "magic_numbers":
                refactor_type = "rename_symbol"
                title = f"Extract constant for magic number in {file}"

            suggestions.append({
                "id": f"sug_{idx + 1}",
                "title": title,
                "description": smell.get("suggestion", ""),
                "refactor_type": refactor_type,
                "file": file,
                "location": loc,
                "severity": smell.get("severity", "Info"),
            })

        return {"suggestions": suggestions}
    except Exception as exc:
        logger.error("Suggestions error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate suggestions: {exc}")
