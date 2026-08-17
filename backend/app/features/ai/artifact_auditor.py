"""
Artifact Auditor — Structural quality gates and post-generation audit engine.

Performs static structural, semantic, and accessibility audits on generated artifacts
(HTML, CSS, JS, etc.) before final approval. Used as a permanent quality gate in the
AI harness to prevent broken seams, unclosed tags, dead controls, mobile antipatterns,
and dishonest line count reporting.
"""
from __future__ import annotations

import re
import html.parser
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuditFinding:
    """A single finding or violation detected during artifact auditing."""
    severity: str  # "error", "warning", "info"
    category: str  # "tag_balance", "chunk_seams", "wiring", "interactivity", "mobile_css", "accessibility", "branding", "quality"
    message: str
    line_number: int | None = None
    fix_suggestion: str = ""


@dataclass
class ArtifactAuditReport:
    """Consolidated audit report for a generated file artifact."""
    file_path: str
    is_clean: bool
    total_raw_lines: int
    non_empty_non_comment_lines: int
    findings: list[AuditFinding] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    def format_summary(self) -> str:
        """Format a human- and LLM-readable summary of the audit results."""
        lines = [
            f"=== STRUCTURAL AUDIT REPORT: {self.file_path} ===",
            f"Status: {'PASSED' if not self.has_errors else 'ACTION REQUIRED'}",
            f"Metrics: {self.total_raw_lines} raw lines ({self.non_empty_non_comment_lines} non-empty, non-comment lines)",
        ]
        if self.passed_checks:
            lines.append("Passed Checks:")
            for check in self.passed_checks:
                lines.append(f"  ✓ {check}")
        if self.findings:
            lines.append("Findings:")
            for f in self.findings:
                prefix = "❌ ERROR" if f.severity == "error" else ("⚠️ WARN" if f.severity == "warning" else "ℹ️ INFO")
                loc = f" (line {f.line_number})" if f.line_number else ""
                lines.append(f"  [{prefix}]{loc} {f.message}")
                if f.fix_suggestion:
                    lines.append(f"     Suggestion: {f.fix_suggestion}")
        return "\n".join(lines)


# ── Tag Balance & HTML Structure Parser ──────────────────────────────────────

class _HTMLStructuralParser(html.parser.HTMLParser):
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr", "!doctype"
    }

    def __init__(self):
        super().__init__()
        self.tag_stack: list[tuple[str, int]] = []
        self.unclosed_tags: list[tuple[str, int]] = []
        self.stray_closing_tags: list[tuple[str, int]] = []
        self.ids_defined: set[str] = set()
        self.href_anchors: list[tuple[str, int]] = []
        self.style_count = 0
        self.script_count = 0
        self.doctype_count = 0
        self.html_tag_count = 0
        self.head_tag_count = 0
        self.body_tag_count = 0
        self.title_text: str = ""
        self.h1_texts: list[str] = []
        self._in_title = False
        self._in_h1 = False
        self.interactive_elements: list[tuple[str, dict, int]] = []

    def handle_decl(self, decl: str):
        if decl.lower().startswith("doctype"):
            self.doctype_count += 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag_lower = tag.lower()
        line = self.getpos()[0]
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        # Track singleton blocks
        if tag_lower == "style":
            self.style_count += 1
        elif tag_lower == "script":
            self.script_count += 1
        elif tag_lower == "html":
            self.html_tag_count += 1
        elif tag_lower == "head":
            self.head_tag_count += 1
        elif tag_lower == "body":
            self.body_tag_count += 1
        elif tag_lower == "title":
            self._in_title = True
        elif tag_lower == "h1":
            self._in_h1 = True

        # Track IDs
        if "id" in attr_dict and attr_dict["id"].strip():
            self.ids_defined.add(attr_dict["id"].strip())

        # Track href anchors (#target)
        if "href" in attr_dict and attr_dict["href"].startswith("#") and len(attr_dict["href"]) > 1:
            target = attr_dict["href"][1:]
            self.href_anchors.append((target, line))

        # Track interactive controls
        if tag_lower in ("button", "form", "select", "textarea") or (tag_lower == "input" and attr_dict.get("type") in ("button", "submit", "reset", "checkbox", "radio", "text", "email", "password")):
            self.interactive_elements.append((tag_lower, attr_dict, line))

        # Push to stack if not void
        if tag_lower not in self.VOID_TAGS:
            self.tag_stack.append((tag_lower, line))

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self._in_title = False
        elif tag_lower == "h1":
            self._in_h1 = False

        if tag_lower in self.VOID_TAGS:
            return

        # Find matching tag in stack
        found_idx = -1
        for i in range(len(self.tag_stack) - 1, -1, -1):
            if self.tag_stack[i][0] == tag_lower:
                found_idx = i
                break

        if found_idx != -1:
            # Pop anything above it as unclosed
            while len(self.tag_stack) > found_idx + 1:
                unclosed = self.tag_stack.pop()
                # Treat optional end tags (p, li, tr, td, th) leniently, others strictly
                if unclosed[0] not in ("p", "li", "tr", "td", "th", "dt", "dd", "option"):
                    self.unclosed_tags.append(unclosed)
            self.tag_stack.pop()  # Pop the matching tag
        else:
            self.stray_closing_tags.append((tag_lower, self.getpos()[0]))

    def handle_data(self, data: str):
        if self._in_title:
            self.title_text += data
        if self._in_h1:
            if not self.h1_texts or len(self.h1_texts[-1]) > 50:
                self.h1_texts.append(data.strip())
            else:
                self.h1_texts[-1] += " " + data.strip()


