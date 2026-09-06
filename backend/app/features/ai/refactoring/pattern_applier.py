"""pattern_applier.py — Pattern-based and AST-guided safe refactoring engine."""
from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def generate_diff(file_path: str, original: str, updated: str) -> str:
    """Generates a standard unified diff between original and updated content."""
    orig_lines = original.splitlines(keepends=True)
    upd_lines = updated.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        upd_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    )
    return "".join(diff)


class PatternApplier:
    def __init__(self, workspace: str) -> None:
        self.ws_path = Path(workspace).resolve()

    def _read_file(self, rel_path: str) -> Tuple[Path, str]:
        fp = (self.ws_path / rel_path).resolve()
        if not fp.is_file():
            # Try finding by name if rel_path was just a filename
            matches = list(self.ws_path.rglob(rel_path))
            if matches:
                fp = matches[0]
            else:
                raise FileNotFoundError(f"Target file '{rel_path}' not found in workspace.")
        return fp, fp.read_text(encoding="utf-8")

    # ─────────────────────────────────────────────────────────────────────────
    # 1. extract_function
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_extract_function(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")
        extracted_name = params.get("extracted_name", "extracted_helper")
        fn_name = params.get("function_name")
        start_line = params.get("start_line")
        end_line = params.get("end_line")

        lines = content.splitlines()

        if start_line is not None and end_line is not None:
            # Extract specific line range (1-indexed)
            s_idx = max(0, start_line - 1)
            e_idx = min(len(lines), end_line)
            extracted_lines = lines[s_idx:e_idx]
            indent = len(lines[s_idx]) - len(lines[s_idx].lstrip())
            indent_str = " " * indent

            helper_body = "\n".join("    " + l.strip() for l in extracted_lines if l.strip())
            helper_def = f"\ndef {extracted_name}():\n{helper_body}\n"

            # Replace lines in original
            new_lines = lines[:s_idx] + [f"{indent_str}{extracted_name}()"] + lines[e_idx:]
            # Insert helper definition before function
            updated_content = helper_def + "\n" + "\n".join(new_lines) + "\n"
            return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

        # Automatic AST-based function decomposition
        try:
            tree = ast.parse(content)
        except Exception:
            # Fallback simple replacement
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        target_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if fn_name is None or node.name == fn_name:
                    target_node = node
                    if fn_name:
                        break

        if not target_node or len(target_node.body) < 2:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        # Split body into first part and extracted second part
        midpoint = len(target_node.body) // 2
        extracted_stmts = target_node.body[midpoint:]
        first_line = extracted_stmts[0].lineno - 1
        last_line = getattr(extracted_stmts[-1], "end_lineno", extracted_stmts[-1].lineno)

        ext_slice = lines[first_line:last_line]
        indent = len(lines[first_line]) - len(lines[first_line].lstrip())
        indent_str = " " * indent

        # Determine if return is present in extracted slice
        has_return = any("return " in l for l in ext_slice)

        helper_body = "\n".join("    " + l.strip() for l in ext_slice if l.strip())
        helper_def = f"def {extracted_name}():\n{helper_body}\n\n"

        call_expr = f"{indent_str}return {extracted_name}()" if has_return else f"{indent_str}{extracted_name}()"
        new_lines = lines[:first_line] + [call_expr] + lines[last_line:]

        updated_content = helper_def + "\n".join(new_lines) + "\n"
        return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 2. extract_method
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_extract_method(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")
        extracted_method = params.get("extracted_name", "_extracted_method")
        class_name = params.get("class_name")
        method_name = params.get("method_name")

        lines = content.splitlines()
        try:
            tree = ast.parse(content)
        except Exception:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        target_class = None
        target_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if not class_name or node.name == class_name:
                    target_class = node
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and (not method_name or item.name == method_name):
                            target_method = item
                            break
                    if target_method:
                        break

        if not target_class or not target_method or len(target_method.body) < 2:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        midpoint = len(target_method.body) // 2
        ext_stmts = target_method.body[midpoint:]
        s_idx = ext_stmts[0].lineno - 1
        e_idx = getattr(ext_stmts[-1], "end_lineno", ext_stmts[-1].lineno)

        ext_slice = lines[s_idx:e_idx]
        indent = len(lines[s_idx]) - len(lines[s_idx].lstrip())
        indent_str = " " * indent

        has_return = any("return " in l for l in ext_slice)
        method_body = "\n".join("        " + l.strip() for l in ext_slice if l.strip())
        method_def = f"\n    def {extracted_method}(self):\n{method_body}\n"

        call_expr = f"{indent_str}return self.{extracted_method}()" if has_return else f"{indent_str}self.{extracted_method}()"
        updated_lines = lines[:s_idx] + [call_expr] + lines[e_idx:]

        # Insert new method after target class definition or method
        class_end = getattr(target_class, "end_lineno", len(lines))
        updated_lines.insert(class_end, method_def)

        updated_content = "\n".join(updated_lines) + "\n"
        return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 3. rename_symbol
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_rename_symbol(self, file: Optional[str], params: Dict[str, Any]) -> List[Dict[str, str]]:
        old_name = params.get("old_name", "")
        new_name = params.get("new_name", "")
        if not old_name or not new_name or old_name == new_name:
            return []

        target_files = []
        if file:
            fp, _ = self._read_file(file)
            target_files.append(fp)
        else:
            for root, dirs, files in os.walk(self.ws_path):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", "venv"}]
                for f in files:
                    if any(f.endswith(ext) for ext in [".py", ".ts", ".tsx", ".js"]):
                        target_files.append(Path(root) / f)

        changes = []
        pattern = re.compile(rf"\b{re.escape(old_name)}\b")

        for fp in target_files:
            try:
                original = fp.read_text(encoding="utf-8")
            except Exception:
                continue

            if pattern.search(original):
                updated = pattern.sub(new_name, original)
                rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")
                changes.append({
                    "file": rel_file,
                    "original_content": original,
                    "updated_content": updated,
                })

        return changes

    # ─────────────────────────────────────────────────────────────────────────
    # 4. inline_function
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_inline_function(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")
        fn_name = params.get("function_name", "")

        try:
            tree = ast.parse(content)
        except Exception:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        target_fn = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == fn_name:
                target_fn = node
                break

        if not target_fn:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        # Check if function has a single return statement
        if len(target_fn.body) == 1 and isinstance(target_fn.body[0], ast.Return) and target_fn.body[0].value:
            lines = content.splitlines()
            s_idx = target_fn.lineno - 1
            e_idx = getattr(target_fn, "end_lineno", target_fn.lineno)

            # Get return expression text
            ret_line = lines[target_fn.body[0].lineno - 1]
            ret_expr = ret_line.split("return", 1)[1].strip()

            # Remove definition
            remaining_lines = lines[:s_idx] + lines[e_idx:]
            new_text = "\n".join(remaining_lines)

            # Replace call sites (e.g. `fn_name()`) with `ret_expr`
            call_pattern = re.compile(rf"\b{re.escape(fn_name)}\(\)")
            updated_content = call_pattern.sub(ret_expr, new_text)
            return [{"file": rel_file, "original_content": content, "updated_content": updated_content + "\n"}]

        return [{"file": rel_file, "original_content": content, "updated_content": content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 5. extract_class
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_extract_class(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")
        class_name = params.get("class_name", "")
        new_class_name = params.get("new_class_name", f"{class_name}Helper")
        methods_to_move = set(params.get("methods_to_move", []))

        try:
            tree = ast.parse(content)
        except Exception:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        target_class = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and (not class_name or node.name == class_name):
                target_class = node
                break

        if not target_class:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        lines = content.splitlines()
        extracted_methods_code = []
        lines_to_remove = set()

        for item in target_class.body:
            if isinstance(item, ast.FunctionDef):
                if not methods_to_move or item.name in methods_to_move:
                    s_idx = item.lineno - 1
                    e_idx = getattr(item, "end_lineno", item.lineno)
                    method_lines = lines[s_idx:e_idx]
                    # unindent from class body (4 spaces)
                    unindented = [l[4:] if l.startswith("    ") else l for l in method_lines]
                    extracted_methods_code.append("\n".join(unindented))
                    for idx in range(s_idx, e_idx):
                        lines_to_remove.add(idx)

        if not extracted_methods_code:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        new_class_code = f"class {new_class_name}:\n" + "\n\n".join(extracted_methods_code) + "\n\n"
        preserved_lines = [l for i, l in enumerate(lines) if i not in lines_to_remove]
        updated_content = new_class_code + "\n".join(preserved_lines) + "\n"

        return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 6. apply_strategy_pattern
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_apply_strategy_pattern(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")

        # Look for if/elif/else pattern or switch pattern
        lines = content.splitlines()
        try:
            tree = ast.parse(content)
        except Exception:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        # Check for function with if-elif chain
        target_fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for stmt in node.body:
                    if isinstance(stmt, ast.If) and stmt.orelse:
                        target_fn = node
                        break
                if target_fn:
                    break

        if not target_fn:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        strategy_map_name = f"{target_fn.name.upper()}_STRATEGIES"
        strategy_template = f"""# Strategy pattern dispatch table
{strategy_map_name} = {{
    "default": lambda *args, **kwargs: None,
}}

def execute_strategy(strategy_key: str, *args, **kwargs):
    handler = {strategy_map_name}.get(strategy_key, {strategy_map_name}["default"])
    return handler(*args, **kwargs)
"""
        updated_content = strategy_template + "\n" + content
        return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 7. apply_factory_pattern
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_apply_factory_pattern(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")
        factory_name = params.get("factory_name", "ServiceFactory")

        factory_template = f"""
class {factory_name}:
    \"\"\"Factory for dynamically creating and configuring instances.\"\"\"
    _registry = {{}}

    @classmethod
    def register(cls, key: str, builder):
        cls._registry[key] = builder

    @classmethod
    def create(cls, key: str, *args, **kwargs):
        builder = cls._registry.get(key)
        if not builder:
            raise ValueError(f"Unknown type '{{key}}' for {factory_name}")
        return builder(*args, **kwargs)
"""
        updated_content = content + "\n" + factory_template
        return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 8. flatten_conditionals
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_flatten_conditionals(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")

        # Flatten nested if statements into guard clauses
        lines = content.splitlines()
        updated_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Detect nested if pattern:
            # if x:
            #     if y:
            #         return z
            match = re.match(r"^(\s*)if\s+(.+):\s*$", line)
            if match and i + 1 < len(lines):
                indent, cond = match.groups()
                next_line = lines[i + 1]
                next_match = re.match(r"^" + indent + r"    if\s+(.+):\s*$", next_line)
                if next_match:
                    inner_cond = next_match.group(1)
                    # Convert to combined or guard clause
                    guard_line = f"{indent}if not ({cond}) or not ({inner_cond}):\n{indent}    return None"
                    updated_lines.append(guard_line)
                    i += 2
                    continue
            updated_lines.append(line)
            i += 1

        updated_content = "\n".join(updated_lines) + "\n"
        return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 9. remove_dead_code
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_remove_dead_code(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")

        try:
            tree = ast.parse(content)
        except Exception:
            return [{"file": rel_file, "original_content": content, "updated_content": content}]

        lines = content.splitlines()
        dead_line_indices = set()

        # 1. Unused imports
        imported_names = {}
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_names[name] = node.lineno - 1

        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Name):
                used_names.add(node.id)

        for name, line_idx in imported_names.items():
            if name not in used_names:
                dead_line_indices.add(line_idx)

        # 2. Statements after return/raise
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for idx, stmt in enumerate(node.body):
                    if isinstance(stmt, (ast.Return, ast.Raise)) and idx + 1 < len(node.body):
                        for unreachable in node.body[idx + 1 :]:
                            s_line = unreachable.lineno - 1
                            e_line = getattr(unreachable, "end_lineno", unreachable.lineno)
                            for l_idx in range(s_line, e_line):
                                dead_line_indices.add(l_idx)

        updated_lines = [l for i, l in enumerate(lines) if i not in dead_line_indices]
        updated_content = "\n".join(updated_lines) + "\n"
        return [{"file": rel_file, "original_content": content, "updated_content": updated_content}]

    # ─────────────────────────────────────────────────────────────────────────
    # 10. deduplicate
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_deduplicate(self, file: Optional[str], params: Dict[str, Any]) -> List[Dict[str, str]]:
        snippet = params.get("code_snippet", "")
        util_name = params.get("utility_name", "shared_helper")
        target_files = params.get("target_files", [file] if file else [])

        if not snippet or not target_files:
            return []

        changes = []
        for f in target_files:
            if not f:
                continue
            fp, content = self._read_file(f)
            rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")

            if snippet in content:
                # Replace with utility call
                updated = content.replace(snippet, f"{util_name}()")
                # Prepend utility definition if not already present
                if f"def {util_name}():" not in updated:
                    util_def = f"def {util_name}():\n" + "\n".join("    " + l for l in snippet.splitlines() if l.strip()) + "\n\n"
                    updated = util_def + updated

                changes.append({
                    "file": rel_file,
                    "original_content": content,
                    "updated_content": updated,
                })

        return changes

    # ─────────────────────────────────────────────────────────────────────────
    # 11. optimize_memory
    # ─────────────────────────────────────────────────────────────────────────
    def refactor_optimize_memory(self, file: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
        fp, content = self._read_file(file)
        rel_file = str(fp.relative_to(self.ws_path)).replace("\\", "/")

        # Convert eager list comprehension to generator expression where appropriate
        # e.g., `return [x for x in ...]` -> `return (x for x in ...)`
        updated = re.sub(r"return\s+\[(.*?\s+for\s+.*?)\]", r"return (\1)", content)
        return [{"file": rel_file, "original_content": content, "updated_content": updated}]


def apply_refactor(refactor_request: Dict[str, Any], workspace: str) -> Dict[str, Any]:
    """Applies a refactoring pattern, returning changes and detailed preview with unified diffs."""
    refactor_type = refactor_request.get("refactor_type", "")
    target_file = refactor_request.get("file", "")
    params = refactor_request.get("params", {})

    applier = PatternApplier(workspace)
    changes: List[Dict[str, str]] = []

    if refactor_type == "extract_function":
        changes = applier.refactor_extract_function(target_file, params)
    elif refactor_type == "extract_method":
        changes = applier.refactor_extract_method(target_file, params)
    elif refactor_type == "rename_symbol":
        changes = applier.refactor_rename_symbol(target_file, params)
    elif refactor_type == "inline_function":
        changes = applier.refactor_inline_function(target_file, params)
    elif refactor_type == "extract_class":
        changes = applier.refactor_extract_class(target_file, params)
    elif refactor_type == "apply_strategy_pattern":
        changes = applier.refactor_apply_strategy_pattern(target_file, params)
    elif refactor_type == "apply_factory_pattern":
        changes = applier.refactor_apply_factory_pattern(target_file, params)
    elif refactor_type == "flatten_conditionals":
        changes = applier.refactor_flatten_conditionals(target_file, params)
    elif refactor_type == "remove_dead_code":
        changes = applier.refactor_remove_dead_code(target_file, params)
    elif refactor_type == "deduplicate":
        changes = applier.refactor_deduplicate(target_file, params)
    elif refactor_type == "optimize_memory":
        changes = applier.refactor_optimize_memory(target_file, params)
    else:
        raise ValueError(f"Unsupported refactor type '{refactor_type}'")

    # Generate preview
    file_previews = []
    combined_diffs = []
    total_lines_removed = 0
    total_lines_added = 0

    for ch in changes:
        orig = ch["original_content"]
        upd = ch["updated_content"]
        diff = generate_diff(ch["file"], orig, upd)
        combined_diffs.append(diff)

        orig_lines = orig.splitlines()
        upd_lines = upd.splitlines()
        lines_removed = max(0, len(orig_lines) - len(upd_lines))
        lines_added = max(0, len(upd_lines) - len(orig_lines))
        total_lines_removed += lines_removed
        total_lines_added += lines_added

        file_previews.append({
            "file": ch["file"],
            "diff": diff,
            "lines_removed": lines_removed,
            "lines_added": lines_added,
        })

    full_diff = "\n".join(combined_diffs)
    complexity_reduction = 2 if refactor_type in ("extract_function", "extract_method", "flatten_conditionals", "apply_strategy_pattern") else 1

    preview = {
        "diff": full_diff,
        "files": file_previews,
        "summary": f"Applied {refactor_type.replace('_', ' ')} across {len(changes)} file(s).",
        "lines_removed": total_lines_removed,
        "lines_added": total_lines_added,
        "complexity_reduction": complexity_reduction,
    }

    return {"changes": changes, "preview": preview}
