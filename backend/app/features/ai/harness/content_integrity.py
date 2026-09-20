from __future__ import annotations

import ast
import difflib
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Common placeholder phrases that LLMs generate when hitting tokens/limits or hallucinating
_PLACEHOLDER_PATTERNS = [
    re.compile(r"\byour (updated )?code here\b", re.IGNORECASE),
    re.compile(r"\binsert (your )?code here\b", re.IGNORECASE),
    re.compile(r"\bcode goes here\b", re.IGNORECASE),
    re.compile(r"\breplace (this|with (your )?code)\b", re.IGNORECASE),
    re.compile(r"<\s*insert[-_ ]code\s*>", re.IGNORECASE),
    re.compile(r"<\s*placeholder\s*>", re.IGNORECASE),
    re.compile(r"//\s*\.\.\.\s*rest of (the )?code\b", re.IGNORECASE),
    re.compile(r"#\s*\.\.\.\s*rest of (the )?code\b", re.IGNORECASE),
    re.compile(r"//\s*TODO:\s*(implement|add|write)\s*(here)?$", re.IGNORECASE),
    re.compile(r"#\s*TODO:\s*(implement|add|write)\s*(here)?$", re.IGNORECASE),
    re.compile(r"pass\s*#\s*(implement|todo|later|fill)", re.IGNORECASE),
]

# Code keywords to distinguish code from pure English prose
_JS_CODE_KEYWORDS = frozenset({
    "function", "const", "let", "var", "import", "export", "class", "return",
    "if", "else", "for", "while", "switch", "case", "default", "try", "catch",
    "finally", "async", "await", "new", "this", "typeof", "instanceof", "require",
    "module.exports", "console.log"
})


def is_placeholder_content(text: str) -> tuple[bool, str]:
    """Detect if the content contains lazy placeholders or TODO stubs instead of real code."""
    if not text or not text.strip():
        return True, "Content is empty"

    stripped = text.strip()

    # Exact placeholder phrases
    for pat in _PLACEHOLDER_PATTERNS:
        match = pat.search(stripped)
        if match:
            return True, f"Detected placeholder phrase: '{match.group(0)}'"

    # Short content check (< 50 chars) without standard code structure
    if len(stripped) < 50:
        lower = stripped.lower()
        if any(p in lower for p in ("code here", "updated code", "todo", "placeholder")):
            return True, f"Content is a short placeholder: '{stripped}'"

    return False, ""


def _normalize_lang(language_or_path: str) -> str:
    """Normalize file extension, filename, or language identifier to canonical extension without dot."""
    raw = language_or_path.strip().lower()
    if "/" in raw or "\\" in raw or "." in raw:
        ext = Path(raw).suffix.lower()
        if ext:
            raw = ext
    if raw.startswith("."):
        raw = raw[1:]
    alias_map = {
        "python": "py",
        "javascript": "js",
        "typescript": "ts",
        "jsx": "jsx",
        "tsx": "tsx",
        "c++": "cpp",
        "csharp": "cs",
        "golang": "go",
        "json": "json",
    }
    return alias_map.get(raw, raw)


def syntax_check(language: str, source: str) -> tuple[bool, str]:
    """Unified syntax checker for arbitrary code sources across supported languages.

    Shared by both check_slice_syntax and check_projected_file_syntax (Phase 12.5 H2.1).
    """
    if source is None:
        return False, "Source content is None"

    norm_lang = _normalize_lang(language)

    # Empty string is valid syntax for Python/JS/C (empty module/file or deleted block)
    if not source.strip():
        if norm_lang == "json":
            return False, "JSON source cannot be empty"
        return True, ""

    if norm_lang in ("py", "pyw"):
        try:
            ast.parse(source, filename=language if language.endswith((".py", ".pyw")) else "<syntax_check>")
            return True, ""
        except SyntaxError as exc:
            return False, f"Python syntax error at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return False, f"Python parse error: {exc}"

    if norm_lang == "json":
        try:
            json.loads(source)
            return True, ""
        except json.JSONDecodeError as exc:
            return False, f"JSON syntax error at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return False, f"JSON parse error: {exc}"

    if norm_lang in ("js", "jsx", "ts", "tsx", "mjs", "cjs"):
        open_braces = source.count("{")
        close_braces = source.count("}")
        open_parens = source.count("(")
        close_parens = source.count(")")
        open_brackets = source.count("[")
        close_brackets = source.count("]")

        if open_braces != close_braces:
            return False, f"Unbalanced curly braces in {norm_lang}: {open_braces} open vs {close_braces} closed"
        if open_parens != close_parens:
            return False, f"Unbalanced parentheses in {norm_lang}: {open_parens} open vs {close_parens} closed"
        if open_brackets != close_brackets:
            return False, f"Unbalanced square brackets in {norm_lang}: {open_brackets} open vs {close_brackets} closed"
        return True, ""

    if norm_lang in ("c", "cpp", "cc", "cxx", "h", "hpp", "java", "cs"):
        open_braces = source.count("{")
        close_braces = source.count("}")
        if open_braces != close_braces:
            return False, f"Unbalanced curly braces in {norm_lang}: {open_braces} open vs {close_braces} closed"
        return True, ""

    return True, ""


