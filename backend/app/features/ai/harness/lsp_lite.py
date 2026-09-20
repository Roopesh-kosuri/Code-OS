"""lsp_lite.py — LSP-Lite Diagnostics for CODE OS v5.0.0 (Phase 12).

Provides:
- collect_diagnostics(file_paths, workspace=None) -> dict[str, list[dict]]:
    Runs lightweight linter/compiler checks on specified hot files:
    - Python: `python -m pyflakes <path>` in bundled python runtime.
    - TypeScript/JavaScript: `npx tsc --noEmit --pretty false` with fallback syntax check.
- Bound every subprocess to 10s; on timeout returns timeout diagnostic without blocking turn.
- Graceful degradation: logs INFO once if tools missing, proceeds silently.
- format_diagnostics_block(diagnostics, max_entries=20) -> str:
    Formats compact [DIAGNOSTICS] block for prompt context injection.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from app.core.paths import ensure_within_workspace, normalize_workspace

logger = logging.getLogger(__name__)

# Single-log flags for graceful degradation
_pyflakes_unavailable_logged = False
_tsc_unavailable_logged = False

# Regex pattern for pyflakes output lines
# Example: "path/to/file.py:14:5: 'os' imported but unused"
# Example: "path/to/file.py:42: 'val' undefined name"
_PYFLAKES_LINE_RE = re.compile(
    r"^(?P<path>[a-zA-Z]:[\\/][^:]+|[^:]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<msg>.+)$"
)

# Regex pattern for tsc output lines
# Example: "path/to/file.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'."
# Example: "path/to/file.ts:12:5 - error TS2322: Type 'string' is not assignable to type 'number'."
_TSC_LINE_RE1 = re.compile(
    r"^(?P<path>[^(:\n]+)\((?P<line>\d+),(?P<col>\d+)\):\s*(?P<severity>error|warning)\s*(?P<code>TS\d+)?:?\s*(?P<msg>.*)$"
)
_TSC_LINE_RE2 = re.compile(
    r"^(?P<path>[^:\n]+):(?P<line>\d+):(?P<col>\d+)\s*-\s*(?P<severity>error|warning)\s*(?P<code>TS\d+)?:?\s*(?P<msg>.*)$"
)


def _find_python_binary() -> str:
    """Locate bundled Python executable, falling back to sys.executable."""
    # 1. Check ./resources/python/python.exe
    bundled_local = Path("resources/python/python.exe")
    if bundled_local.is_file():
        return str(bundled_local.resolve())

    # 2. Check relative to repo root
    try:
        repo_root = Path(__file__).resolve().parents[5]
        bundled_repo = repo_root / "resources" / "python" / "python.exe"
        if bundled_repo.is_file():
            return str(bundled_repo.resolve())
    except Exception:
        pass

    return sys.executable


def _run_pyflakes_check(file_path: Path, rel_path: str, timeout_sec: float = 10.0) -> list[dict[str, Any]]:
    """Run pyflakes on a Python file and return structured diagnostics."""
    global _pyflakes_unavailable_logged

    py_bin = _find_python_binary()
    cmd = [py_bin, "-m", "pyflakes", str(file_path)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return [{
            "path": rel_path,
            "line": 1,
            "col": 1,
            "severity": "warning",
            "message": "Diagnostic check timeout (>10s)",
        }]
    except (FileNotFoundError, OSError) as exc:
        if not _pyflakes_unavailable_logged:
            logger.info("lsp_lite: pyflakes unavailable in runtime (%s); skipping Python diagnostics", exc)
            _pyflakes_unavailable_logged = True
        return []

    # Check if pyflakes is not installed
    combined_output = f"{proc.stdout}\n{proc.stderr}".strip()
    if "No module named pyflakes" in combined_output:
        if not _pyflakes_unavailable_logged:
            logger.info("lsp_lite: pyflakes module not found in bundled runtime; skipping Python diagnostics")
            _pyflakes_unavailable_logged = True
        return []

    diagnostics: list[dict[str, Any]] = []

    # Parse stdout and stderr lines
    for line in combined_output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _PYFLAKES_LINE_RE.match(line)
        if m:
            raw_msg = m.group("msg").strip()
            line_no = int(m.group("line"))
            col_no = int(m.group("col")) if m.group("col") else 1

            lower_msg = raw_msg.lower()
            if any(k in lower_msg for k in ("syntax", "undefined", "never closed", "invalid", "unexpected")):
                severity = "error"
            else:
                severity = "warning"

            diagnostics.append({
                "path": rel_path,
                "line": line_no,
                "col": col_no,
                "severity": severity,
                "message": raw_msg,
            })

    return diagnostics


def _fallback_js_syntax_check(file_path: Path, rel_path: str) -> list[dict[str, Any]]:
    """Fast regex-based fallback syntax check for JS/TS files."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    diagnostics: list[dict[str, Any]] = []
    lines = content.splitlines()

    # Track unclosed braces/brackets across file
    brace_stack = []
    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        for col_idx, ch in enumerate(line, start=1):
            if ch in ("{", "(", "["):
                brace_stack.append((ch, line_idx, col_idx))
            elif ch in ("}", ")", "]"):
                if not brace_stack:
                    diagnostics.append({
                        "path": rel_path,
                        "line": line_idx,
                        "col": col_idx,
                        "severity": "error",
                        "message": f"Unmatched closing delimiter '{ch}'",
                    })
                    break
                open_ch, _, _ = brace_stack.pop()
                expected = "}" if open_ch == "{" else (")" if open_ch == "(" else "]")
                if ch != expected:
                    diagnostics.append({
                        "path": rel_path,
                        "line": line_idx,
                        "col": col_idx,
                        "severity": "error",
                        "message": f"Mismatched delimiter: opened with '{open_ch}', closed with '{ch}'",
                    })
                    break
        if len(diagnostics) >= 5:
            break

    if brace_stack and len(diagnostics) < 5:
        open_ch, open_line, open_col = brace_stack[-1]
        diagnostics.append({
            "path": rel_path,
            "line": open_line,
            "col": open_col,
            "severity": "error",
            "message": f"Unclosed delimiter '{open_ch}'",
        })

    return diagnostics


