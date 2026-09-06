"""
cicd_routes.py — REST API router for CI/CD Pipeline Generator.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.features.ai.cicd.stack_analyzer import analyze_stack
from app.features.ai.cicd.yaml_generator import generate_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalyzeStackRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace path to analyze")


class GeneratePipelineRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace path")
    provider: Optional[str] = Field("github", description="'github' or 'gitlab'")
    stack_config: Optional[Dict[str, Any]] = Field(None, description="Optional pre-analyzed stack config")


class SavePipelineRequest(BaseModel):
    workspace: str = Field(..., description="Root workspace path")
    yaml_content: str = Field(..., description="YAML content to save")
    file_path: str = Field(..., description="Relative destination file path (e.g., .github/workflows/ci.yml)")


@router.post("/analyze")
async def analyze_endpoint(req: AnalyzeStackRequest) -> Dict[str, Any]:
    """Analyzes codebase stack to detect languages, frameworks, and test runners."""
    try:
        config = analyze_stack(req.workspace)
        return config
    except Exception as exc:
        logger.error("Stack analysis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Stack analysis failed: {exc}")


@router.post("/generate")
async def generate_endpoint(req: GeneratePipelineRequest) -> Dict[str, Any]:
    """Generates CI/CD pipeline YAML content for the specified provider."""
    try:
        config = req.stack_config or analyze_stack(req.workspace)
        result = generate_pipeline(config, provider=req.provider or "github")
        return result
    except Exception as exc:
        logger.error("Pipeline generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Pipeline generation failed: {exc}")


@router.post("/save")
async def save_endpoint(req: SavePipelineRequest) -> Dict[str, Any]:
    """Saves generated YAML pipeline file directly to the workspace."""
    try:
        ws_path = Path(req.workspace)
        if not ws_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Workspace path '{req.workspace}' does not exist")

        dest_file = ws_path / req.file_path.lstrip("/\\")
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(req.yaml_content, encoding="utf-8")

        return {
            "success": True,
            "file_path": req.file_path,
            "full_path": str(dest_file),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed saving pipeline file: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed saving pipeline file: {exc}")
