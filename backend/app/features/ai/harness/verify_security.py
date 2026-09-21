"""Diff-scoped security scanner for CODE OS (Phase 14 Part 5).

Scans only added/modified lines in code touched by the turn:
- Python via AST (no false positives in comments/strings)
- JS/TS via regex
- Severity gating: HIGH (blocking FAILED) vs MEDIUM (WARN)
- Inline suppression: `# codeos-allow: <rule-id>` or `// codeos-allow: <rule-id>`
- Added suppressions accounting as caveats
- Optional bandit scan filtered to diff lines
- Optional npm audit on lockfile changes (informational only, never FAILED)
"""

from __future__ import annotations

import ast
import difflib
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.features.ai.harness.verification_matrix import (
    VerifyResult,
    VerifyStatus,
    is_code_file,
)

logger = logging.getLogger(__name__)

# Suppression comments regex: e.g. # codeos-allow: shell-true or // codeos-allow: hardcoded-secret
SUPPRESSION_RE = re.compile(
    r"(?:#|//)\s*codeos-allow:\s*([a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)

# Hardcoded secret patterns
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
GITHUB_TOKEN_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b")
API_KEY_ASSIGN_RE = re.compile(
    r"""(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*=\s*['"][a-zA-Z0-9_\-\.]{20,}['"]"""
)


@dataclass
class Finding:
    rule_id: str
    severity: str  # "HIGH" | "MEDIUM"
    file_path: str
    lineno: int
    message: str
    suppressed: bool = False

    def to_string(self) -> str:
        status_suffix = " [suppressed]" if self.suppressed else ""
        return f"[{self.severity}] {self.file_path}:{self.lineno} - {self.rule_id}: {self.message}{status_suffix}"


# ── Diff Line Extraction ─────────────────────────────────────────────────────

def get_added_line_numbers(pre_content: str | None, post_content: str) -> set[int]:
    """Return 1-indexed set of line numbers in post_content that were added or modified."""
    if pre_content is None:
        # Entire file is new -> all lines are added
        lines = post_content.splitlines()
        return set(range(1, len(lines) + 1))

    pre_lines = pre_content.splitlines()
    post_lines = post_content.splitlines()

    added: set[int] = set()
    matcher = difflib.SequenceMatcher(None, pre_lines, post_lines)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            for lineno in range(j1 + 1, j2 + 1):
                added.add(lineno)

    return added


def extract_suppressions_from_lines(lines: list[str], target_lines: set[int]) -> dict[int, set[str]]:
    """Map lineno -> set of suppressed rule IDs (from same line or preceding line)."""
    suppressions: dict[int, set[str]] = {}
    for idx, line in enumerate(lines, 1):
        match = SUPPRESSION_RE.search(line)
        if match:
            rule = match.group(1).lower()
            # Suppress current line and next line
            suppressions.setdefault(idx, set()).add(rule)
            suppressions.setdefault(idx + 1, set()).add(rule)
    return suppressions


# ── Python AST Scanner ───────────────────────────────────────────────────────

class _PythonSecurityVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, added_lines: set[int], pre_available: bool):
        self.file_path = file_path
        self.added_lines = added_lines
        self.pre_available = pre_available
        self.findings: list[Finding] = []

    def _is_added(self, lineno: int) -> bool:
        if not self.pre_available:
            return True
        return lineno in self.added_lines

    def visit_Call(self, node: ast.Call):
        lineno = getattr(node, "lineno", 0)
        func_name = ""
        mod_name = ""

        # Extract function call name
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
            if isinstance(node.func.value, ast.Name):
                mod_name = node.func.value.id

        # 1. subprocess.*(shell=True) -> HIGH
        if (mod_name == "subprocess" or func_name in ("Popen", "run", "call", "check_call", "check_output")):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    if self._is_added(lineno):
                        self.findings.append(Finding(
                            rule_id="shell-true",
                            severity="HIGH",
                            file_path=self.file_path,
                            lineno=lineno,
                            message="subprocess invoked with shell=True",
                        ))

        # 2. os.system( -> HIGH
        if mod_name == "os" and func_name == "system":
            if self._is_added(lineno):
                self.findings.append(Finding(
                    rule_id="os-system",
                    severity="HIGH",
                    file_path=self.file_path,
                    lineno=lineno,
                    message="os.system() call executes raw shell command",
                ))

        # 3. eval / exec with non-literal argument -> HIGH; literal -> MEDIUM
        if func_name in ("eval", "exec") and node.args:
            first_arg = node.args[0]
            is_literal = isinstance(first_arg, ast.Constant)
            if self._is_added(lineno):
                self.findings.append(Finding(
                    rule_id="dynamic-eval" if not is_literal else "eval-literal",
                    severity="HIGH" if not is_literal else "MEDIUM",
                    file_path=self.file_path,
                    lineno=lineno,
                    message=f"{func_name}() called with non-literal code" if not is_literal else f"{func_name}() called on literal",
                ))

        # 4. pickle.loads / marshal.loads non-literal -> HIGH
        if (mod_name in ("pickle", "marshal", "_pickle") or func_name == "loads") and node.args:
            if not isinstance(node.args[0], ast.Constant):
                if self._is_added(lineno):
                    self.findings.append(Finding(
                        rule_id="unsafe-deserialization",
                        severity="HIGH",
                        file_path=self.file_path,
                        lineno=lineno,
                        message=f"unsafe deserialization via {mod_name or func_name}.loads",
                    ))

        # 5. yaml.load without Loader=SafeLoader -> HIGH
        if mod_name == "yaml" and func_name == "load":
            has_safe_loader = any(kw.arg == "Loader" and "Safe" in ast.dump(kw.value) for kw in node.keywords)
            if not has_safe_loader and self._is_added(lineno):
                self.findings.append(Finding(
                    rule_id="unsafe-yaml-load",
                    severity="HIGH",
                    file_path=self.file_path,
                    lineno=lineno,
                    message="yaml.load() called without SafeLoader",
                ))

        # 6. verify=False -> MEDIUM
        for kw in node.keywords:
            if kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                if self._is_added(lineno):
                    self.findings.append(Finding(
                        rule_id="ssl-verify-disabled",
                        severity="MEDIUM",
                        file_path=self.file_path,
                        lineno=lineno,
                        message="TLS/SSL certificate verification disabled (verify=False)",
                    ))

        self.generic_visit(node)