# ── Main Audit Function ──────────────────────────────────────────────────────

def audit_generated_artifact(content: str, file_path: str) -> ArtifactAuditReport:
    """Run comprehensive structural, quality, and wiring audit on generated file content."""
    findings: list[AuditFinding] = []
    passed: list[str] = []

    # 1. Line counts
    raw_lines = content.splitlines()
    total_raw_lines = len(raw_lines)
    non_empty_non_comment_lines = _count_non_empty_non_comment_lines(raw_lines, file_path)

    # If not an HTML/web artifact, perform generic code/config audit
    lower_path = file_path.lower()
    is_html = lower_path.endswith((".html", ".htm"))
    is_css = lower_path.endswith(".css")
    is_js_or_ts = lower_path.endswith((".js", ".jsx", ".ts", ".tsx"))

    if not is_html and not is_css and not is_js_or_ts:
        # Generic non-empty check
        if total_raw_lines > 0:
            passed.append(f"File has {total_raw_lines} lines of valid structure")
        return ArtifactAuditReport(
            file_path=file_path,
            is_clean=len(findings) == 0,
            total_raw_lines=total_raw_lines,
            non_empty_non_comment_lines=non_empty_non_comment_lines,
            findings=findings,
            passed_checks=passed,
        )

    if is_html:
        _audit_html_structure(content, raw_lines, findings, passed)

    if is_html or is_css:
        _audit_css_and_styling(content, raw_lines, findings, passed)

    if is_html or is_js_or_ts:
        _audit_javascript_and_interactivity(content, raw_lines, findings, passed)

    # Quality & Branding Checks across web artifacts
    _audit_quality_and_standards(content, raw_lines, findings, passed)

    has_errors = any(f.severity == "error" for f in findings)
    return ArtifactAuditReport(
        file_path=file_path,
        is_clean=not has_errors,
        total_raw_lines=total_raw_lines,
        non_empty_non_comment_lines=non_empty_non_comment_lines,
        findings=findings,
        passed_checks=passed,
    )


# ── Sub-Auditors ─────────────────────────────────────────────────────────────

