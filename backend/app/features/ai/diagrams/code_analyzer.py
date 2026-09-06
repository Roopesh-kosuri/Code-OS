"""code_analyzer.py — Local codebase AST and pattern analysis for architecture diagram generation.

Analyzes Python, TypeScript, and JavaScript codebases locally to detect:
- Components (modules, classes, services, controllers, models, stores, UI components)
- Dependency & import relationships
- API route definitions (FastAPI, Flask, Express, Django)
- Database entity relationships and foreign keys
- External service integrations (HTTP calls)
"""
from __future__ import annotations

import ast
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Extensions to scan
SCAN_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
IGNORE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "dist", "dist-electron",
    "build", ".pytest_cache", "__pycache__", ".idea", ".vscode", "coverage"
}


def analyze_codebase(workspace_path: str) -> Dict[str, Any]:
    """
    Analyze codebase at workspace_path.
    Returns:
        {
            "components": [...],
            "relationships": [...],
            "apis": [...],
            "models": [...],
            "stats": {...}
        }
    """
    root = Path(workspace_path).resolve()
    if not root.exists():
        return {
            "components": [],
            "relationships": [],
            "apis": [],
            "models": [],
            "stats": {"components": 0, "relationships": 0, "apis": 0, "models": 0},
        }

    components: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    apis: List[Dict[str, Any]] = []
    models: List[Dict[str, Any]] = []

    # Map file relative path to component info
    file_map: Dict[str, Dict[str, Any]] = {}
    known_component_names: Set[str] = set()

    for current_root, dirs, files in os.walk(root):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]

        for file_name in files:
            ext = Path(file_name).suffix.lower()
            if ext not in SCAN_EXTENSIONS:
                continue

            full_path = Path(current_root) / file_name
            rel_path = str(full_path.relative_to(root)).replace("\\", "/")

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug(f"Failed to read {full_path}: {e}")
                continue

            if ext == ".py":
                comp = _analyze_python_file(content, rel_path, apis, models)
            else:
                comp = _analyze_ts_js_file(content, rel_path, apis, models)

            if comp:
                components.append(comp)
                file_map[rel_path] = comp
                known_component_names.add(comp["name"])

    # Extract cross-component relationships
    relationships = _extract_relationships(components, file_map, apis, models)

    # Calculate statistics
    stats = {
        "components": len(components),
        "relationships": len(relationships),
        "apis": len(apis),
        "models": len(models),
    }

    return {
        "components": components,
        "relationships": relationships,
        "apis": apis,
        "models": models,
        "stats": stats,
    }


