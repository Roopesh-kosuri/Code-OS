"""analyze_service.py — AST and heuristic-based code smell detection, duplicate detection, and complexity analysis."""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "venv",
    ".venv",
    "dist",
    "build",
    ".tempmediaStorage",
}

CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Complexity Visitor
# ─────────────────────────────────────────────────────────────────────────────

class CognitiveComplexityVisitor(ast.NodeVisitor):
    """Calculates cognitive complexity by weighting control structures by their nesting depth."""

    def __init__(self) -> None:
        self.complexity = 0
        self.nesting_level = 0

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1 + self.nesting_level
        self.nesting_level += 1
        self.generic_visit(node)
        self.nesting_level -= 1

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1 + self.nesting_level
        self.nesting_level += 1
        self.generic_visit(node)
        self.nesting_level -= 1

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1 + self.nesting_level
        self.nesting_level += 1
        self.generic_visit(node)
        self.nesting_level -= 1

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1 + self.nesting_level
        self.nesting_level += 1
        self.generic_visit(node)
        self.nesting_level -= 1

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1 + self.nesting_level
        self.nesting_level += 1
        self.generic_visit(node)
        self.nesting_level -= 1

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # A sequence of boolean operators adds 1 to cognitive complexity
        self.complexity += len(node.values) - 1
        self.generic_visit(node)