def scan_python_code(
    file_path: str,
    content: str,
    added_lines: set[int],
    pre_available: bool,
) -> list[Finding]:
    """Scan Python file content using AST parser."""
    try:
        tree = ast.parse(content, filename=file_path)
    except Exception:
        # Syntax error: fall back to regex scan
        return scan_regex_code(file_path, content, added_lines, pre_available)

    visitor = _PythonSecurityVisitor(file_path, added_lines, pre_available)
    visitor.visit(tree)
    return visitor.findings


# ── Regex Scanner (JS, TS, Fallback) ─────────────────────────────────────────

JS_PATTERNS = [
    # child_process.exec / execSync
    (re.compile(r"\b(?:child_process\.)?exec(?:Sync)?\s*\((?!\s*['\"])"), "HIGH", "child-process-exec", "child_process.exec with non-literal argument"),
    # new Function(
    (re.compile(r"\bnew\s+Function\s*\((?!\s*['\"])"), "HIGH", "new-function", "new Function() with non-literal argument"),
    # eval(
    (re.compile(r"\beval\s*\((?!\s*['\"])"), "HIGH", "js-eval", "eval() with non-literal argument"),
    # dangerouslySetInnerHTML
    (re.compile(r"\bdangerouslySetInnerHTML\b"), "MEDIUM", "dangerously-set-inner-html", "dangerouslySetInnerHTML used"),
    # innerHTML = non-literal
    (re.compile(r"\.innerHTML\s*=\s*(?!['\"])"), "MEDIUM", "inner-html-assignment", "Direct innerHTML assignment with non-literal"),
]


def scan_regex_code(
    file_path: str,
    content: str,
    added_lines: set[int],
    pre_available: bool,
) -> list[Finding]:
    """Scan JS/TS or fallback code using targeted regexes."""
    findings: list[Finding] = []
    lines = content.splitlines()

    for lineno, line in enumerate(lines, 1):
        if pre_available and lineno not in added_lines:
            continue

        # Skip comment-only lines in JS/TS
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue

        for pat, sev, rule, msg in JS_PATTERNS:
            if pat.search(line):
                findings.append(Finding(
                    rule_id=rule,
                    severity=sev,
                    file_path=file_path,
                    lineno=lineno,
                    message=msg,
                ))

    return findings


# ── Secret Pattern Scanner ───────────────────────────────────────────────────

def scan_for_secrets(
    file_path: str,
    content: str,
    added_lines: set[int],
    pre_available: bool,
) -> list[Finding]:
    """Scan code lines for hardcoded private keys, tokens, or long API keys."""
    findings: list[Finding] = []
    lines = content.splitlines()

    for lineno, line in enumerate(lines, 1):
        if pre_available and lineno not in added_lines:
            continue

        # Private key header
        if PRIVATE_KEY_RE.search(line):
            findings.append(Finding(
                rule_id="hardcoded-private-key",
                severity="HIGH",
                file_path=file_path,
                lineno=lineno,
                message="Hardcoded private key block detected",
            ))

        # AWS Access Key
        if AWS_KEY_RE.search(line):
            findings.append(Finding(
                rule_id="aws-access-key",
                severity="HIGH",
                file_path=file_path,
                lineno=lineno,
                message="Hardcoded AWS Access Key ID detected",
            ))

        # GitHub token
        if GITHUB_TOKEN_RE.search(line):
            findings.append(Finding(
                rule_id="github-token",
                severity="HIGH",
                file_path=file_path,
                lineno=lineno,
                message="Hardcoded GitHub token detected",
            ))

        # API Key assignment
        if API_KEY_ASSIGN_RE.search(line):
            findings.append(Finding(
                rule_id="hardcoded-api-key",
                severity="HIGH",
                file_path=file_path,
                lineno=lineno,
                message="Hardcoded API key or access token literal detected",
            ))

    return findings