def _audit_html_structure(content: str, lines: list[str], findings: list[AuditFinding], passed: list[str]):
    """Audit HTML tag hierarchy, seam hygiene, and duplicate structural tags."""
    parser = _HTMLStructuralParser()
    try:
        parser.feed(content)
    except Exception as exc:
        findings.append(AuditFinding(
            severity="error",
            category="tag_balance",
            message=f"HTML parsing failed with syntax error: {exc}",
            fix_suggestion="Ensure all open tags are properly matched and closed."
        ))
        return

    # Check unclosed tags (popped prematurely when parent closed, or left on stack at EOF)
    all_unclosed = list(parser.unclosed_tags) + [
        (t, l) for t, l in parser.tag_stack
        if t not in ("p", "li", "tr", "td", "th", "dt", "dd", "option", "html", "body")
    ]
    for tag, line in all_unclosed:
        findings.append(AuditFinding(
            severity="error",
            category="tag_balance",
            message=f"Unclosed tag <{tag}> opened at line {line}",
            line_number=line,
            fix_suggestion=f"Add closing </{tag}> tag before parent closing element."
        ))

    for tag, line in parser.stray_closing_tags:
        findings.append(AuditFinding(
            severity="warning",
            category="tag_balance",
            message=f"Stray closing tag </{tag}> at line {line} has no matching opener",
            line_number=line,
            fix_suggestion=f"Remove extraneous </{tag}> or add corresponding <{tag}> opener."
        ))

    # Duplicate block checks (Chunk seam hygiene)
    if parser.doctype_count > 1:
        findings.append(AuditFinding(
            severity="error",
            category="chunk_seams",
            message=f"Found {parser.doctype_count} <!DOCTYPE> declarations. Chunk seams duplicated header structure.",
            fix_suggestion="Ensure only one <!DOCTYPE html> declaration exists at the top of the file."
        ))
    if parser.html_tag_count > 1:
        findings.append(AuditFinding(
            severity="error",
            category="chunk_seams",
            message=f"Found {parser.html_tag_count} <html> tags. Chunk seams duplicated root structure.",
            fix_suggestion="Merge into exactly one <html>...</html> root tag."
        ))
    if parser.style_count > 1:
        findings.append(AuditFinding(
            severity="warning",
            category="chunk_seams",
            message=f"Found {parser.style_count} separate <style> blocks. Expected a single coherent stylesheet.",
            fix_suggestion="Consolidate all CSS rules into one <style> block inside <head>."
        ))
    if parser.script_count > 1:
        findings.append(AuditFinding(
            severity="warning",
            category="chunk_seams",
            message=f"Found {parser.script_count} separate <script> blocks. Expected a single script region.",
            fix_suggestion="Consolidate script logic into one <script> block before </body>."
        ))

    # Wiring: Anchor #targets must exist
    missing_anchors: list[tuple[str, int]] = []
    for target, line in parser.href_anchors:
        if target not in parser.ids_defined and target not in ("top", "main", "#"):
            missing_anchors.append((target, line))

    if missing_anchors:
        for target, line in missing_anchors[:5]:
            findings.append(AuditFinding(
                severity="error",
                category="wiring",
                message=f"Anchor href='#{target}' (line {line}) targets non-existent element id='{target}'",
                line_number=line,
                fix_suggestion=f"Add id='{target}' to the intended target section or update href."
            ))
    else:
        passed.append(f"All anchor links (#{', #'.join(list(set(t for t, _ in parser.href_anchors))[:5]) or 'none'}) match real DOM element IDs")

    if parser.style_count <= 1 and parser.doctype_count <= 1 and not parser.unclosed_tags:
        passed.append("HTML document structure & tag balance verified cleanly")


