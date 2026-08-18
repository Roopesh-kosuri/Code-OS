"""
Code intelligence & workspace analysis package for CODE OS.
Provides AST symbol indexing, definition lookup, reference searching, style extraction,
dead-code detection, secret scanning, structured git diffs, and living architecture docs.
"""
from .code_intelligence import (
    CodeIntelligence,
    _build_symbol_index,
    _handle_go_to_definition,
    _handle_find_references,
    _extract_style_conventions,
    _load_style_conventions_summary,
    _find_dead_code,
    _load_architecture_doc,
    _update_architecture_doc,
    _get_structured_git_diff,
    _handle_git_diff,
    _scan_for_secrets,
    _calculate_shannon_entropy,
    SECRET_PATTERNS,
)

__all__ = [
    "CodeIntelligence",
    "_build_symbol_index",
    "_handle_go_to_definition",
    "_handle_find_references",
    "_extract_style_conventions",
    "_load_style_conventions_summary",
    "_find_dead_code",
    "_load_architecture_doc",
    "_update_architecture_doc",
    "_get_structured_git_diff",
    "_handle_git_diff",
    "_scan_for_secrets",
    "_calculate_shannon_entropy",
    "SECRET_PATTERNS",
]
