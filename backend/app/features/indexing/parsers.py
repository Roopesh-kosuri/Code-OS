import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedSymbol:
    name: str
    kind: str
    line: int
    column: int = 1
    signature: str = ""
    parent: str | None = None


@dataclass
class ParsedFile:
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s]+))")
PY_SYMBOL_RE = re.compile(r"^\s*(class|def|async\s+def)\s+([A-Za-z_]\w*)\s*(.*)")
PY_ASSIGN_RE = re.compile(r"^([A-Za-z_]\w*)\s*=")

C_INCLUDE_RE = re.compile(r"^\s*#\s*include\s+[<\"]([^>\"]+)[>\"]")
C_TYPE_RE = re.compile(r"^\s*(?:typedef\s+)?(?:struct|class|enum)\s+([A-Za-z_]\w*)")
C_FUNC_RE = re.compile(r"^\s*(?:[A-Za-z_][\w:<>,*&\s]+\s+)+([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:\{|$)")

JAVA_IMPORT_RE = re.compile(r"^\s*import\s+([\w.*]+)\s*;")
JAVA_TYPE_RE = re.compile(r"^\s*(?:public|private|protected|abstract|final|\s)*\s*(class|interface|enum)\s+([A-Za-z_]\w*)")
JAVA_METHOD_RE = re.compile(r"^\s*(?:public|private|protected|static|final|synchronized|abstract|\s)+[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\(")

JS_IMPORT_RE = re.compile(r"^\s*(?:import\s+.*?\s+from\s+[\"']([^\"']+)[\"']|import\s+[\"']([^\"']+)[\"']|const\s+.*?=\s+require\([\"']([^\"']+)[\"']\))")
JS_SYMBOL_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)")
JS_CONST_RE = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)?\s*=>?")


def parse_source(path: Path, language: str, content: str) -> ParsedFile:
    if language == "python":
        return _parse_python(content)
    if language in {"c", "cpp"}:
        return _parse_c_family(content)
    if language == "java":
        return _parse_java(content)
    if language in {"javascript", "typescript"}:
        return _parse_js_ts(content)
    return ParsedFile()


def _parse_python(content: str) -> ParsedFile:
    parsed = ParsedFile()
    class_stack: list[tuple[int, str]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        indent = len(line) - len(line.lstrip(" "))
        while class_stack and indent <= class_stack[-1][0]:
            class_stack.pop()
        import_match = PY_IMPORT_RE.match(line)
        if import_match:
            if import_match.group(1):
                parsed.imports.append(import_match.group(1))
            elif import_match.group(2):
                parsed.imports.extend(part.strip().split(" as ")[0] for part in import_match.group(2).split(",") if part.strip())
        symbol_match = PY_SYMBOL_RE.match(line)
        if symbol_match:
            raw_kind = symbol_match.group(1)
            kind = "class" if raw_kind == "class" else "function"
            name = symbol_match.group(2)
            parent = class_stack[-1][1] if class_stack and kind == "function" else None
            parsed.symbols.append(ParsedSymbol(name=name, kind=kind, line=line_number, column=line.find(name) + 1, signature=line.strip(), parent=parent))
            if kind == "class":
                class_stack.append((indent, name))
            continue
        assign_match = PY_ASSIGN_RE.match(line.strip())
        if assign_match and not class_stack:
            parsed.symbols.append(ParsedSymbol(name=assign_match.group(1), kind="variable", line=line_number, column=line.find(assign_match.group(1)) + 1, signature=line.strip()))
    return parsed


def _parse_c_family(content: str) -> ParsedFile:
    parsed = ParsedFile()
    for line_number, line in enumerate(content.splitlines(), start=1):
        include_match = C_INCLUDE_RE.match(line)
        if include_match:
            parsed.imports.append(include_match.group(1))
        type_match = C_TYPE_RE.match(line)
        if type_match:
            parsed.symbols.append(ParsedSymbol(name=type_match.group(1), kind="type", line=line_number, column=line.find(type_match.group(1)) + 1, signature=line.strip()))
            continue
        func_match = C_FUNC_RE.match(line)
        if func_match and func_match.group(1) not in {"if", "for", "while", "switch"}:
            parsed.symbols.append(ParsedSymbol(name=func_match.group(1), kind="function", line=line_number, column=line.find(func_match.group(1)) + 1, signature=line.strip()))
    return parsed


def _parse_java(content: str) -> ParsedFile:
    parsed = ParsedFile()
    current_type: str | None = None
    for line_number, line in enumerate(content.splitlines(), start=1):
        import_match = JAVA_IMPORT_RE.match(line)
        if import_match:
            parsed.imports.append(import_match.group(1))
        type_match = JAVA_TYPE_RE.match(line)
        if type_match:
            current_type = type_match.group(2)
            parsed.symbols.append(ParsedSymbol(name=current_type, kind=type_match.group(1), line=line_number, column=line.find(current_type) + 1, signature=line.strip()))
            continue
        method_match = JAVA_METHOD_RE.match(line)
        if method_match:
            parsed.symbols.append(ParsedSymbol(name=method_match.group(1), kind="method", line=line_number, column=line.find(method_match.group(1)) + 1, signature=line.strip(), parent=current_type))
    return parsed


def _parse_js_ts(content: str) -> ParsedFile:
    parsed = ParsedFile()
    for line_number, line in enumerate(content.splitlines(), start=1):
        import_match = JS_IMPORT_RE.match(line)
        if import_match:
            parsed.imports.extend(group for group in import_match.groups() if group)
        symbol_match = JS_SYMBOL_RE.match(line)
        if symbol_match:
            kind = "class" if "class" in line else "function"
            parsed.symbols.append(ParsedSymbol(name=symbol_match.group(1), kind=kind, line=line_number, column=line.find(symbol_match.group(1)) + 1, signature=line.strip()))
            continue
        const_match = JS_CONST_RE.match(line)
        if const_match:
            parsed.symbols.append(ParsedSymbol(name=const_match.group(1), kind="function", line=line_number, column=line.find(const_match.group(1)) + 1, signature=line.strip()))
    return parsed


def parse_package_json(path: Path) -> list[tuple[str, str | None, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return []
    dependencies: list[tuple[str, str | None, str]] = []
    for source in ("dependencies", "devDependencies", "peerDependencies"):
        for name, version in payload.get(source, {}).items():
            dependencies.append((name, str(version), "package.json"))
    return dependencies


def parse_requirements(path: Path) -> list[tuple[str, str | None, str]]:
    dependencies: list[tuple[str, str | None, str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return dependencies
    for line in lines:
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#") or cleaned.startswith("-"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*(?:[=<>!~]=?\s*(.+))?", cleaned)
        if match:
            dependencies.append((match.group(1), match.group(2), path.name))
    return dependencies
