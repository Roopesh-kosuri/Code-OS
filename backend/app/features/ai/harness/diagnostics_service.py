"""diagnostics_service.py — Compiler, linter, and type diagnostics service for CODE OS.

Provides file-level diagnostics (syntax errors, compiler errors, type errors)
for the get_diagnostics tool, allowing agents to verify edits without a full test suite.
Supports mock provider injection for unit testing and testing environments.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.paths import ensure_within_workspace

logger = logging.getLogger(__name__)


class DiagnosticsService:
    """Pluggable service for retrieving compiler, syntax, and type diagnostics."""

    _mock_provider: Optional[Callable[[str, str], list[dict[str, Any]]]] = None
    _is_available: bool = True

    @classmethod
    def set_mock_provider(cls, provider: Optional[Callable[[str, str], list[dict[str, Any]]]]) -> None:
        """Inject a mock diagnostic provider function: (workspace, file_path) -> list[Diagnostic]."""
        cls._mock_provider = provider

    @classmethod
    def set_available(cls, available: bool) -> None:
        """Toggle service availability (used for testing graceful degradation / fallback)."""
        cls._is_available = available

    @classmethod
    def reset(cls) -> None:
        """Reset service state back to defaults."""
        cls._mock_provider = None
        cls._is_available = True

    @classmethod
    def get_diagnostics(cls, workspace: str, file_path: str) -> tuple[list[dict[str, Any]], str]:
        """Retrieve diagnostic issues for a given file.

        Returns:
            (diagnostics_list, status_message)
        """
        if not cls._is_available:
            return [], "Diagnostics unavailable"

        if cls._mock_provider is not None:
            try:
                res = cls._mock_provider(workspace, file_path)
                msg = f"Retrieved {len(res)} diagnostic issue(s)" if res else "No diagnostic issues detected"
                return res, msg
            except Exception as exc:
                logger.warning("Mock diagnostics provider failed: %s", exc)
                return [], f"Diagnostics unavailable: {exc}"

        # Native syntax and compiler check based on file extension
        try:
            target = ensure_within_workspace(workspace, file_path)
        except Exception as exc:
            return [], f"Path rejected: {exc}"

        if not target.is_file():
            return [], f"File not found: {file_path}"

        suffix = target.suffix.lower()
        diagnostics: list[dict[str, Any]] = []

        if suffix == ".py":
            try:
                source = target.read_text(encoding="utf-8", errors="replace")
                ast.parse(source, filename=file_path)
            except SyntaxError as syn_err:
                diagnostics.append({
                    "file": file_path,
                    "line": syn_err.lineno or 1,
                    "column": syn_err.offset or 1,
                    "severity": "error",
                    "message": syn_err.msg or "Syntax error",
                    "source": "py_compile",
                })
                return diagnostics, f"Found {len(diagnostics)} syntax error(s)"
            except Exception as exc:
                logger.debug("Diagnostics parse exception: %s", exc)

        # Fallback when no active LSP or compiler errors are reported
        if not diagnostics:
            return [], "Diagnostics unavailable: No diagnostic issues detected or service unavailable"

        return diagnostics, f"Found {len(diagnostics)} diagnostic issue(s)"


def run_diagnostics(workspace: str, file_path: str) -> tuple[list[dict[str, Any]], str]:
    """Convenience functional wrapper around DiagnosticsService.get_diagnostics."""
    return DiagnosticsService.get_diagnostics(workspace, file_path)
