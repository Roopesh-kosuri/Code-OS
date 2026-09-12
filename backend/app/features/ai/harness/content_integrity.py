from __future__ import annotations

import ast
import difflib
import json
import logging
import re
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


def validate_language_syntax(path: str, content: str) -> tuple[bool, str]:
    """Verify that file content parses or conforms to expected syntax for its extension."""
    if not content or not content.strip():
        return False, "File content is empty"

    ext = Path(path).suffix.lower()

    # Python syntax verification
    if ext in (".py", ".pyw"):
        try:
            ast.parse(content, filename=path)
        except SyntaxError as exc:
            return False, f"Python syntax error at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return False, f"Python parse error: {exc}"
        return True, ""

    # JSON syntax verification
    if ext == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return False, f"JSON syntax error at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return False, f"JSON parse error: {exc}"
        return True, ""

    # JavaScript / TypeScript sanity
    if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        # Check brace, parenthesis, bracket balance
        open_braces = content.count("{")
        close_braces = content.count("}")
        open_parens = content.count("(")
        close_parens = content.count(")")
        open_brackets = content.count("[")
        close_brackets = content.count("]")

        if open_braces != close_braces:
            return False, f"Unbalanced curly braces in {ext}: {open_braces} open vs {close_braces} closed"
        if open_parens != close_parens:
            return False, f"Unbalanced parentheses in {ext}: {open_parens} open vs {close_parens} closed"
        if open_brackets != close_brackets:
            return False, f"Unbalanced square brackets in {ext}: {open_brackets} open vs {close_brackets} closed"

        # Check if file is pure English sentences masquerading as code (like CV prose)
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if len(lines) > 0 and len(content) < 500:
            words = set(re.findall(r"\b[a-zA-Z_]\w*\b", content))
            has_js_keywords = any(kw in words for kw in _JS_CODE_KEYWORDS)
            has_code_puncts = any(c in content for c in (";", "{", "}", "=", "(", ")", "=>"))
            # If no JS keywords and no code punctuation, it is pure prose
            if not has_js_keywords and not has_code_puncts:
                return False, f"File '{path}' contains conversational prose rather than valid JavaScript/TypeScript code"

        return True, ""

    # C / C++ / Java / C#
    if ext in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".java", ".cs"):
        open_braces = content.count("{")
        close_braces = content.count("}")
        if open_braces != close_braces:
            return False, f"Unbalanced curly braces in {ext}: {open_braces} open vs {close_braces} closed"
        return True, ""

    return True, ""


def is_truncated_content(content: str) -> tuple[bool, str]:
    """Detect if content appears truncated (e.g. cut off mid-statement at EOF)."""
    if not content or not content.strip():
        return False, ""

    stripped = content.strip()
    last_line = stripped.splitlines()[-1].strip()

    # Unbalanced curly braces usually indicate mid-block cut-off
    if content.count("{") > content.count("}"):
        return True, f"Truncated content: unclosed block ({content.count('{')} '{{' vs {content.count('}')} '}}')"

    # Ends mid-expression or mid-keyword
    truncated_endings = (
        re.compile(r"\b(def|class|function|import|from|return|const|let|var|if|else|while|for)\s*$", re.IGNORECASE),
        re.compile(r"\b(def|class)\s+[a-zA-Z_]\w*\s*(\([^)]*\))?\s*:\s*$", re.IGNORECASE),
        re.compile(r"[=+\-*/&|,({\[]\s*$"),
    )
    for pat in truncated_endings:
        if pat.search(last_line):
            return True, f"Truncated content: file ends abruptly with '{last_line[:40]}'"

    if re.search(r"(//|#)\s*(continuing|\.\.\.)", last_line, re.IGNORECASE):
        return True, f"Truncated content: ending comment stub '{last_line}'"

    # Unclosed triple quotes in python
    triple_double = content.count('"""')
    triple_single = content.count("'''")
    if triple_double % 2 != 0 or triple_single % 2 != 0:
        return True, "Truncated content: unclosed multi-line string literal"

    return False, ""


def check_cross_turn_contamination(
    content: str,
    conversation_messages: list[Any] | None = None,
    extra_texts: list[str] | None = None,
) -> tuple[bool, str]:
    """Detect if file content is an accidental copy/echo of earlier assistant prose or chat history."""
    if not content or not content.strip():
        return False, ""

    stripped_content = content.strip()
    sources_to_check: list[str] = []

    if conversation_messages:
        for m in conversation_messages:
            text = ""
            if isinstance(m, dict):
                if m.get("role") in ("assistant", "user"):
                    text = str(m.get("content") or "")
            elif hasattr(m, "content"):
                text = str(getattr(m, "content") or "")
            if text and len(text.strip()) > 30:
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

    # 4. Cross-turn contamination
    is_contam, contam_msg = check_cross_turn_contamination(content, conversation_messages, extra_texts)
    if is_contam:
        return "suspicious", f"Cross-turn contamination in '{path}': {contam_msg}"

    # 5. Language syntax
    syntax_ok, syntax_msg = validate_language_syntax(path, content)
    if not syntax_ok:
        return "blocked", f"Syntax validation failed for '{path}': {syntax_msg}"

    return "valid", None