# ── Layered Syntax Checks (Phase 12.5 H2) ──────────────────────────────────
# Two NAMED layers calling the shared syntax_check helper with different sources:
# Layer 1 (check_slice_syntax): Inspects replacement slice in isolation (fast, catches broken patch early).
# Layer 2 (check_projected_file_syntax): Inspects in-memory projected file (catches context / boundary breakage).

def check_slice_syntax(path_or_lang: str, slice_code: str) -> tuple[bool, str]:
    """Layer 1: Verify replacement slice syntax in isolation (Phase 12.5 H2.1).

    Fast check to detect malformed patches before attempting projection or touching disk.
    For Python slices that belong inside indented blocks (methods/functions), applies
    dedent normalization so valid nested code is not rejected on IndentationError.
    """
    if not slice_code or not slice_code.strip():
        # Deleting a range or empty replacement is syntactically valid in isolation
        return True, ""

    norm_lang = _normalize_lang(path_or_lang)
    if norm_lang in ("py", "pyw"):
        # Try raw slice first
        ok, err = syntax_check(norm_lang, slice_code)
        if ok:
            return True, ""
        # If indentation error, dedent and retry (common for indented function/class slices)
        if "indent" in err.lower():
            dedented = textwrap.dedent(slice_code)
            ok_dedent, err_dedent = syntax_check(norm_lang, dedented)
            if ok_dedent:
                return True, ""
            return False, f"Slice syntax error: {err_dedent}"
        return False, f"Slice syntax error: {err}"

    ok, err = syntax_check(norm_lang, slice_code)
    if not ok:
        return False, f"Slice syntax error: {err}"
    return True, ""


def check_projected_file_syntax(path: str, projected_content: str) -> tuple[bool, str]:
    """Layer 2: Verify syntax of the full file with patch projected in-memory (Phase 12.5 H2.1).

    Catches contextual breakage across range boundaries (e.g. slice is valid alone
    but leaves surrounding braces unbalanced, breaks outer indentation, or introduces
    orphaned control-flow keywords).
    """
    if not projected_content or not projected_content.strip():
        return False, "Projected file content is empty"

    # Also run language prose check for JS/TS if present
    ok, err = validate_language_syntax(path, projected_content)
    if not ok:
        return False, f"Projected file syntax error: {err}"
    return True, ""


def validate_language_syntax(path: str, content: str) -> tuple[bool, str]:
    """Verify that file content parses or conforms to expected syntax for its extension."""
    if not content or not content.strip():
        return False, "File content is empty"

    ext = Path(path).suffix.lower()
    ok, err = syntax_check(ext or path, content)
    if not ok:
        return False, err

    # Check if file is pure English sentences masquerading as code (like CV prose)
    if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if len(lines) > 0 and len(content) < 500:
            words = set(re.findall(r"\b[a-zA-Z_]\w*\b", content))
            has_js_keywords = any(kw in words for kw in _JS_CODE_KEYWORDS)
            has_code_puncts = any(c in content for c in (";", "{", "}", "=", "(", ")", "=>"))
            if not has_js_keywords and not has_code_puncts:
                return False, f"File '{path}' contains conversational prose rather than valid JavaScript/TypeScript code"

    return True, ""