def _run_tsc_check(file_path: Path, rel_path: str, workspace_path: Path, timeout_sec: float = 10.0) -> list[dict[str, Any]]:
    """Run tsc check on a TS/JS file with fallback syntax parsing."""
    global _tsc_unavailable_logged

    # Look for tsconfig in directory hierarchy
    curr = file_path.parent
    tsconfig = None
    while curr >= workspace_path:
        cand = curr / "tsconfig.json"
        if cand.is_file():
            tsconfig = cand
            break
        if curr == curr.parent:
            break
        curr = curr.parent

    # Run npx tsc
    cmd = ["npx", "--no-install", "tsc", "--noEmit", "--pretty", "false"]
    if tsconfig:
        cmd.extend(["-p", str(tsconfig.parent)])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(workspace_path),
            timeout=timeout_sec,
            shell=os.name == "nt",
        )
    except subprocess.TimeoutExpired:
        return [{
            "path": rel_path,
            "line": 1,
            "col": 1,
            "severity": "warning",
            "message": "Diagnostic check timeout (>10s)",
        }]
    except (FileNotFoundError, OSError) as exc:
        if not _tsc_unavailable_logged:
            logger.info("lsp_lite: tsc / npx unavailable (%s); falling back to syntax check", exc)
            _tsc_unavailable_logged = True
        return _fallback_js_syntax_check(file_path, rel_path)

    combined_output = f"{proc.stdout}\n{proc.stderr}".strip()
    if not combined_output or proc.returncode == 0:
        return []

    # Check if npx/tsc failed with tool missing
    if "not found" in combined_output.lower() or "not recognized" in combined_output.lower():
        if not _tsc_unavailable_logged:
            logger.info("lsp_lite: tsc command not found; falling back to syntax check")
            _tsc_unavailable_logged = True
        return _fallback_js_syntax_check(file_path, rel_path)

    diagnostics: list[dict[str, Any]] = []
    clean_target = rel_path.replace("\\", "/").lower()

    for line in combined_output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TSC_LINE_RE1.match(line) or _TSC_LINE_RE2.match(line)
        if m:
            file_match = m.group("path").replace("\\", "/").lower()
            if not file_match.endswith(clean_target) and clean_target not in file_match:
                continue

            line_no = int(m.group("line"))
            col_no = int(m.group("col"))
            severity = m.group("severity").lower()
            code = m.group("code") or ""
            raw_msg = m.group("msg").strip()
            formatted_msg = f"{code}: {raw_msg}".strip(" :") if code else raw_msg

            diagnostics.append({
                "path": rel_path,
                "line": line_no,
                "col": col_no,
                "severity": severity,
                "message": formatted_msg,
            })

    if not diagnostics and proc.returncode != 0:
        # If tsc failed but no matching lines for this file, fallback to syntax check
        return _fallback_js_syntax_check(file_path, rel_path)

    return diagnostics


