"""
__init__.py — Git Autopilot package exports.
"""

from .routes import router as git_autopilot_router
from .service import (
    analyze_changes,
    categorize_file,
    generate_commit_message,
    generate_pr_description,
    create_branch,
    stage_and_commit,
    push_branch,
    create_pull_request,
    get_github_token,
    save_github_token,
)

__all__ = [
    "git_autopilot_router",
    "analyze_changes",
    "categorize_file",
    "generate_commit_message",
    "generate_pr_description",
    "create_branch",
    "stage_and_commit",
    "push_branch",
    "create_pull_request",
    "get_github_token",
    "save_github_token",
]