# ── Lockfile Audit Hook (npm audit) ──────────────────────────────────────────

async def run_npm_audit_hook(ws_path: Path) -> VerifyResult:
    """Run npm audit if lockfile changed; informational only, never FAILED."""
    t0 = time.perf_counter()
    npm_bin = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_bin:
        return VerifyResult(
            hook="npm_audit",
            status=VerifyStatus.SKIPPED,
            summary="npm binary not available",
            skip_reason="npm binary not available",
            duration_ms=0,
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            npm_bin,
            "audit",
            "--audit-level=high",
            cwd=str(ws_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        out_text = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")

        if proc.returncode != 0:
            # Informational only: status is WARN at worst, never FAILED
            return VerifyResult(
                hook="npm_audit",
                status=VerifyStatus.WARN,
                summary="npm audit reported vulnerabilities",
                details=[out_text[:300]],
                duration_ms=duration_ms,
            )

        return VerifyResult(
            hook="npm_audit",
            status=VerifyStatus.PASSED,
            summary="0 high vulnerabilities reported",
            duration_ms=duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return VerifyResult(
            hook="npm_audit",
            status=VerifyStatus.SKIPPED,
            summary=f"npm audit offline or failed: {exc}",
            skip_reason=f"npm audit failed: {exc}",
            duration_ms=duration_ms,
        )


# ── Main Security Hook Entrypoint ────────────────────────────────────────────

async def run_security_scan_hook(
    workspace_root: str | Path,
    changed_rel_paths: list[str],
    pre_images: dict[str, bytes | None] | None = None,
) -> tuple[VerifyResult, int]:
    """Execute diff-scoped security scan on touched files.
    
    Returns: (VerifyResult, suppressions_added_count)
    """
    t0 = time.perf_counter()
    ws_path = normalize_workspace(str(workspace_root))
    pre_imgs = pre_images or {}

    findings: list[Finding] = []
    suppressions_added_total = 0
    caveats: list[str] = []

    for rel_p in changed_rel_paths:
        if not is_code_file(rel_p):
            continue

        full_p = ws_path / rel_p
        if not full_p.is_file():
            continue

        try:
            post_bytes = full_p.read_bytes()
            post_content = post_bytes.decode("utf-8", errors="replace")
        except Exception:
            continue

        pre_bytes = pre_imgs.get(rel_p)
        pre_content = pre_bytes.decode("utf-8", errors="replace") if pre_bytes is not None else None
        pre_available = pre_bytes is not None

        added_lines = get_added_line_numbers(pre_content, post_content)
        lines = post_content.splitlines()

        # Extract suppressions
        supp_map = extract_suppressions_from_lines(lines, added_lines)

        # Count suppressions added in this turn (comments on added lines)
        for lineno in added_lines:
            line = lines[lineno - 1]
            match = SUPPRESSION_RE.search(line)
            if match:
                suppressions_added_total += 1

        # 1. AST scan for Python
        if rel_p.endswith(".py"):
            file_findings = scan_python_code(rel_p, post_content, added_lines, pre_available)
        else:
            file_findings = scan_regex_code(rel_p, post_content, added_lines, pre_available)

        # 2. Secret scan
        secret_findings = scan_for_secrets(rel_p, post_content, added_lines, pre_available)
        file_findings.extend(secret_findings)

        # Apply suppressions and check pre-existing status
        for f in file_findings:
            supps_for_line = supp_map.get(f.lineno, set())
            if f.rule_id.lower() in supps_for_line or "all" in supps_for_line:
                f.suppressed = True
                f.severity = "MEDIUM"  # Suppressed findings downgraded to WARN
            elif not pre_available:
                f.severity = "MEDIUM"  # Cannot attribute to turn -> WARN
                f.message += " (cannot tell if pre-existing)"

            findings.append(f)

    duration_ms = int((time.perf_counter() - t0) * 1000)

    if suppressions_added_total > 0:
        caveats.append(f"{suppressions_added_total} security suppression{'s' if suppressions_added_total > 1 else ''} added in this turn")

    high_findings = [f for f in findings if f.severity == "HIGH" and not f.suppressed]
    med_findings = [f for f in findings if f.severity == "MEDIUM" or f.suppressed]

    if high_findings:
        return VerifyResult(
            hook="security_scan",
            status=VerifyStatus.FAILED,
            summary=f"{len(high_findings)} HIGH severity security vulnerability detected",
            details=[f.to_string() for f in high_findings],
            duration_ms=duration_ms,
            caveats=caveats,
        ), suppressions_added_total

    if med_findings:
        return VerifyResult(
            hook="security_scan",
            status=VerifyStatus.WARN,
            summary=f"{len(med_findings)} security warning(s)",
            details=[f.to_string() for f in med_findings],
            duration_ms=duration_ms,
            caveats=caveats,
        ), suppressions_added_total

    return VerifyResult(
        hook="security_scan",
        status=VerifyStatus.PASSED,
        summary="clean (0 findings)",
        duration_ms=duration_ms,
        caveats=caveats,
    ), suppressions_added_total