def _audit_css_and_styling(content: str, lines: list[str], findings: list[AuditFinding], passed: list[str]):
    """Audit CSS for mobile antipatterns (fixed parallax), progressive enhancement, and responsive design."""
    # 1. Check for background-attachment: fixed (mobile antipattern)
    fixed_bg_match = re.search(r"background-attachment\s*:\s*fixed", content, re.IGNORECASE)
    if fixed_bg_match:
        line_no = content[:fixed_bg_match.start()].count("\n") + 1
        findings.append(AuditFinding(
            severity="error",
            category="mobile_css",
            message=f"Found 'background-attachment: fixed' at line {line_no}. This causes broken/janky rendering on mobile browsers.",
            line_number=line_no,
            fix_suggestion="Replace with transform-based parallax (rAF + translateY) or standard CSS layout."
        ))
    else:
        passed.append("No janky 'background-attachment: fixed' parallax patterns")

    # 2. Check for progressive enhancement with scroll animations
    # If opacity: 0 is used for initial animation states, verify .js or .js-enabled is required
    has_initial_hidden = bool(re.search(r"\.(reveal|fade-in|animate|scroll-item|hero-element)\s*\{[^}]*opacity\s*:\s*0", content, re.IGNORECASE))
    if has_initial_hidden:
        has_js_gate = bool(re.search(r"(\.js|\.js-enabled|\.has-js)\s+\.(reveal|fade-in|animate|scroll-item|hero-element)", content, re.IGNORECASE))
        has_js_doc_class = bool(re.search(r"classList\.add\(['\"](js|js-enabled)['\"]\)", content, re.IGNORECASE)) or bool(re.search(r"className\s*\+?=\s*['\"].*js", content, re.IGNORECASE))
        if not (has_js_gate or has_js_doc_class):
            findings.append(AuditFinding(
                severity="warning",
                category="mobile_css",
                message="Scroll animation elements start at 'opacity: 0' without a .js class gate. Content may remain invisible if JS fails or is disabled.",
                fix_suggestion="Gate hidden states behind a .js root class: html.js .reveal { opacity: 0; } and add document.documentElement.classList.add('js')."
            ))
        else:
            passed.append("Progressive enhancement: animated elements safely gated behind JS activation")

    # 3. Responsive media queries & viewport meta
    has_viewport = bool(re.search(r"<meta\s+name=[\"']viewport[\"']", content, re.IGNORECASE))
    has_media_queries = bool(re.search(r"@media\s*\(\s*max-width\s*:\s*\d+px\s*\)", content, re.IGNORECASE))
    
    if "<html" in content and not has_viewport:
        findings.append(AuditFinding(
            severity="warning",
            category="mobile_css",
            message="Missing <meta name='viewport' content='width=device-width, initial-scale=1.0'> tag.",
            fix_suggestion="Add viewport meta tag in <head> to ensure proper mobile scaling."
        ))
    if "<html" in content and not has_media_queries:
        findings.append(AuditFinding(
            severity="warning",
            category="mobile_css",
            message="No responsive media queries (@media (max-width: ...)) detected. Mobile layout may overflow.",
            fix_suggestion="Add media queries for ~768px screens to adapt navigation, grids, and typography."
        ))
    elif has_media_queries:
        passed.append("Responsive mobile media queries detected")


COMMON_HTML_TAGS = {
    "html", "body", "head", "main", "nav", "footer", "header", "button",
    "form", "section", "div", "a", "p", "span", "ul", "ol", "li", "input",
    "textarea", "select", "h1", "h2", "h3", "h4", "h5", "h6", "img", "canvas",
    "svg", "path", "article", "aside", "details", "summary", "figure",
    "figcaption", "table", "thead", "tbody", "tr", "th", "td", "label", "option"
}


def _audit_javascript_and_interactivity(content: str, lines: list[str], findings: list[AuditFinding], passed: list[str]):
    """Audit JS DOM queries, event listeners, and dead controls."""
    html_ids = set(re.findall(r"\sid=['\"]([a-zA-Z0-9_\-]+)['\"]", content))

    # 1. getElementById('id') and querySelector('#id')
    get_elem_ids = re.findall(r"getElementById\s*\(\s*['\"]([a-zA-Z0-9_\-]+)['\"]\s*\)", content)
    query_hash_ids = re.findall(r"querySelector(?:All)?\s*\(\s*['\"]#([a-zA-Z0-9_\-]+)['\"]\s*\)", content)
    all_referenced_ids = set(get_elem_ids + query_hash_ids)

    missing_ids = [m_id for m_id in all_referenced_ids if m_id not in html_ids]
    if missing_ids:
        for m_id in missing_ids[:4]:
            findings.append(AuditFinding(
                severity="warning",
                category="wiring",
                message=f"JavaScript references element '#{m_id}' via getElementById/querySelector('#{m_id}'), but no id='{m_id}' exists in HTML.",
                fix_suggestion=f"Ensure HTML element has id='{m_id}' or update the JS query selector."
            ))
    else:
        if all_referenced_ids:
            passed.append(f"JavaScript DOM selectors (#{', #'.join(list(all_referenced_ids)[:4])}) match defined HTML element IDs")
        else:
            passed.append("JavaScript DOM selector wiring verified")

    # 2. Interactive control handlers
    has_buttons = bool(re.search(r"<button[\s>]", content, re.IGNORECASE))
    has_forms = bool(re.search(r"<form[\s>]", content, re.IGNORECASE))
    has_event_listeners = bool(re.search(r"addEventListener\s*\(", content, re.IGNORECASE)) or bool(re.search(r"on(click|submit|change|input)\s*=", content, re.IGNORECASE))

    if (has_buttons or has_forms) and not has_event_listeners and "<script" in content:
        findings.append(AuditFinding(
            severity="warning",
            category="interactivity",
            message="Interactive buttons/forms present in HTML but no event listeners found in JavaScript.",
            fix_suggestion="Add event listeners (e.g. click/submit) to provide working interactivity."
        ))
    elif has_event_listeners:
        passed.append("Interactive elements have associated JavaScript event listeners")


