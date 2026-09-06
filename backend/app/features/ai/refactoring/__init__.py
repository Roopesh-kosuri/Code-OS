"""Refactoring Assistant package — AI-powered safe code restructuring."""
from app.features.ai.refactoring.analyze_service import (
    detect_code_smells,
    find_duplicates,
    analyze_complexity,
)
from app.features.ai.refactoring.pattern_applier import apply_refactor
from app.features.ai.refactoring.verify_service import verify_refactor_safety
from app.features.ai.refactoring.refactor_routes import router as refactor_router

__all__ = [
    "detect_code_smells",
    "find_duplicates",
    "analyze_complexity",
    "apply_refactor",
    "verify_refactor_safety",
    "refactor_router",
]