def _analyze_python_file(
    content: str, rel_path: str, apis: List[Dict[str, Any]], models: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Parse a Python source file using the standard library ast module."""
    base_name = Path(rel_path).stem
    comp_type = "module"
    if "route" in rel_path or "api" in rel_path or "controller" in rel_path:
        comp_type = "controller"
    elif "service" in rel_path:
        comp_type = "service"
    elif "model" in rel_path or "schema" in rel_path:
        comp_type = "model"

    classes: List[str] = []
    functions: List[str] = []
    imports: List[str] = []
    external_calls: List[str] = []

    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
                # Check if it's a database model or Pydantic schema
                base_names = [
                    b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
                    for b in node.bases
                ]
                if any(b in {"Base", "Model", "BaseModel", "DeclarativeBase", "Document"} for b in base_names):
                    fields, foreign_keys = _extract_model_fields_py(node)
                    models.append({
                        "name": node.name,
                        "file": rel_path,
                        "fields": fields,
                        "foreign_keys": foreign_keys,
                        "type": "database_model" if "BaseModel" not in base_names else "schema",
                    })

            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                functions.append(node.name)
                # Check for FastAPI / Flask route decorators
                for dec in node.decorator_list:
                    route_infos = _extract_py_route(dec, node.name, rel_path)
                    if route_infos:
                        apis.extend(route_infos)

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

            # Django url pattern calls: path("...", views.foo) or re_path("...", views.bar)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {"path", "re_path"}:
                    if node.args and len(node.args) >= 2:
                        path_val = None
                        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            path_val = node.args[0].value
                        handler_val = "django_view"
                        if isinstance(node.args[1], ast.Attribute):
                            handler_val = node.args[1].attr
                        elif isinstance(node.args[1], ast.Name):
                            handler_val = node.args[1].id
                        elif isinstance(node.args[1], ast.Call) and isinstance(node.args[1].func, ast.Attribute):
                            handler_val = getattr(node.args[1].func.value, "id", "View")
                        if path_val is not None:
                            parts = [p for p in path_val.strip("/").split("/") if p and p != "api"]
                            resource = parts[0] if parts else "root"
                            apis.append({
                                "method": "ANY",
                                "path": "/" + path_val.strip("/"),
                                "handler": handler_val,
                                "file": rel_path,
                                "resource": resource,
                            })

                # Detect external HTTP requests
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in {"get", "post", "put", "delete", "request"}:
                        if isinstance(node.func.value, ast.Name) and node.func.value.id in {"requests", "httpx", "aiohttp", "client"}:
                            external_calls.append(f"{node.func.value.id}.{node.func.attr}")
    except Exception as e:
        logger.debug(f"AST parse fallback for {rel_path}: {e}")
        # Fallback to regex if syntax error
        classes.extend(re.findall(r"class\s+([A-Za-z0-9_]+)", content))
        functions.extend(re.findall(r"def\s+([A-Za-z0-9_]+)", content))
        imports.extend(re.findall(r"(?:from|import)\s+([A-Za-z0-9_\.]+)", content))

    return {
        "id": rel_path.replace("/", "_").replace(".", "_"),
        "name": base_name,
        "path": rel_path,
        "type": comp_type,
        "language": "python",
        "classes": list(dict.fromkeys(classes)),
        "functions": list(dict.fromkeys(functions)),
        "imports": list(dict.fromkeys(imports)),
        "external_calls": list(set(external_calls)),
    }


def _extract_model_fields_py(node: ast.ClassDef) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Extract fields, types, and foreign key references from an AST class definition."""
    fields: List[Dict[str, str]] = []
    foreign_keys: List[Dict[str, str]] = []

    for item in node.body:
        field_name = None
        t_str = "Column"
        target_ref = None

        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            field_name = item.target.id
            if isinstance(item.annotation, ast.Name):
                t_str = item.annotation.id
            elif isinstance(item.annotation, ast.Attribute):
                t_str = item.annotation.attr
            elif isinstance(item.annotation, ast.Subscript):
                t_str = "Optional"

            # Check if assigned value is ForeignKey(...)
            if item.value and isinstance(item.value, ast.Call):
                target_ref = _find_foreign_key_arg(item.value)

        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    field_name = target.id
                    if item.value and isinstance(item.value, ast.Call):
                        target_ref = _find_foreign_key_arg(item.value)
                        # Check Column(Integer, ForeignKey(...)) or relationship("Other")
                        if isinstance(item.value.func, ast.Name):
                            func_name = item.value.func.id
                            if func_name == "relationship":
                                t_str = "Relationship"
                            elif func_name == "Column":
                                t_str = "Column"

        if field_name:
            fields.append({"name": field_name, "type": t_str})
            if target_ref:
                foreign_keys.append({"field": field_name, "target": target_ref})

    return fields, foreign_keys


def _find_foreign_key_arg(call_node: ast.Call) -> Optional[str]:
    """Inspect an AST Call for ForeignKey('target.id') or relationship('Target')."""
    # Direct ForeignKey("model.id")
    func_name = ""
    if isinstance(call_node.func, ast.Name):
        func_name = call_node.func.id
    elif isinstance(call_node.func, ast.Attribute):
        func_name = call_node.func.attr

    if func_name in {"ForeignKey", "relationship"}:
        if call_node.args and isinstance(call_node.args[0], ast.Constant) and isinstance(call_node.args[0].value, str):
            target = call_node.args[0].value.split(".")[0]
            return target

    # Nested Column(..., ForeignKey("model.id"))
    for arg in call_node.args:
        if isinstance(arg, ast.Call):
            res = _find_foreign_key_arg(arg)
            if res:
                return res

    return None


def _extract_py_route(dec: ast.expr, handler_name: str, file_path: str) -> List[Dict[str, Any]]:
    """Extract HTTP route details from FastAPI/Flask decorator."""
    if not isinstance(dec, ast.Call):
        return []

    routes: List[Dict[str, Any]] = []

    # Check @app.get("/path") or @router.post("/path")
    if isinstance(dec.func, ast.Attribute):
        attr_name = dec.func.attr.upper()
        if attr_name in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
            path = ""
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                path = dec.args[0].value
            elif dec.args and isinstance(dec.args[0], ast.Str):
                path = dec.args[0].s

            if path:
                parts = [p for p in path.strip("/").split("/") if p and p != "api" and not p.startswith("{")]
                resource = parts[0] if parts else "root"
                routes.append({
                    "method": attr_name,
                    "path": path,
                    "handler": handler_name,
                    "file": file_path,
                    "resource": resource,
                })

        # Check Flask @app.route("/path", methods=["GET", "POST"])
        elif dec.func.attr == "route":
            path = ""
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                path = dec.args[0].value
            methods = ["GET"]
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = [
                        elt.value for elt in kw.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ] or ["GET"]

            if path:
                parts = [p for p in path.strip("/").split("/") if p and p != "api" and not p.startswith("<")]
                resource = parts[0] if parts else "root"
                for m in methods:
                    routes.append({
                        "method": m.upper(),
                        "path": path,
                        "handler": handler_name,
                        "file": file_path,
                        "resource": resource,
                    })

    return routes


def _analyze_ts_js_file(
    content: str, rel_path: str, apis: List[Dict[str, Any]], models: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Parse TypeScript/JavaScript source file for components, routes, and imports."""
    base_name = Path(rel_path).stem
    comp_type = "module"
    if "routes" in rel_path or "controller" in rel_path or "api" in rel_path:
        comp_type = "controller"
    elif "store" in rel_path:
        comp_type = "store"
    elif "service" in rel_path:
        comp_type = "service"
    elif "component" in rel_path or rel_path.endswith((".tsx", ".jsx")):
        comp_type = "ui_component"
    elif "model" in rel_path or "type" in rel_path or "schema" in rel_path:
        comp_type = "model"

    # Classes & Interfaces
    classes = re.findall(r"class\s+([A-Za-z0-9_]+)", content)
    interfaces = re.findall(r"interface\s+([A-Za-z0-9_]+)", content)
    classes.extend(interfaces)

    # Functions
    functions = re.findall(r"(?:function\s+|const\s+)([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(", content)
    functions.extend(re.findall(r"function\s+([A-Za-z0-9_]+)\s*\(", content))

    # Imports
    imports = re.findall(r'from\s+[\'"]([^\'"]+)[\'"]', content)
    imports.extend(re.findall(r'require\([\'"]([^\'"]+)[\'"]\)', content))

    # External API calls (fetch, axios, api.get/post)
    external_calls: List[str] = []
    if re.search(r'\bfetch\(', content):
        external_calls.append("fetch")
    if re.search(r'\baxios\b', content):
        external_calls.append("axios")
    if re.search(r'\bapi\.(get|post|put|delete|blob)\b', content):
        external_calls.append("api_client")

    # Extract Express/Node routes: app.get('/api/...'), router.post('/api/...')
    route_matches = re.finditer(
        r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*(?:async\s*)?(?:function\s*([A-Za-z0-9_]*)|([A-Za-z0-9_]+)|\()',
        content,
    )
    for m in route_matches:
        method = m.group(1).upper()
        route_path = m.group(2)
        handler = m.group(3) or m.group(4) or "anonymous_handler"
        parts = [p for p in route_path.strip("/").split("/") if p and p != "api" and not p.startswith(":")]
        resource = parts[0] if parts else "root"
        apis.append({
            "method": method,
            "path": route_path,
            "handler": handler,
            "file": rel_path,
            "resource": resource,
        })

    # Detect interface / type models
    for iface in interfaces:
        models.append({
            "name": iface,
            "file": rel_path,
            "fields": [],
            "foreign_keys": [],
            "type": "interface",
        })

    # Detect API calls made in frontend (calls to endpoints)
    api_call_paths = re.findall(r'(?:api\.(?:get|post|put|delete|blob)|fetch)\s*\(\s*[`\'"](/api/[^\'`"?\s]+)', content)

    return {
        "id": rel_path.replace("/", "_").replace(".", "_"),
        "name": base_name,
        "path": rel_path,
        "type": comp_type,
        "language": "typescript" if rel_path.endswith((".ts", ".tsx")) else "javascript",
        "classes": list(dict.fromkeys(classes)),
        "functions": list(dict.fromkeys(functions)),
        "imports": list(dict.fromkeys(imports)),
        "external_calls": external_calls,
        "api_calls": api_call_paths,
    }


def _extract_relationships(
    components: List[Dict[str, Any]],
    file_map: Dict[str, Dict[str, Any]],
    apis: List[Dict[str, Any]],
    models: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Map dependencies and semantic relationships between detected components."""
    relationships: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for comp in components:
        source_name = comp["name"]

        # 1. Import relationships
        for imp in comp.get("imports", []):
            target_name = None
            if imp.startswith("."):
                target_name = Path(imp).name.split(".")[0]
            else:
                parts = imp.split("/")
                target_name = parts[-1].split(".")[0]

            matched_target = None
            for other in components:
                if other["name"] == target_name and other["name"] != source_name:
                    matched_target = other
                    break

            if matched_target:
                rel_id = f"{source_name}->{matched_target['name']}:imports"
                if rel_id not in seen:
                    seen.add(rel_id)
                    rel_type = "imports"
                    label = "imports"
                    if comp["type"] == "controller" and matched_target["type"] == "service":
                        rel_type = "calls_service"
                        label = "delegates to"
                    elif comp["type"] in {"controller", "service"} and matched_target["type"] == "model":
                        rel_type = "uses_model"
                        label = "queries"
                    elif comp["type"] == "ui_component" and matched_target["type"] in {"store", "service"}:
                        rel_type = "uses_state"
                        label = "connects to"

                    relationships.append({
                        "source": source_name,
                        "source_type": comp["type"],
                        "target": matched_target["name"],
                        "target_type": matched_target["type"],
                        "type": rel_type,
                        "label": label,
                    })

        # 2. Frontend calling API endpoints
        for endpoint_path in comp.get("api_calls", []):
            # Find matching backend API
            matched_api = None
            for api in apis:
                if api["path"] in endpoint_path or endpoint_path in api["path"]:
                    matched_api = api
                    break

            if matched_api:
                target_controller = Path(matched_api["file"]).stem
                rel_id = f"{source_name}->{target_controller}:api_call"
                if rel_id not in seen:
                    seen.add(rel_id)
                    relationships.append({
                        "source": source_name,
                        "source_type": comp["type"],
                        "target": target_controller,
                        "target_type": "controller",
                        "type": "calls_api",
                        "label": f"calls {matched_api['method']} {matched_api['path']}",
                    })

    # 3. Model Foreign Key relationships
    for mod in models:
        for fk in mod.get("foreign_keys", []):
            target_model = fk["target"]
            rel_id = f"{mod['name']}->{target_model}:foreign_key"
            if rel_id not in seen:
                seen.add(rel_id)
                relationships.append({
                    "source": mod["name"],
                    "source_type": "model",
                    "target": target_model,
                    "target_type": "model",
                    "type": "foreign_key",
                    "label": f"foreign key ({fk['field']})",
                })

    # 4. API to Model flow relationships
    for api in apis:
        controller_name = Path(api["file"]).stem
        res = api.get("resource", "")
        for mod in models:
            if mod["name"].lower() in res.lower() or res.lower() in mod["name"].lower():
                rel_id = f"{controller_name}->{mod['name']}:persists"
                if rel_id not in seen:
                    seen.add(rel_id)
                    relationships.append({
                        "source": controller_name,
                        "source_type": "controller",
                        "target": mod["name"],
                        "target_type": "model",
                        "type": "database_access",
                        "label": f"{api['method']} {api['path']}",
                    })

    return relationships
