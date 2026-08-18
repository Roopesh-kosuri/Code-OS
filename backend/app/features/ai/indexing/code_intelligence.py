"""
code_intelligence.py — Workspace Symbol Indexing & Code Intelligence Engine for CODE OS.

Provides:
- AST Symbol Indexing & Reference Resolution (Python, JS, TS, React)
- Go-to-Definition and Find-References tool handlers
- Style Learning & Convention Extraction (naming, imports, error styles, comments)
- Dead-Code & Orphan File Detection
- Living Architecture Documentation generator (ARCHITECTURE.md)
- Structured Git Diff Analysis (compared to checkpoints / commits)
- Pre-proposal Secret & High-Entropy Token Scanner
"""
from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from ..agents.agent_tools import ToolResult
from ..schemas import FileChange

logger = logging.getLogger(__name__)


# ── Symbol Indexing Engine (find_references & go_to_definition) ──────────────

def _build_symbol_index(workspace: str, max_files: int = 250) -> dict[str, Any]:
    """Parse Python, JS, TS files in workspace and build symbol definitions and references map.
    Stores and caches to <workspace>/.code_os/symbol_index.json.
    """
    if not workspace:
        return {"definitions": {}, "references": {}}
    
    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return {"definitions": {}, "references": {}}

    definitions: dict[str, list[dict]] = {}
    references: dict[str, list[dict]] = {}

    source_exts = {".py", ".ts", ".js", ".tsx", ".jsx", ".mjs", ".cjs"}
    ignored_dirs = {".git", ".code_os", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache"}

    all_files: list[Path] = []
    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix in source_exts:
                all_files.append(p)
                if len(all_files) >= max_files:
                    break
        if len(all_files) >= max_files:
            break

    for file_path in all_files:
        try:
            rel_path = str(file_path.relative_to(ws_path)).replace("\\", "/")
            content = file_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
        except Exception:
            continue

        if file_path.suffix == ".py":
            try:
                tree = ast.parse(content, filename=str(file_path))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args_list = [a.arg for a in node.args.args]
                        sig = f"def {node.name}({', '.join(args_list)})"
                        doc = ast.get_docstring(node) or ""
                        definitions.setdefault(node.name, []).append({
                            "name": node.name,
                            "symbol_type": "function",
                            "file_path": rel_path,
                            "line": node.lineno,
                            "signature": sig,
                            "docstring": doc[:120],
                        })
                    elif isinstance(node, ast.ClassDef):
                        bases = [getattr(b, "id", getattr(b, "attr", "")) for b in node.bases]
                        sig = f"class {node.name}({', '.join(filter(None, bases))})"
                        doc = ast.get_docstring(node) or ""
                        definitions.setdefault(node.name, []).append({
                            "name": node.name,
                            "symbol_type": "class",
                            "file_path": rel_path,
                            "line": node.lineno,
                            "signature": sig,
                            "docstring": doc[:120],
                        })
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                sym_type = "constant" if target.id.isupper() else "variable"
                                val_repr = ""
                                if isinstance(node.value, ast.Constant):
                                    val_repr = repr(node.value.value)
                                sig = f"{target.id} = {val_repr}".strip()
                                definitions.setdefault(target.id, []).append({
                                    "name": target.id,
                                    "symbol_type": sym_type,
                                    "file_path": rel_path,
                                    "line": node.lineno,
                                    "signature": sig,
                                    "docstring": "",
                                })
            except Exception:
                pass
        else:
            # JS/TS parsing
            for line_idx, line in enumerate(lines, start=1):
                fn_m = re.search(r"\b(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)", line)
                if fn_m:
                    definitions.setdefault(fn_m.group(1), []).append({
                        "name": fn_m.group(1),
                        "symbol_type": "function",
                        "file_path": rel_path,
                        "line": line_idx,
                        "signature": f"function {fn_m.group(1)}({fn_m.group(2)})",
                        "docstring": "",
                    })
                var_m = re.search(r"\b(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:(?:async\s*)?\(([^)]*)\)\s*=>|function|([^\n;]+))", line)
                if var_m:
                    sym_name = var_m.group(1)
                    sym_type = "constant" if sym_name.isupper() else ("function" if "=>" in line or "function" in line else "variable")
                    definitions.setdefault(sym_name, []).append({
                        "name": sym_name,
                        "symbol_type": sym_type,
                        "file_path": rel_path,
                        "line": line_idx,
                        "signature": line.strip()[:100],
                        "docstring": "",
                    })
                cls_m = re.search(r"\b(?:export\s+)?class\s+([a-zA-Z0-9_$]+)", line)
                if cls_m:
                    definitions.setdefault(cls_m.group(1), []).append({
                        "name": cls_m.group(1),
                        "symbol_type": "class",
                        "file_path": rel_path,
                        "line": line_idx,
                        "signature": line.strip()[:100],
                        "docstring": "",
                    })

        # Reference finding
        for line_idx, line in enumerate(lines, start=1):
            tokens = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", line))
            for tok in tokens:
                if len(tok) >= 2 and tok not in (
                    "def", "class", "import", "from", "return", "const", "let", "var", "function",
                    "if", "else", "for", "while", "in", "and", "or", "not", "is", "None", "True", "False",
                    "async", "await", "try", "except", "finally", "with", "as", "pass", "break", "continue"
                ):
                    references.setdefault(tok, []).append({
                        "name": tok,
                        "file_path": rel_path,
                        "line": line_idx,
                        "line_content": line.strip()[:140],
                    })

    index_data = {
        "definitions": definitions,
        "references": references,
        "indexed_at": time.time(),
        "total_files": len(all_files),
    }

    try:
        idx_file = ws_path / ".code_os" / "symbol_index.json"
        idx_file.parent.mkdir(parents=True, exist_ok=True)
        idx_file.write_text(json.dumps(index_data, indent=2), encoding="utf-8")
    except Exception:
        pass

    return index_data


def _handle_go_to_definition(workspace: str, arguments: dict) -> ToolResult:
    """Find the defining location of a symbol."""
    symbol = (arguments.get("symbol") or arguments.get("name") or "").strip()
    if not symbol:
        return ToolResult(tool_name="go_to_definition", success=False, output="", error="Missing parameter 'symbol'")

    index = _build_symbol_index(workspace)
    defs = index.get("definitions", {}).get(symbol, [])
    if not defs:
        # Direct search fallback
        ws_path = Path(workspace)
        matches = []
        for p in ws_path.rglob("*.py"):
            if ".git" in p.parts or ".venv" in p.parts or "node_modules" in p.parts:
                continue
            try:
                for idx, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                    if re.search(rf"\b(def|class|{symbol}\s*=)\s+{symbol}\b", line) or re.search(rf"^{symbol}\s*=", line):
                        rel = str(p.relative_to(ws_path)).replace("\\", "/")
                        matches.append(f"- **{symbol}** defined in `{rel}:{idx}`: `{line.strip()}`")
            except Exception:
                pass
        if matches:
            return ToolResult(tool_name="go_to_definition", success=True, output="\n".join(matches))
        return ToolResult(tool_name="go_to_definition", success=True, output=f"No definition found for symbol '{symbol}' in workspace.")

    output_lines = [f"=== DEFINITION(S) FOR `{symbol}` ==="]
    for d in defs:
        doc_snippet = f"\n  Doc: {d['docstring']}" if d.get("docstring") else ""
        output_lines.append(f"- [{d['symbol_type'].upper()}] `{d['file_path']}:{d['line']}`\n  `{d['signature']}`{doc_snippet}")
    return ToolResult(tool_name="go_to_definition", success=True, output="\n".join(output_lines))


def _handle_find_references(workspace: str, arguments: dict) -> ToolResult:
    """Find all usages and references of a symbol across workspace files."""
    symbol = (arguments.get("symbol") or arguments.get("name") or "").strip()
    if not symbol:
        return ToolResult(tool_name="find_references", success=False, output="", error="Missing parameter 'symbol'")

    index = _build_symbol_index(workspace)
    refs = index.get("references", {}).get(symbol, [])

    if not refs:
        ws_path = Path(workspace)
        matches = []
        for p in ws_path.rglob("*.py"):
            if ".git" in p.parts or ".venv" in p.parts or "node_modules" in p.parts:
                continue
            try:
                for idx, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                    if symbol in line:
                        rel = str(p.relative_to(ws_path)).replace("\\", "/")
                        matches.append(f"- `{rel}:{idx}`: `{line.strip()}`")
            except Exception:
                pass
        if matches:
            header = f"=== REFERENCES TO `{symbol}` ({len(matches)} occurrences) ==="
            return ToolResult(tool_name="find_references", success=True, output=header + "\n" + "\n".join(matches[:40]))
        return ToolResult(tool_name="find_references", success=True, output=f"No references found for symbol '{symbol}'.")

    by_file: dict[str, list[dict]] = {}
    for r in refs:
        by_file.setdefault(r["file_path"], []).append(r)

    total_refs = len(refs)
    output_lines = [f"=== REFERENCES TO `{symbol}` ({total_refs} occurrences across {len(by_file)} files) ==="]
    for file_path, items in by_file.items():
        output_lines.append(f"\n📂 `{file_path}` ({len(items)} usage{'s' if len(items) > 1 else ''}):")
        for item in items[:15]:
            output_lines.append(f"  - Line {item['line']}: `{item['line_content']}`")
        if len(items) > 15:
            output_lines.append(f"  - ... and {len(items) - 15} more occurrences")

    return ToolResult(tool_name="find_references", success=True, output="\n".join(output_lines))


# ── Style Learning & Conventions Engine ──────────────────────────────────────

def _extract_style_conventions(workspace: str, sample_limit: int = 35) -> dict[str, Any]:
    """Inspect workspace source files and extract conventions (naming, imports, errors, comments)."""
    if not workspace:
        return {"naming": "snake_case", "imports": "absolute", "error_handling": "try/except", "comments": "docstrings"}

    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return {"naming": "snake_case", "imports": "absolute", "error_handling": "try/except", "comments": "docstrings"}

    source_files: list[Path] = []
    ignored = {".git", ".code_os", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix in (".py", ".ts", ".js", ".tsx", ".jsx"):
                source_files.append(p)
                if len(source_files) >= sample_limit:
                    break
        if len(source_files) >= sample_limit:
            break

    snake_count = 0
    camel_count = 0
    abs_import_count = 0
    rel_import_count = 0
    try_except_count = 0
    docstring_count = 0
    inline_comment_count = 0

    for sf in source_files:
        try:
            txt = sf.read_text(encoding="utf-8", errors="replace")
            # Naming
            snake_count += len(re.findall(r"\bdef\s+[a-z_][a-z0-9_]*\b", txt))
            camel_count += len(re.findall(r"\b(?:function|const)\s+[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b", txt))
            # Imports
            abs_import_count += len(re.findall(r"\bfrom\s+[a-zA-Z0-9_]+\s+import\b", txt))
            rel_import_count += len(re.findall(r"\bfrom\s+\.[a-zA-Z0-9_.]*\s+import\b", txt))
            # Error handling
            try_except_count += len(re.findall(r"\btry\s*:", txt))
            # Comments
            docstring_count += len(re.findall(r'"""[\s\S]*?"""', txt))
            inline_comment_count += len(re.findall(r"#\s+[a-zA-Z]", txt))
        except Exception:
            continue

    naming_style = "snake_case" if snake_count >= camel_count else "camelCase"
    import_style = "absolute" if abs_import_count >= rel_import_count else "relative"
    err_style = "try/except" if try_except_count > 0 else "Result/return checks"
    comment_style = "docstrings" if docstring_count >= inline_comment_count else "inline comments"

    conventions = {
        "naming": naming_style,
        "imports": import_style,
        "error_handling": err_style,
        "comments": comment_style,
        "analyzed_files": len(source_files),
    }

    try:
        style_file = ws_path / ".code_os" / "style_conventions.json"
        style_file.parent.mkdir(parents=True, exist_ok=True)
        style_file.write_text(json.dumps(conventions, indent=2), encoding="utf-8")
    except Exception:
        pass

    return conventions


def _load_style_conventions_summary(workspace: str) -> str:
    """Load or extract style conventions and return concise prompt injection string."""
    if not workspace:
        return ""
    ws_path = Path(workspace)
    style_file = ws_path / ".code_os" / "style_conventions.json"
    if style_file.is_file():
        try:
            conv = json.loads(style_file.read_text(encoding="utf-8"))
        except Exception:
            conv = _extract_style_conventions(workspace)
    else:
        conv = _extract_style_conventions(workspace)

    naming = conv.get("naming", "snake_case")
    imports = conv.get("imports", "absolute")
    errs = conv.get("error_handling", "try/except")
    return f"This workspace uses {naming} for functions, {imports} imports, and {errs} for error handling."


# ── Dead-Code Detection Engine (find_dead_code) ──────────────────────────────

def _find_dead_code(workspace: str, sample_paths: list[str] | None = None) -> ToolResult:
    """Scan workspace and identify unreferenced / orphaned files with no incoming imports."""
    if not workspace:
        return ToolResult(tool_name="find_dead_code", success=False, output="", error="No workspace provided")

    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return ToolResult(tool_name="find_dead_code", success=False, output="", error="Workspace directory not found")

    source_exts = {".py", ".ts", ".js", ".tsx", ".jsx"}
    ignored = {".git", ".code_os", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}

    files_map: dict[str, Path] = {}
    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix in source_exts:
                rel = str(p.relative_to(ws_path)).replace("\\", "/")
                files_map[rel] = p

    entrypoint_patterns = (
        r"^main\.py$", r"^app\.py$", r"^__init__\.py$", r"^index\.(ts|js|html|tsx|jsx)$",
        r"^App\.(tsx|jsx)$", r"^setup\.py$", r"^conftest\.py$", r"^manage\.py$",
        r"^vite\.config\.(ts|js)$", r"^tailwind\.config\.(ts|js)$", r"^next\.config\.(js|ts)$",
        r"^tests?/", r"^test_.*\.py$", r".*_test\.py$", r".*\.test\.(ts|js|tsx|jsx)$",
    )

    imported_stems: set[str] = set()
    for rel_path, p in files_map.items():
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            py_imports = re.findall(r"(?:from\s+([a-zA-Z0-9_.]+)\s+import|import\s+([a-zA-Z0-9_.]+))", txt)
            for m1, m2 in py_imports:
                mod = m1 or m2
                parts = mod.split(".")
                for pt in parts:
                    imported_stems.add(pt.lower())
                imported_stems.add(mod.lower())
            js_imports = re.findall(r"""(?:from|require|import)\s*\(?['"]([^'"]+)['"]""", txt)
            for imp in js_imports:
                stem = Path(imp).stem.lower()
                imported_stems.add(stem)
        except Exception:
            continue

    unreferenced: list[str] = []
    for rel_path, p in sorted(files_map.items()):
        if any(re.search(ep, rel_path, re.IGNORECASE) for ep in entrypoint_patterns):
            continue

        stem = p.stem.lower()
        if stem not in imported_stems:
            unreferenced.append(rel_path)

    if not unreferenced:
        return ToolResult(tool_name="find_dead_code", success=True, output="=== DEAD-CODE SCAN ===\n✓ No unreferenced/orphan source files detected in workspace.")

    lines = [f"=== DEAD-CODE SCAN ({len(unreferenced)} unreferenced source file(s) found) ==="]
    lines.append("The following files have no incoming imports/references across workspace modules:")
    for uf in unreferenced:
        lines.append(f"- `❌ {uf}`")
    lines.append("\nTip: If these are intentionally standalone CLI scripts, keep them. Otherwise consider removing or linking them.")
    return ToolResult(tool_name="find_dead_code", success=True, output="\n".join(lines))


# ── Living ARCHITECTURE.md Engine ────────────────────────────────────────────

def _load_architecture_doc(workspace: str) -> str:
    """Load <workspace>/ARCHITECTURE.md if present."""
    if not workspace:
        return ""
    p = Path(workspace) / "ARCHITECTURE.md"
    if p.is_file():
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:2000]
        except Exception:
            return ""
    return ""


def _update_architecture_doc(workspace: str, reason: str = "Automated architecture refresh") -> ToolResult:
    """Scan workspace and generate / maintain <workspace>/ARCHITECTURE.md."""
    if not workspace:
        return ToolResult(tool_name="update_architecture_doc", success=False, output="", error="No workspace provided")

    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return ToolResult(tool_name="update_architecture_doc", success=False, output="", error="Workspace directory not found")

    top_dirs = [d.name for d in ws_path.iterdir() if d.is_dir() and not d.name.startswith(".") and d.name not in ("node_modules", "__pycache__", "dist", "build")]
    
    module_descriptions: list[str] = []
    for td in sorted(top_dirs):
        sub_files = [f.name for f in (ws_path / td).iterdir() if f.is_file()][:5]
        sub_str = f" (contains: {', '.join(sub_files)})" if sub_files else ""
        module_descriptions.append(f"- **`{td}/`**: Core sub-package{sub_str}")

    entry_points: list[str] = []
    for cand in ("main.py", "app.py", "index.html", "src/main.tsx", "src/index.ts", "package.json"):
        if (ws_path / cand).is_file():
            entry_points.append(f"- `{cand}`")

    iso_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    style_summary = _load_style_conventions_summary(workspace)

    doc_content = f"""# Project Architecture Overview

## Module Map
{chr(10).join(module_descriptions) if module_descriptions else "- Flat single-directory workspace layout"}

## Key Entry Points
{chr(10).join(entry_points) if entry_points else "- Standalone project files"}

## Architectural Conventions & Data Flow
- **Style Conventions**: {style_summary or "Follow established local file patterns."}
- **Sandboxing**: Workspace-contained file edits and fail-closed allowlists.

## Last Updated
- **Timestamp**: `{iso_time}`
- **Reason**: {reason}
"""
    try:
        arch_file = ws_path / "ARCHITECTURE.md"
        arch_file.write_text(doc_content, encoding="utf-8")
        return ToolResult(
            tool_name="update_architecture_doc",
            success=True,
            output=f"=== ARCHITECTURE.MD UPDATED ===\nSaved to `{arch_file}` ({len(doc_content.splitlines())} lines).\nReason: {reason}"
        )
    except Exception as exc:
        return ToolResult(tool_name="update_architecture_doc", success=False, output="", error=f"Failed to write ARCHITECTURE.md: {exc}")


# ── Structured Git Diff Engine (git_diff) ────────────────────────────────────

def _get_structured_git_diff(
    workspace: str,
    since_commit: str | None = None,
    paths: list[str] | None = None,
) -> ToolResult:
    """Return structured git diff against since_commit (or last checkpoint commit, or HEAD)."""
    if not workspace:
        return ToolResult(tool_name="git_diff", success=False, output="", error="No workspace provided")

    ws_path = Path(workspace)
    if not (ws_path / ".git").is_dir():
        return ToolResult(tool_name="git_diff", success=True, output="Git repository not initialized in workspace (no diff available).")

    # If since_commit is None, find last checkpoint commit
    target_commit = since_commit
    if not target_commit:
        try:
            log_res = subprocess.run(
                ["git", "log", "--grep=rony-turn-", "-n", "1", "--pretty=%H"],
                cwd=str(ws_path),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            found_hash = log_res.stdout.strip()
            if found_hash:
                target_commit = found_hash
            else:
                target_commit = "HEAD"
        except Exception:
            target_commit = "HEAD"

    cmd_diff = ["git", "diff", target_commit]
    cmd_stat = ["git", "diff", "--stat", target_commit]
    if paths:
        cmd_diff.extend(["--"] + paths)
        cmd_stat.extend(["--"] + paths)

    try:
        stat_res = subprocess.run(cmd_stat, cwd=str(ws_path), capture_output=True, text=True, timeout=10.0)
        diff_res = subprocess.run(cmd_diff, cwd=str(ws_path), capture_output=True, text=True, timeout=10.0)

        stat_text = stat_res.stdout.strip() or "(No file changes)"
        raw_diff = diff_res.stdout.strip()

        if not raw_diff:
            return ToolResult(tool_name="git_diff", success=True, output=f"=== GIT DIFF (compared to {target_commit}) ===\nNo changes detected since {target_commit}.")

        if len(raw_diff) > 4000:
            raw_diff = raw_diff[:4000] + "\n... [Diff truncated to save tokens]"

        out = (
            f"=== GIT DIFF SUMMARY (compared to `{target_commit[:8]}`) ===\n"
            f"{stat_text}\n\n"
            f"=== PATCH DETAILS ===\n"
            f"```diff\n{raw_diff}\n```"
        )
        return ToolResult(tool_name="git_diff", success=True, output=out)
    except Exception as exc:
        return ToolResult(tool_name="git_diff", success=False, output="", error=f"git diff failed: {exc}")


def _handle_git_diff(workspace: str, arguments: dict) -> ToolResult:
    since = arguments.get("since_commit") or arguments.get("commit") or arguments.get("since")
    paths = arguments.get("paths") if isinstance(arguments.get("paths"), list) else None
    return _get_structured_git_diff(workspace, since, paths)


# ── Secret Scanning Engine ───────────────────────────────────────────────────

SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"), "OpenAI/Anthropic API Key (sk-...)"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token (ghp_...)"),
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "GitHub OAuth Token (gho_...)"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID (AKIA...)"),
    (re.compile(r"glpat-[a-zA-Z0-9_\-]{20,}"), "GitLab Personal Access Token (glpat-...)"),
    (re.compile(r"xox[baprs]-[a-zA-Z0-9\-]{10,}"), "Slack Token (xox...)"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google API Key (AIza...)"),
    (re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PRIVATE) KEY-----"), "Private Key Block"),
]


def _calculate_shannon_entropy(data: str) -> float:
    """Compute Shannon entropy in bits per character."""
    if not data:
        return 0.0
    entropy = 0.0
    for x in set(data):
        p_x = float(data.count(x)) / len(data)
        if p_x > 0:
            entropy += - p_x * math.log2(p_x)
    return entropy


def _scan_for_secrets(staged_changes: list[FileChange]) -> tuple[bool, str]:
    """Scan staged changes for potential credentials, tokens, or private keys before creating proposals."""
    for change in staged_changes:
        content = change.updated or ""
        for pat, desc in SECRET_PATTERNS:
            m = pat.search(content)
            if m:
                matched = m.group(0)
                masked = matched[:4] + "..." + matched[-4:] if len(matched) > 8 else matched[:3] + "..."
                return True, f"Proposal contains a potential secret: {masked} ({desc}). Remove it before applying."

        # High-entropy token assignment check
        high_entropy_assignments = re.findall(
            r"""(?i)(?:api_key|secret_key|auth_token|access_token|private_key|bearer_token)\s*[:=]\s*["']([^"']{18,})["']""",
            content
        )
        for tok_val in high_entropy_assignments:
            if _calculate_shannon_entropy(tok_val) > 4.2 and not tok_val.startswith("YOUR_") and not tok_val.startswith("ENV_") and not tok_val.startswith("process.env"):
                masked = tok_val[:4] + "..." + tok_val[-4:]
                return True, f"Proposal contains a potential secret: {masked} (High-entropy token). Remove it before applying."

    return False, ""


class CodeIntelligence:
    """Class wrapper providing a unified interface for code search, indexing, style, and secret analysis."""

    def __init__(self):
        pass

    def build_index(self, workspace: str, max_files: int = 250) -> dict[str, Any]:
        return _build_symbol_index(workspace, max_files=max_files)

    def find_definition(self, workspace: str, symbol: str) -> ToolResult:
        return _handle_go_to_definition(workspace, {"symbol": symbol})

    def find_references(self, workspace: str, symbol: str) -> ToolResult:
        return _handle_find_references(workspace, {"symbol": symbol})

    def extract_style(self, workspace: str) -> dict[str, Any]:
        return _extract_style_conventions(workspace)

    def find_dead_code(self, workspace: str) -> ToolResult:
        return _find_dead_code(workspace)

    def update_architecture_doc(self, workspace: str, reason: str = "Automated architecture refresh") -> ToolResult:
        return _update_architecture_doc(workspace, reason=reason)

    def get_git_diff(self, workspace: str, since_commit: str | None = None, paths: list[str] | None = None) -> ToolResult:
        return _get_structured_git_diff(workspace, since_commit=since_commit, paths=paths)

    def scan_secrets(self, staged_changes: list[FileChange]) -> tuple[bool, str]:
        return _scan_for_secrets(staged_changes)
