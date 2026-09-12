"""intent_tool_selector.py — Intent-based dynamic tool filtering for CODE OS turns.

Analyzes task intent from user query, active file, and RAG context to shrink
active_tools per turn, reducing token consumption and hallucination surface on weaker models.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Patterns for intent classification
DB_KEYWORDS = {
    "sql", "migration", "schema", "sqlite", "postgres", "postgresql", "mysql",
    "alembic", "prisma", "database", "table", "query", "orm", "foreign key", "primary key",
    "db_setup", "ddl", "dml", "crud", "seed",
}

FRONTEND_KEYWORDS = {
    "react", "vue", "angular", "svelte", "css", "scss", "html", "tailwind", "jsx", "tsx",
    "component", "styling", "ui", "button", "navbar", "modal", "frontend", "layout", "flexbox",
    "grid", "canvas", "dom", "animation", "responsive",
}

TEST_KEYWORDS = {
    "pytest", "vitest", "jest", "unittest", "test suite", "run tests", "run_test",
    "assert", "mock", "fixture", "testing", "coverage", "spec",
}

DOCS_KEYWORDS = {
    "documentation", "readme", "docstring", "docs", "document", "architecture.md",
    "changelog", "api doc", "user guide", "manual",
}

# Sets of tools for filtering
BROWSER_AND_COMPUTER_TOOLS = {
    "browser_open", "browser_screenshot", "browser_console_logs", "browser_network_errors",
    "browser_click", "browser_type", "browser_wait_for", "browser_scroll", "browser_close",
    "screen_screenshot", "mouse_click", "keyboard_type", "hotkey", "open_app",
    "list_windows", "focus_window",
}

BACKEND_HEAVY_TOOLS = {
    "server_session",
}


def detect_task_intent(
    user_query: str,
    active_file: Optional[str] = None,
    rag_context: Optional[str] = None,
) -> str:
    """Classify the user turn into an intent: 'db', 'frontend', 'test', 'docs', or 'general'."""
    text = (user_query or "").lower()
    rag_lower = (rag_context or "").lower()
    active_lower = (active_file or "").lower()

    # Active file extension hints
    if active_lower:
        if any(active_lower.endswith(ext) for ext in (".sql", "migration.py", "models.py", "schema.py")):
            return "db"
        if any(active_lower.endswith(ext) for ext in (".tsx", ".jsx", ".vue", ".css", ".scss", ".html", ".svelte")):
            return "frontend"
        if any(sub in active_lower for sub in ("test_", "_test.", ".spec.", ".test.")):
            return "test"
        if any(active_lower.endswith(ext) for ext in (".md", ".rst", ".txt")):
            return "docs"

    words = set(re.findall(r"\b[a-z_0-9-]+\b", text))
    rag_words = set(re.findall(r"\b[a-z_0-9-]+\b", rag_lower[:1000]))

    # Score categories based on keyword presence
    db_score = len(words & DB_KEYWORDS) + (1 if (rag_words & DB_KEYWORDS) else 0)
    fe_score = len(words & FRONTEND_KEYWORDS) + (1 if (rag_words & FRONTEND_KEYWORDS) else 0)
    test_score = len(words & TEST_KEYWORDS) + (1 if (rag_words & TEST_KEYWORDS) else 0)
    docs_score = len(words & DOCS_KEYWORDS) + (1 if (rag_words & DOCS_KEYWORDS) else 0)

    # Check for explicit phrases
    if "run test" in text or "run the tests" in text or "pytest" in text or "vitest" in text:
        test_score += 3
    if "migration" in text or "database" in text or "sqlite" in text or "schema" in text or "sql" in text:
        db_score += 2
    if "component" in text or "react" in text or "tailwind" in text or "css" in text or "styling" in text:
        fe_score += 2
    if "documentation" in text or "readme" in text or "write docs" in text:
        docs_score += 2

    scores = [
        ("test", test_score),
        ("db", db_score),
        ("frontend", fe_score),
        ("docs", docs_score),
    ]
    scores.sort(key=lambda x: x[1], reverse=True)

    top_intent, top_score = scores[0]
    if top_score >= 2:
        return top_intent

    return "general"


def filter_tools_by_intent(
    tools: list[dict[str, Any]],
    intent: str,
) -> list[dict[str, Any]]:
    """Shrink tool definitions based on detected intent:
    * db: exclude browser_* and computer_* tools
    * frontend: exclude backend-heavy tools (e.g. server_session)
    * test: exclude edit_file/append_file, prioritize test tools
    * docs: exclude run_command, prioritize edit_file and read_file
    * general: return unchanged
    """
    if not tools:
        return []

    if intent == "db":
        return [
            t for t in tools
            if t.get("function", {}).get("name") not in BROWSER_AND_COMPUTER_TOOLS
        ]
    elif intent == "frontend":
        return [
            t for t in tools
            if t.get("function", {}).get("name") not in BACKEND_HEAVY_TOOLS
        ]
    elif intent == "test":
        return [
            t for t in tools
            if t.get("function", {}).get("name") not in {"edit_file", "append_file"}
        ]
    elif intent == "docs":
        return [
            t for t in tools
            if t.get("function", {}).get("name") not in {"run_command", *BROWSER_AND_COMPUTER_TOOLS}
        ]

    return list(tools)