def is_truncated_content(content: str) -> tuple[bool, str]:
    """Detect if content appears truncated (e.g. cut off mid-statement at EOF or missing block closers)."""
    if not content or not content.strip():
        return False, ""

    stripped = content.strip()
    lines = [l for l in content.splitlines() if l.strip()]
    if not lines:
        return False, ""
    last_line = lines[-1].strip()

    # Unbalanced curly braces usually indicate mid-block cut-off
    if content.count("{") > content.count("}"):
        return True, f"Truncated content: unclosed block ({content.count('{')} '{{' vs {content.count('}')} '}}')"

    # Unbalanced parentheses or brackets
    if content.count("(") > content.count(")"):
        return True, f"Truncated content: unclosed parenthesis ({content.count('(')} '(' vs {content.count(')')} ')')"
    if content.count("[") > content.count("]"):
        return True, f"Truncated content: unclosed bracket ({content.count('[')} '[' vs {content.count(']')} ']')"

    # Ends mid-expression, mid-keyword, or trailing operator
    truncated_endings = (
        re.compile(r"\b(def|class|function|import|from|return|const|let|var|if|else|elif|while|for|try|except|finally|with|async|await)\s*$", re.IGNORECASE),
        re.compile(r"\b(def|class)\s+[a-zA-Z_]\w*\s*(\([^)]*\))?\s*:\s*$", re.IGNORECASE),
        re.compile(r"[=+\-*/&|,({\[\\.]\s*$"),
        re.compile(r"\b(and|or|in|is|not|as)\s*$", re.IGNORECASE),
    )
    for pat in truncated_endings:
        if pat.search(last_line):
            return True, f"Truncated content: file ends abruptly with '{last_line[:40]}'"

    # Mid-statement member access e.g. "self." or "response."
    if last_line.endswith("."):
        return True, f"Truncated content: file ends with trailing dot '{last_line[:40]}'"

    # Indented line at EOF without statement termination in Python
    raw_last = lines[-1]
    indent = len(raw_last) - len(raw_last.lstrip())
    if indent > 0:
        if last_line.endswith((":", ",", "\\", "(", "[", "{", "+", "-", "*", "/", "=")):
            return True, f"Truncated content: indented block ends mid-statement '{last_line[:40]}'"

    if re.search(r"(//|#)\s*(continuing|\.\.\.|to be continued)", last_line, re.IGNORECASE):
        return True, f"Truncated content: ending comment stub '{last_line}'"

    # Unclosed triple quotes in python
    triple_double = content.count('"""')
    triple_single = content.count("'''")
    if triple_double % 2 != 0 or triple_single % 2 != 0:
        return True, "Truncated content: unclosed multi-line string literal"

    # Unclosed single/double quotes on the last line
    stripped_slashes = re.sub(r'\\.', '', last_line)
    d_quotes = stripped_slashes.count('"')
    s_quotes = stripped_slashes.count("'")
    if (d_quotes % 2 != 0 and '"""' not in last_line) or (s_quotes % 2 != 0 and "'''" not in last_line):
        return True, f"Truncated content: unclosed string literal on last line '{last_line[:40]}'"

    return False, ""


def check_cross_turn_contamination(
    content: str,
    conversation_messages: list[Any] | None = None,
    extra_texts: list[str] | None = None,
) -> tuple[bool, str]:
    """Detect if file content is an accidental copy/echo of earlier assistant prose or chat history (AUD-003).

    Provenance-aware: isolates prior assistant conversational prose and checks against
    staged content without blocking ordinary source repetition from user instructions
    or file inspection tools.
    """
    if not content or not content.strip():
        return False, ""

    stripped_content = content.strip()
    sources_to_check: list[str] = []

    if conversation_messages:
        for m in conversation_messages:
            role = ""
            text = ""
            provenance = ""
            if isinstance(m, dict):
                role = str(m.get("role") or "")
                text = str(m.get("content") or "")
                provenance = str(m.get("provenance") or "")
            elif hasattr(m, "content"):
                role = str(getattr(m, "role", "") or "")
                text = str(getattr(m, "content") or "")
                provenance = str(getattr(m, "provenance", "") or "")

            # Prioritize assistant conversational prose; ignore user instructions or system prompts
            # so ordinary user code repetition is not blocked (AUD-003)
            is_assistant = role == "assistant" or provenance in ("assistant_prose", "assistant")
            if is_assistant and text and len(text.strip()) > 30:
                # Strip markdown code blocks from assistant prose to isolate conversational sentences
                prose_only = re.sub(r"```[\s\S]*?```", "", text).strip()
                if len(prose_only) > 30:
                    sources_to_check.append(prose_only)
                elif len(text.strip()) > 30:
                    sources_to_check.append(text.strip())
            elif not role and text and len(text.strip()) > 30:
                # Fallback for generic text blocks
                sources_to_check.append(text.strip())

    if extra_texts:
        for t in extra_texts:
            if t and len(t.strip()) > 30:
                sources_to_check.append(t.strip())

    for source in sources_to_check:
        # Check whole content similarity
        ratio = difflib.SequenceMatcher(None, stripped_content, source).ratio()
        if ratio > 0.8:
            return True, "Content matches an unrelated earlier response; regenerate."

        # Check line-by-line similarity for prose lines
        for line in stripped_content.splitlines():
            line_str = line.strip()
            if len(line_str) > 40:
                line_ratio = difflib.SequenceMatcher(None, line_str, source).ratio()
                if line_ratio > 0.85:
                    return True, f"Line matches prior chat prose ('{line_str[:50]}...'): cross-turn contamination detected."

    return False, ""