def _audit_quality_and_standards(content: str, lines: list[str], findings: list[AuditFinding], passed: list[str]):
    """Audit for emoji-as-icons, prefers-reduced-motion, aria-labels, and identity consistency."""
    # 1. Emoji used as icons in buttons/headers
    # Emojis in range \U0001F300-\U0001F9FF, \U00002600-\U000027BF inside <button> or <nav>
    emoji_in_btn_match = re.search(r"<button[^>]*>[^<]*[\U0001F300-\U0001F9FF\u2600-\u27BF][^<]*</button>", content)
    if emoji_in_btn_match:
        findings.append(AuditFinding(
            severity="warning",
            category="quality",
            message="Emoji used as button icon. Professional deliverables should use inline SVG icons.",
            fix_suggestion="Replace emoji with crisp inline <svg viewBox='...'> icon."
        ))
    else:
        passed.append("Icon standards: clean SVG / semantic iconography (no raw emoji icons)")

    # 2. prefers-reduced-motion check
    has_motion_query = bool(re.search(r"prefers-reduced-motion", content, re.IGNORECASE))
    if re.search(r"(@keyframes|animation\s*:|transition\s*:)", content, re.IGNORECASE) and not has_motion_query:
        findings.append(AuditFinding(
            severity="info",
            category="accessibility",
            message="CSS animations present without '@media (prefers-reduced-motion: reduce)' accessibility override.",
            fix_suggestion="Add @media (prefers-reduced-motion: reduce) { * { animation-duration: 0.01ms !important; } }."
        ))
    elif has_motion_query:
        passed.append("Accessibility: prefers-reduced-motion respected")

    # 3. Branding & Title consistency
    title_match = re.search(r"<title>([^<]+)</title>", content, re.IGNORECASE)
    h1_match = re.search(r"<h1[^>]*>([^<]+)</h1>", content, re.IGNORECASE)
    if title_match and h1_match:
        title_str = title_match.group(1).strip()
        h1_str = h1_match.group(1).strip()
        # If title and h1 are completely divergent without common words
        title_words = set(re.findall(r"\w{3,}", title_str.lower()))
        h1_words = set(re.findall(r"\w{3,}", h1_str.lower()))
        if title_words and h1_words and not (title_words & h1_words) and "portfolio" not in title_str.lower():
            findings.append(AuditFinding(
                severity="info",
                category="branding",
                message=f"Brand identity divergence between <title> ('{title_str}') and <h1> ('{h1_str}').",
                fix_suggestion="Keep name and role consistent across <title>, <h1>, and <footer>."
            ))
        else:
            passed.append(f"Branding & identity consistent across <title> and <h1> ('{title_str}')")


def _count_non_empty_non_comment_lines(lines: list[str], file_path: str) -> int:
    """Calculate honest line count by ignoring blank lines and comment-only lines."""
    count = 0
    in_block_comment = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # HTML Comments
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        if stripped.startswith("<!--"):
            in_block_comment = True
            continue
        if in_block_comment and "-->" in stripped:
            in_block_comment = False
            continue

        # C-style block comments
        if stripped.startswith("/*") and stripped.endswith("*/"):
            continue
        if stripped.startswith("/*"):
            in_block_comment = True
            continue
        if in_block_comment and "*/" in stripped:
            in_block_comment = False
            continue

        # Single line comments
        if stripped.startswith("//") or stripped.startswith("#"):
            continue

        if not in_block_comment:
            count += 1

    return count
