"""symbol_index.py — Workspace Symbol Index & Code Navigation for CODE OS v5.0.0 (Phase 11).

Provides:
- Extraction of symbols (functions, classes, methods) with exact line ranges.
- Tree-sitter AST extraction when available, falling back to Python AST and robust regex parsing.
- Bounded LRU cache (<= 500 files, <= 2000 symbols/file).
- Watcher-driven file invalidation on change.
- APIs:
    - index_file(path) -> list[SymbolEntry]
    - symbols_in_file(path) -> list[SymbolEntry]
    - find_symbol(ws, name) -> list[SymbolEntry]
    - references_to(ws, name) -> list[dict[str, Any]]
"""

from __future__ import annotations

import ast
from collections import OrderedDict
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any

from app.core.paths import ensure_within_workspace, normalize_workspace, IGNORED_DIRS

logger = logging.getLogger(__name__)

# Bounded LRU limits per Phase 11 S1
MAX_INDEXED_FILES = 500
MAX_SYMBOLS_PER_FILE = 2000

# Extensions to index
CODE_EXTENSIONS = {
    ".py", ".pyw", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".cs", ".rb", ".php",
}

IGNORED_SCAN_DIRS = set(IGNORED_DIRS) | {
    "node_modules", ".git", "dist", "release", "build",
    ".code_os", "__pycache__", ".pytest_cache", ".venv", "venv",
    "env", ".next", ".turbo", "coverage", "resources", "target",
}


@dataclass
class SymbolEntry:
    """Represents a code symbol (function, class, method) with location and line range."""
    name: str
    kind: str  # "function", "class", "method"
    path: str
    start_line: int  # 1-indexed
    end_line: int    # 1-indexed
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "snippet": self.snippet,
        }


# Check tree-sitter availability
_TREE_SITTER_AVAILABLE = False
try:
    import tree_sitter  # noqa: F401
    _TREE_SITTER_AVAILABLE = True
except Exception:
    _TREE_SITTER_AVAILABLE = False