def validate_file_target(
    path: str,
    plan_text: str = "",
    user_query: str = "",
) -> tuple[bool, str]:
    """Check if the target file matches the active task domain or appears hallucinated."""
    if not path:
        return False, "Target path is empty"

    path_lower = path.lower()
    base_name = Path(path).name.lower()
    ext = Path(path).suffix.lower()

    # Generic tech names created as root files
    tech_names = {"node.js", "three.js", "react.js", "vue.js", "angular.js", "express.js", "next.js"}
    if base_name in tech_names:
        context = (plan_text + " " + user_query).lower()
        # If user explicitly asked to create node.js or three.js, allow it
        if base_name not in context and base_name.replace(".js", "") not in context:
            return False, f"File '{base_name}' is a known technology name and ungrounded in current task. Do not create library placeholder files."

    return True, ""


def validate_content_integrity(
    path: str,
    content: str,
    conversation_messages: list[Any] | None = None,
    extra_texts: list[str] | None = None,
    plan_text: str = "",
    user_query: str = "",
) -> tuple[str, str | None]:
    """Master integrity check returning (integrity_status, warning_message).
    
    Status can be:
    - 'valid': passed all checks
    - 'incomplete': placeholders or truncation detected
    - 'suspicious': cross-turn contamination or off-target file
    - 'blocked': critical syntax error or invalid structure
    """
    # 1. Target grounding
    target_ok, target_msg = validate_file_target(path, plan_text, user_query)
    if not target_ok:
        return "suspicious", target_msg

    # 2. Placeholders
    is_ph, ph_msg = is_placeholder_content(content)
    if is_ph:
        return "incomplete", f"Placeholder content detected in '{path}': {ph_msg}"

    # 3. Truncation
    is_trunc, trunc_msg = is_truncated_content(content)
    if is_trunc:
        return "incomplete", f"Truncated code detected in '{path}': {trunc_msg}"

    # 3b. Undersized implementation check for complex tasks (e.g. 135-char OAuth2 flow)
    stripped_len = len(content.strip())
    q_lower = (user_query or "").lower()
    is_complex_auth = any(kw in q_lower for kw in ("oauth", "oauth2", "providers", "rate limiting", "session management", "token refresh"))
    if is_complex_auth and stripped_len < 250:
        missing = []
        if "provider" in q_lower and not re.search(r"\b(google|github|provider)\b", content, re.IGNORECASE):
            missing.append("providers (Google/GitHub)")
        if "token refresh" in q_lower and not re.search(r"\b(refresh|token)\b", content, re.IGNORECASE):
            missing.append("token refresh")
        if "session" in q_lower and not re.search(r"\b(session)\b", content, re.IGNORECASE):
            missing.append("session management")
        if "rate limit" in q_lower and not re.search(r"\b(rate_limit|rate\s+limit|limiter)\b", content, re.IGNORECASE):
            missing.append("rate limiting")
        if missing or stripped_len <= 150:
            return "incomplete", f"Incomplete or truncated implementation staged for '{path}' ({stripped_len} chars): missing required components ({', '.join(missing) if missing else 'stub implementation'})."

    # 4. Cross-turn contamination
    is_contam, contam_msg = check_cross_turn_contamination(content, conversation_messages, extra_texts)
    if is_contam:
        return "blocked", f"Cross-turn contamination in '{path}': {contam_msg}"

    # 5. Language syntax
    syntax_ok, syntax_msg = validate_language_syntax(path, content)
    if not syntax_ok:
        return "blocked", f"Syntax validation failed for '{path}': {syntax_msg}"

    return "valid", None