def collect_diagnostics(
    file_paths: list[str],
    workspace: str | None = None,
    timeout_per_file: float = 10.0,
) -> dict[str, list[dict[str, Any]]]:
    """Collect compiler and linter diagnostics for specified files.

    Args:
        file_paths: List of file paths to check.
        workspace: Workspace root path (defaults to cwd).
        timeout_per_file: Maximum subprocess execution duration (default 10s).

    Returns:
        Mapping from file relative path to list of diagnostic dicts:
        {"path", "line", "col", "severity", "message"}.
    """
    ws_path = normalize_workspace(workspace) if workspace else Path.cwd()
    results: dict[str, list[dict[str, Any]]] = {}

    for raw_p in file_paths:
        if not raw_p or not isinstance(raw_p, str):
            continue
        try:
            full_p = ensure_within_workspace(ws_path, raw_p)
            if not full_p.is_file():
                continue
            rel_p = str(full_p.relative_to(ws_path)).replace("\\", "/")
        except (ValueError, OSError):
            continue

        ext = full_p.suffix.lower()
        if ext in (".py", ".pyw"):
            diags = _run_pyflakes_check(full_p, rel_p, timeout_sec=timeout_per_file)
            if diags:
                results[rel_p] = diags
        elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            diags = _run_tsc_check(full_p, rel_p, ws_path, timeout_sec=timeout_per_file)
            if diags:
                results[rel_p] = diags

    return results


def format_diagnostics_block(
    diagnostics: dict[str, list[dict[str, Any]]] | list[dict[str, Any]],
    max_entries: int = 20,
) -> str:
    """Format diagnostic entries into a compact context block.

    Example output:
        [DIAGNOSTICS]
        - src/index.ts:12:5 [error] TS2322: Type 'string' is not assignable to type 'number'.
        - app/utils.py:1:1 [warning] 'os' imported but unused
        [END DIAGNOSTICS]
    """
    flat: list[dict[str, Any]] = []
    if isinstance(diagnostics, dict):
        for items in diagnostics.values():
            flat.extend(items)
    elif isinstance(diagnostics, list):
        flat.extend(diagnostics)

    if not flat:
        return ""

    # Sort errors first, then warnings
    flat.sort(key=lambda d: (0 if d.get("severity") == "error" else 1, d.get("path", ""), d.get("line", 0)))
    selected = flat[:max_entries]

    lines = ["[DIAGNOSTICS]"]
    for d in selected:
        p = d.get("path", "")
        ln = d.get("line", 1)
        col = d.get("col", 1)
        sev = d.get("severity", "warning")
        msg = d.get("message", "")
        lines.append(f"- {p}:{ln}:{col} [{sev}] {msg}")
    lines.append("[END DIAGNOSTICS]")

    return "\n".join(lines)