def calculate_cyclomatic_complexity(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Calculates McCabe Cyclomatic Complexity for a function node."""
    complexity = 1
    for child in ast.walk(fn_node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.Assert)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
    return complexity


def calculate_cognitive_complexity(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Calculates Cognitive Complexity for a function node."""
    visitor = CognitiveComplexityVisitor()
    for item in fn_node.body:
        visitor.visit(item)
    return visitor.complexity


# ─────────────────────────────────────────────────────────────────────────────
# 2. Code Smell Detection
# ─────────────────────────────────────────────────────────────────────────────

def _collect_files(workspace: str, file_paths: Optional[List[str]] = None) -> List[Path]:
    ws_path = Path(workspace).resolve()
    if file_paths:
        collected = []
        for p in file_paths:
            fp = Path(p)
            if not fp.is_absolute():
                fp = ws_path / p
            if fp.is_file():
                collected.append(fp)
        return collected

    collected = []
    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for f in files:
            p = Path(root) / f
            if p.suffix in CODE_EXTENSIONS:
                collected.append(p)
    return collected


def detect_code_smells(workspace: str, file_paths: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Detects 8 categories of code smells across the specified workspace or files:

    1. long_function: function lines > 20
    2. deep_nesting: nesting depth >= 4
    3. duplicated_code: repeated identical or near-identical code blocks
    4. dead_code: unreachable code or unused internal helpers
    5. unused_imports: imports never referenced in code
    6. god_class: class with excessive methods (> 8) or lines (> 100)
    7. complex_conditional: conditions with 3+ boolean operators or high nesting
    8. magic_numbers: raw unexplained numeric literals in expressions
    """
    ws_path = Path(workspace).resolve()
    files = _collect_files(workspace, file_paths)
    smells: List[Dict[str, Any]] = []

    # Detect duplicates across files first
    duplicate_groups = find_duplicates(workspace)
    for dup in duplicate_groups:
        for loc in dup.get("locations", []):
            smells.append({
                "type": "duplicated_code",
                "location": {
                    "file": loc["file"],
                    "line": loc["lines"][0],
                    "end_line": loc["lines"][1],
                },
                "severity": "Warning",
                "suggestion": "Extract duplicated logic into a shared utility function.",
                "details": f"Duplicated block ({loc['lines'][1] - loc['lines'][0] + 1} lines) matches another section in the workspace."
            })

    for file_path in files:
        rel_path = str(file_path.relative_to(ws_path)).replace("\\", "/")
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        if file_path.suffix == ".py":
            try:
                tree = ast.parse(content, filename=str(file_path))
            except Exception:
                # Syntax error or unparseable, continue
                continue

            # Check unused imports
            _detect_unused_imports(tree, rel_path, smells)

            # Walk AST for class/function/expression smells
            for node in ast.walk(tree):
                # 1. God class
                if isinstance(node, ast.ClassDef):
                    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    end_lineno = getattr(node, "end_lineno", node.lineno)
                    class_len = end_lineno - node.lineno + 1
                    if len(methods) > 8 or class_len > 100:
                        smells.append({
                            "type": "god_class",
                            "location": {
                                "file": rel_path,
                                "line": node.lineno,
                                "end_line": end_lineno,
                            },
                            "severity": "Critical",
                            "suggestion": f"Class '{node.name}' has {len(methods)} methods and {class_len} lines. Split into focused classes using extract_class.",
                            "details": f"Class has high responsibility footprint ({len(methods)} methods, {class_len} lines)."
                        })

                # 2. Long function & Deep nesting
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end_lineno = getattr(node, "end_lineno", node.lineno)
                    func_len = end_lineno - node.lineno + 1
                    if func_len > 20:
                        smells.append({
                            "type": "long_function",
                            "location": {
                                "file": rel_path,
                                "line": node.lineno,
                                "end_line": end_lineno,
                            },
                            "severity": "Critical" if func_len > 50 else "Warning",
                            "description": f"Function '{node.name}' is {func_len} lines long ({func_len} > 20).",
                            "message": f"Function '{node.name}' is {func_len} lines long.",
                            "suggestion": f"Function '{node.name}' is {func_len} lines long. Extract helpers using extract_function.",
                            "details": f"Function '{node.name}' exceeds recommended 20-line threshold."
                        })

                    # Check deep nesting inside this function
                    max_depth, deep_line = _calculate_max_nesting(node)
                    if max_depth >= 4:
                        smells.append({
                            "type": "deep_nesting",
                            "location": {
                                "file": rel_path,
                                "line": deep_line,
                                "end_line": end_lineno,
                            },
                            "severity": "Warning",
                            "suggestion": f"Deep nesting level ({max_depth}) in '{node.name}'. Flatten conditionals using guard clauses.",
                            "details": f"Control flow is nested {max_depth} levels deep."
                        })

                    # Check dead code in function body
                    _detect_dead_code_in_body(node.body, rel_path, smells)

                # 3. Complex conditional
                if isinstance(node, (ast.If, ast.While)):
                    if isinstance(node.test, ast.BoolOp):
                        if len(node.test.values) >= 3 or _count_bool_ops(node.test) >= 3:
                            smells.append({
                                "type": "complex_conditional",
                                "location": {
                                    "file": rel_path,
                                    "line": node.lineno,
                                    "end_line": getattr(node.test, "end_lineno", node.lineno),
                                },
                                "severity": "Warning",
                                "suggestion": "Simplify complex conditional expression using strategy pattern or boolean helper variables.",
                                "details": f"Conditional has {len(node.test.values)} combined conditions."
                            })

                # 4. Magic numbers
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                    val = node.value
                    if val not in (0, 1, -1, 2, 100, 0.0, 1.0, 100.0, 200, 404, 500):
                        # Ensure it's not a top-level constant definition e.g. CONSTANT = 42
                        if not _is_top_level_assignment(tree, node):
                            smells.append({
                                "type": "magic_numbers",
                                "location": {
                                    "file": rel_path,
                                    "line": node.lineno,
                                    "end_line": node.lineno,
                                },
                                "severity": "Info",
                                "suggestion": f"Magic number {val} used directly. Extract into a named constant.",
                                "details": f"Literal {val} without semantic name."
                            })

        else:
            # Fallback for JS/TS/other files using heuristic line scanning
            _detect_heuristic_smells(content, rel_path, smells)

    for s in smells:
        if "description" not in s:
            s["description"] = s.get("details") or s.get("suggestion") or s.get("message", "")
        if "message" not in s:
            s["message"] = s.get("description") or s.get("suggestion") or ""

    return smells


def _is_top_level_assignment(tree: ast.AST, const_node: ast.Constant) -> bool:
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            if node.value is const_node:
                return True
    return False


def _count_bool_ops(node: ast.AST) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.BoolOp):
            count += len(child.values) - 1
    return count


def _calculate_max_nesting(fn_node: ast.AST) -> Tuple[int, int]:
    """Returns (max_depth, line_of_deepest_node)."""
    max_depth = 0
    deepest_line = getattr(fn_node, "lineno", 1)

    def walk_depth(node: ast.AST, current_depth: int) -> None:
        nonlocal max_depth, deepest_line
        is_nesting_node = isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith))
        next_depth = current_depth + 1 if is_nesting_node else current_depth
        if next_depth > max_depth:
            max_depth = next_depth
            deepest_line = getattr(node, "lineno", deepest_line)

        for child in ast.iter_child_nodes(node):
            walk_depth(child, next_depth)

    for stmt in getattr(fn_node, "body", []):
        walk_depth(stmt, 0)

    return max_depth, deepest_line


def _detect_unused_imports(tree: ast.AST, rel_path: str, smells: List[Dict[str, Any]]) -> None:
    imported_names: Dict[str, Tuple[str, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = (alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = (alias.name, node.lineno)

    used_names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            used_names.add(node.value.id)

    for name, (orig_name, lineno) in imported_names.items():
        if name not in used_names and not name.startswith("_"):
            smells.append({
                "type": "unused_imports",
                "location": {
                    "file": rel_path,
                    "line": lineno,
                    "end_line": lineno,
                },
                "severity": "Info",
                "suggestion": f"Import '{orig_name}' is unused. Remove to clean up dependencies.",
                "details": f"'{orig_name}' imported but never referenced in module."
            })


def _detect_dead_code_in_body(stmts: List[ast.stmt], rel_path: str, smells: List[Dict[str, Any]]) -> None:
    for idx, stmt in enumerate(stmts):
        if isinstance(stmt, (ast.Return, ast.Raise)):
            # If there are statements after return/raise in the same block, they are unreachable
            if idx + 1 < len(stmts):
                dead_stmt = stmts[idx + 1]
                end_line = getattr(stmts[-1], "end_lineno", dead_stmt.lineno)
                smells.append({
                    "type": "dead_code",
                    "location": {
                        "file": rel_path,
                        "line": dead_stmt.lineno,
                        "end_line": end_line,
                    },
                    "severity": "Info",
                    "suggestion": "Unreachable dead code found after return/raise statement. Delete unused lines.",
                    "details": "Statements cannot be executed."
                })
                break
        for child in ast.iter_child_nodes(stmt):
            child_body = getattr(child, "body", None)
            if isinstance(child_body, list):
                _detect_dead_code_in_body(child_body, rel_path, smells)


def _detect_heuristic_smells(content: str, rel_path: str, smells: List[Dict[str, Any]]) -> None:
    lines = content.splitlines()
    fn_start = -1
    fn_indent = 0
    brace_depth = 0
    max_brace_depth = 0

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Heuristic long function in JS/TS
        if ("function " in stripped or "=>" in stripped or stripped.startswith("def ")) and fn_start == -1:
            fn_start = i
            fn_indent = len(line) - len(line.lstrip())

        if fn_start != -1 and (i - fn_start > 35):
            smells.append({
                "type": "long_function",
                "location": {"file": rel_path, "line": fn_start, "end_line": i},
                "severity": "Warning",
                "suggestion": "Long function detected. Split into smaller modular helpers.",
                "details": f"Function spans more than 35 lines in {rel_path}."
            })
            fn_start = -1

        brace_depth += line.count("{") - line.count("}")
        if brace_depth >= 4 and brace_depth > max_brace_depth:
            max_brace_depth = brace_depth
            smells.append({
                "type": "deep_nesting",
                "location": {"file": rel_path, "line": i, "end_line": i},
                "severity": "Warning",
                "suggestion": f"Deep nesting level ({brace_depth}) detected. Flatten using guard clauses.",
                "details": f"Nesting depth {brace_depth} in {rel_path}."
            })


# ─────────────────────────────────────────────────────────────────────────────
# 3. Duplication Finder
# ─────────────────────────────────────────────────────────────────────────────

def find_duplicates(workspace: str, min_lines: int = 4) -> List[Dict[str, Any]]:
    """Finds repeated duplicate code blocks of at least min_lines across workspace files."""
    ws_path = Path(workspace).resolve()
    files = _collect_files(workspace)

    file_lines: Dict[str, List[str]] = {}
    file_norm: Dict[str, List[str]] = {}
    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        lines = content.splitlines()
        rel_path = str(file_path.relative_to(ws_path)).replace("\\", "/")
        file_lines[rel_path] = lines
        file_norm[rel_path] = [l.strip() for l in lines]

    duplicates: List[Dict[str, Any]] = []
    ngram_index: Dict[Tuple[str, ...], List[Tuple[str, int]]] = {}

    for rel_path, nlines in file_norm.items():
        if len(nlines) < min_lines:
            continue
        for i in range(len(nlines) - min_lines + 1):
            chunk = tuple(nlines[i : i + min_lines])
            if all(not l or l.startswith(("#", "//", "/*", "*")) for l in chunk):
                continue
            ngram_index.setdefault(chunk, []).append((rel_path, i))

    seen_pairs: Set[Tuple[Tuple[str, int, int], Tuple[str, int, int]]] = set()

    for chunk, occurrences in ngram_index.items():
        if len(occurrences) < 2:
            continue
        for idx1 in range(len(occurrences)):
            for idx2 in range(idx1 + 1, len(occurrences)):
                f1, s1 = occurrences[idx1]
                f2, s2 = occurrences[idx2]
                if f1 == f2 and abs(s1 - s2) < min_lines:
                    continue

                match_len = min_lines
                lines1 = file_norm[f1]
                lines2 = file_norm[f2]
                while (
                    s1 + match_len < len(lines1)
                    and s2 + match_len < len(lines2)
                    and lines1[s1 + match_len] == lines2[s2 + match_len]
                ):
                    match_len += 1

                range1 = (f1, s1 + 1, s1 + match_len)
                range2 = (f2, s2 + 1, s2 + match_len)
                pair_key = (range1, range2) if range1 <= range2 else (range2, range1)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                raw_snippet = "\n".join(file_lines[f1][s1 : s1 + match_len])
                duplicates.append({
                    "code_snippet": raw_snippet,
                    "locations": [
                        {"file": f1, "lines": [s1 + 1, s1 + match_len]},
                        {"file": f2, "lines": [s2 + 1, s2 + match_len]},
                    ],
                    "occurrences": [
                        {"file": f1, "lines": [s1 + 1, s1 + match_len]},
                        {"file": f2, "lines": [s2 + 1, s2 + match_len]},
                    ],
                    "line_count": match_len,
                    "similarity": 1.0,
                })

    duplicates.sort(key=lambda d: d["line_count"], reverse=True)
    filtered: List[Dict[str, Any]] = []
    seen_loc_sets: Set[str] = set()
    for d in duplicates:
        loc_key = "-".join(f"{loc['file']}:{loc['lines'][0]}-{loc['lines'][1]}" for loc in d["locations"])
        if loc_key not in seen_loc_sets:
            seen_loc_sets.add(loc_key)
            filtered.append(d)

    return filtered


# ─────────────────────────────────────────────────────────────────────────────
# 4. Complexity Analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_complexity(workspace: str) -> Dict[str, Any]:
    """Analyzes cyclomatic and cognitive complexity for all functions across workspace."""
    ws_path = Path(workspace).resolve()
    files = _collect_files(workspace)
    functions_list: List[Dict[str, Any]] = []

    for file_path in files:
        if file_path.suffix != ".py":
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(file_path))
        except Exception:
            continue

        rel_path = str(file_path.relative_to(ws_path)).replace("\\", "/")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_lineno = getattr(node, "end_lineno", node.lineno)
                cyclo = calculate_cyclomatic_complexity(node)
                cogni = calculate_cognitive_complexity(node)

                functions_list.append({
                    "name": node.name,
                    "file": rel_path,
                    "lines": [node.lineno, end_lineno],
                    "cyclomatic_complexity": cyclo,
                    "cognitive_complexity": cogni,
                })

    return {"functions": functions_list}