class SymbolIndexManager:
    """Thread-safe, bounded LRU workspace symbol index."""

    def __init__(self, max_files: int = MAX_INDEXED_FILES, max_symbols_per_file: int = MAX_SYMBOLS_PER_FILE):
        self.max_files = max_files
        self.max_symbols_per_file = max_symbols_per_file
        self._cache: OrderedDict[str, list[SymbolEntry]] = OrderedDict()
        self._lock = threading.Lock()

    def invalidate(self, path: str | Path) -> None:
        """Invalidate cached entries for a given file path."""
        norm_key = str(Path(path).resolve())
        posix_key = str(Path(path).as_posix())
        with self._lock:
            self._cache.pop(norm_key, None)
            self._cache.pop(posix_key, None)
            # Also purge any key matching the file name or suffix
            keys_to_del = [
                k for k in self._cache
                if k == norm_key or k == posix_key or k.endswith("/" + Path(path).name) or k.endswith("\\" + Path(path).name)
            ]
            for k in keys_to_del:
                self._cache.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def index_file(self, file_path: str | Path, workspace: str | None = None) -> list[SymbolEntry]:
        """Parse and return symbols for a single file, using LRU cache."""
        p = Path(file_path)
        if not p.is_file():
            return []

        resolved_key = str(p.resolve())

        with self._lock:
            if resolved_key in self._cache:
                self._cache.move_to_end(resolved_key)
                return list(self._cache[resolved_key])

        # Extract symbols outside the lock to keep lock contention low
        symbols = self._extract_symbols_from_file(p, workspace)

        # Truncate to max symbols per file
        bounded_symbols = symbols[:self.max_symbols_per_file]

        with self._lock:
            self._cache[resolved_key] = bounded_symbols
            self._cache.move_to_end(resolved_key)
            if len(self._cache) > self.max_files:
                self._cache.popitem(last=False)

        return list(bounded_symbols)

    def _extract_symbols_from_file(self, file_path: Path, workspace: str | None = None) -> list[SymbolEntry]:
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug("Failed reading %s for symbol indexing: %s", file_path, exc)
            return []

        lines = raw.splitlines()
        if not lines:
            return []

        # Relative path for display
        rel_path = str(file_path)
        if workspace:
            try:
                rel_path = str(file_path.relative_to(Path(workspace))).replace("\\", "/")
            except ValueError:
                pass

        ext = file_path.suffix.lower()
        if ext in (".py", ".pyw"):
            return self._extract_python_symbols(raw, lines, rel_path)
        elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            return self._extract_js_ts_symbols(raw, lines, rel_path)
        else:
            return self._extract_generic_symbols(raw, lines, rel_path)

    # ── Python Parser ────────────────────────────────────────────────────────
    def _extract_python_symbols(self, raw: str, lines: list[str], rel_path: str) -> list[SymbolEntry]:
        symbols: list[SymbolEntry] = []
        total_lines = len(lines)

        # 1. Primary: Standard AST
        try:
            tree = ast.parse(raw)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = node.lineno
                    end = getattr(node, "end_lineno", None) or self._infer_python_end_line(lines, start)
                    snippet = self._make_snippet(lines, start, end)
                    symbols.append(SymbolEntry(
                        name=node.name,
                        kind="function",
                        path=rel_path,
                        start_line=start,
                        end_line=end,
                        snippet=snippet,
                    ))
                elif isinstance(node, ast.ClassDef):
                    class_start = node.lineno
                    class_end = getattr(node, "end_lineno", None) or self._infer_python_end_line(lines, class_start)
                    symbols.append(SymbolEntry(
                        name=node.name,
                        kind="class",
                        path=rel_path,
                        start_line=class_start,
                        end_line=class_end,
                        snippet=self._make_snippet(lines, class_start, class_end),
                    ))
                    # Extract methods within the class
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            m_start = item.lineno
                            m_end = getattr(item, "end_lineno", None) or self._infer_python_end_line(lines, m_start)
                            symbols.append(SymbolEntry(
                                name=item.name,
                                kind="method",
                                path=rel_path,
                                start_line=m_start,
                                end_line=m_end,
                                snippet=self._make_snippet(lines, m_start, m_end),
                            ))
            if symbols:
                return symbols
        except Exception:
            # Fall back to regex on syntax errors or partial files
            pass

        # 2. Robust Regex Fallback for Python
        py_func_re = re.compile(r"^[ \t]*(?:async\s+)?def\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE)
        py_class_re = re.compile(r"^[ \t]*class\s+([a-zA-Z0-9_]+)\b", re.MULTILINE)

        for match in py_func_re.finditer(raw):
            name = match.group(1)
            line_idx = raw[:match.start()].count("\n") + 1
            indent = len(match.group(0)) - len(match.group(0).lstrip())
            kind = "method" if indent > 0 else "function"
            end = self._infer_python_end_line(lines, line_idx)
            symbols.append(SymbolEntry(
                name=name,
                kind=kind,
                path=rel_path,
                start_line=line_idx,
                end_line=end,
                snippet=self._make_snippet(lines, line_idx, end),
            ))

        for match in py_class_re.finditer(raw):
            name = match.group(1)
            line_idx = raw[:match.start()].count("\n") + 1
            end = self._infer_python_end_line(lines, line_idx)
            symbols.append(SymbolEntry(
                name=name,
                kind="class",
                path=rel_path,
                start_line=line_idx,
                end_line=end,
                snippet=self._make_snippet(lines, line_idx, end),
            ))

        symbols.sort(key=lambda s: s.start_line)
        return symbols

    def _infer_python_end_line(self, lines: list[str], start_line: int) -> int:
        """Infer end of Python block by inspecting indentation."""
        total = len(lines)
        if start_line > total:
            return start_line
        start_idx = start_line - 1
        base_line = lines[start_idx]
        base_indent = len(base_line) - len(base_line.lstrip())

        last_content_line = start_line
        for idx in range(start_idx + 1, total):
            line = lines[idx]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            curr_indent = len(line) - len(line.lstrip())
            if curr_indent <= base_indent:
                break
            last_content_line = idx + 1
        return last_content_line

    # ── JavaScript / TypeScript Parser ───────────────────────────────────────
    def _extract_js_ts_symbols(self, raw: str, lines: list[str], rel_path: str) -> list[SymbolEntry]:
        symbols: list[SymbolEntry] = []
        total_lines = len(lines)

        # Regex patterns for JS/TS
        # 1. Functions: function foo(...)
        func_re = re.compile(
            r"^(?:[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*([a-zA-Z0-9_$]+)\s*\()",
            re.MULTILINE
        )
        # 2. Arrow / Assigned functions: const foo = (...) => or const foo = function(...)
        assigned_func_re = re.compile(
            r"^(?:[ \t]*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>)",
            re.MULTILINE
        )
        assigned_classic_re = re.compile(
            r"^(?:[ \t]*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?function\b)",
            re.MULTILINE
        )
        # 3. Classes: class Foo
        class_re = re.compile(
            r"^(?:[ \t]*(?:export\s+)?(?:default\s+)?class\s+([a-zA-Z0-9_$]+)\b)",
            re.MULTILINE
        )

        seen_spans: set[tuple[int, str]] = set()

        # Check functions
        for match in func_re.finditer(raw):
            name = match.group(1)
            line_idx = raw[:match.start()].count("\n") + 1
            if (line_idx, name) in seen_spans:
                continue
            seen_spans.add((line_idx, name))
            end_line = self._infer_brace_block_end_line(lines, line_idx)
            symbols.append(SymbolEntry(
                name=name,
                kind="function",
                path=rel_path,
                start_line=line_idx,
                end_line=end_line,
                snippet=self._make_snippet(lines, line_idx, end_line),
            ))

        for match in assigned_func_re.finditer(raw):
            name = match.group(1)
            line_idx = raw[:match.start()].count("\n") + 1
            if (line_idx, name) in seen_spans:
                continue
            seen_spans.add((line_idx, name))
            end_line = self._infer_brace_block_end_line(lines, line_idx)
            symbols.append(SymbolEntry(
                name=name,
                kind="function",
                path=rel_path,
                start_line=line_idx,
                end_line=end_line,
                snippet=self._make_snippet(lines, line_idx, end_line),
            ))

        for match in assigned_classic_re.finditer(raw):
            name = match.group(1)
            line_idx = raw[:match.start()].count("\n") + 1
            if (line_idx, name) in seen_spans:
                continue
            seen_spans.add((line_idx, name))
            end_line = self._infer_brace_block_end_line(lines, line_idx)
            symbols.append(SymbolEntry(
                name=name,
                kind="function",
                path=rel_path,
                start_line=line_idx,
                end_line=end_line,
                snippet=self._make_snippet(lines, line_idx, end_line),
            ))

        for match in class_re.finditer(raw):
            name = match.group(1)
            line_idx = raw[:match.start()].count("\n") + 1
            if (line_idx, name) in seen_spans:
                continue
            seen_spans.add((line_idx, name))
            end_line = self._infer_brace_block_end_line(lines, line_idx)
            symbols.append(SymbolEntry(
                name=name,
                kind="class",
                path=rel_path,
                start_line=line_idx,
                end_line=end_line,
                snippet=self._make_snippet(lines, line_idx, end_line),
            ))

        symbols.sort(key=lambda s: s.start_line)
        return symbols

    def _infer_brace_block_end_line(self, lines: list[str], start_line: int) -> int:
        """Infer end of brace-enclosed block by tracking '{' and '}' balance."""
        total = len(lines)
        start_idx = start_line - 1
        brace_count = 0
        found_open = False

        for idx in range(start_idx, total):
            line = lines[idx]
            # Strip string literals and comments to avoid counting braces inside strings
            sanitized = re.sub(r"//.*$", "", line)
            sanitized = re.sub(r'("[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|`[^`\\]*(?:\\.[^`\\]*)*`)', '""', sanitized)

            for char in sanitized:
                if char == "{":
                    brace_count += 1
                    found_open = True
                elif char == "}":
                    if found_open:
                        brace_count -= 1
                        if brace_count == 0:
                            return idx + 1

            # If no opening brace found by line 5 after start, assume single-line statement
            if not found_open and idx > start_idx + 4:
                return start_line

        return start_line if not found_open else total

    # ── Generic Parser (Go, Rust, C, C++, Java, etc.) ─────────────────────────
    def _extract_generic_symbols(self, raw: str, lines: list[str], rel_path: str) -> list[SymbolEntry]:
        symbols: list[SymbolEntry] = []
        # Match common function / class patterns
        gen_re = re.compile(
            r"^[ \t]*(?:(?:pub|public|private|protected|static|async|fn|func)\s+)*(?:fn|func|function|class|struct|interface|void|int|bool|string)\s+([a-zA-Z0-9_]+)\b",
            re.MULTILINE
        )
        for match in gen_re.finditer(raw):
            name = match.group(1)
            line_idx = raw[:match.start()].count("\n") + 1
            end_line = self._infer_brace_block_end_line(lines, line_idx)
            symbols.append(SymbolEntry(
                name=name,
                kind="function",
                path=rel_path,
                start_line=line_idx,
                end_line=end_line,
                snippet=self._make_snippet(lines, line_idx, end_line),
            ))
        symbols.sort(key=lambda s: s.start_line)
        return symbols

    def _make_snippet(self, lines: list[str], start_line: int, end_line: int, max_lines: int = 15) -> str:
        s_idx = max(0, start_line - 1)
        e_idx = min(len(lines), end_line)
        selected = lines[s_idx:e_idx]
        if len(selected) > max_lines:
            selected = selected[:max_lines] + [f"... ({len(lines[s_idx:e_idx]) - max_lines} more lines)"]
        return "\n".join(selected)

    # ── Search & References ───────────────────────────────────────────────────
    def find_symbol(self, workspace: str, name: str) -> list[SymbolEntry]:
        """Search workspace code files for symbols matching name."""
        ws_path = normalize_workspace(workspace)
        exact_matches: list[SymbolEntry] = []

        # 1. Search existing cached files first
        with self._lock:
            cached_paths = list(self._cache.keys())

        for p_str in cached_paths:
            p = Path(p_str)
            if p.exists() and p.is_file():
                for sym in self._cache.get(p_str, []):
                    if sym.name == name:
                        exact_matches.append(sym)

        if exact_matches:
            return exact_matches

        # 2. Walk workspace code files lazily
        for dirpath, dirnames, filenames in os.walk(ws_path):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_SCAN_DIRS and not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                ext = Path(fname).suffix.lower()
                if ext not in CODE_EXTENSIONS:
                    continue

                full_file = Path(dirpath) / fname
                try:
                    if full_file.stat().st_size > 2_000_000:
                        continue
                except OSError:
                    continue

                file_syms = self.index_file(full_file, workspace=str(ws_path))
                for sym in file_syms:
                    if sym.name == name:
                        exact_matches.append(sym)

                # Return early if multiple matches found
                if len(exact_matches) >= 10:
                    break
            if len(exact_matches) >= 10:
                break

        return exact_matches

    def references_to(self, workspace: str, name: str, max_results: int = 50) -> list[dict[str, Any]]:
        """Scan workspace code files for symbol name word-boundary references (call sites, imports, assignments)."""
        ws_path = normalize_workspace(workspace)
        results: list[dict[str, Any]] = []

        clean_name = name.strip()
        if not clean_name:
            return []

        pattern = re.compile(rf"\b{re.escape(clean_name)}\b")

        for dirpath, dirnames, filenames in os.walk(ws_path):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_SCAN_DIRS and not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                ext = Path(fname).suffix.lower()
                if ext not in CODE_EXTENSIONS:
                    continue

                full_p = Path(dirpath) / fname
                try:
                    if full_p.stat().st_size > 1_500_000:
                        continue
                    text = full_p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                if clean_name not in text:
                    continue

                rel_p = str(full_p.relative_to(ws_path)).replace("\\", "/")
                lines = text.splitlines()
                for line_no, line in enumerate(lines, start=1):
                    if pattern.search(line):
                        results.append({
                            "path": rel_p,
                            "line": line_no,
                            "text": line.strip()[:160],
                        })
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        results.sort(key=lambda r: (r["path"], r["line"]))
        return results


# Global Symbol Index Singleton
_symbol_index = SymbolIndexManager()


def index_file(path: str | Path, workspace: str | None = None) -> list[SymbolEntry]:
    return _symbol_index.index_file(path, workspace=workspace)


def symbols_in_file(path: str | Path, workspace: str | None = None) -> list[SymbolEntry]:
    return _symbol_index.index_file(path, workspace=workspace)


def find_symbol(workspace: str, name: str) -> list[SymbolEntry]:
    return _symbol_index.find_symbol(workspace, name)


def references_to(workspace: str, name: str, max_results: int = 50) -> list[dict[str, Any]]:
    return _symbol_index.references_to(workspace, name, max_results=max_results)


def invalidate_file(path: str | Path) -> None:
    _symbol_index.invalidate(path)
    try:
        from .repo_map import invalidate_repo_map_cache
        invalidate_repo_map_cache(path)
    except Exception:
        pass


def clear_symbol_index() -> None:
    _symbol_index.clear()
    try:
        from .repo_map import clear_repo_map_cache
        clear_repo_map_cache()
    except Exception:
        pass
