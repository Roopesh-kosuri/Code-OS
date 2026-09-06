"""
staging package — Smart Staging / PR View review system.
"""

from .staging_review_service import (
    get_staged_changes_summary,
    get_file_diff,
    approve_files,
    reject_files,
    approve_chunk,
    reject_chunk,
    apply_approved_changes,
    stage_files_for_review,
    clear_staged_changes,
)
from .staging_review_routes import router as staging_router

__all__ = [
    "get_staged_changes_summary",
    "get_file_diff",
    "approve_files",
    "reject_files",
    "approve_chunk",
    "reject_chunk",
    "apply_approved_changes",
    "stage_files_for_review",
    "clear_staged_changes",
    "staging_router",
]
