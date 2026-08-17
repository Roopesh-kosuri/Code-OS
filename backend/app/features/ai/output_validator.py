"""Output Validator — stub detection and output quality gates.

Scans generated code proposals for stub patterns that indicate incomplete
implementation. Used as a hard guardrail in the DAG engine to prevent
silently passing stub functions as completed work.
"""
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class StubFinding:
    """A detected stub pattern in generated code."""
    file_path: str
    function_name: str
    line_number: int
    stub_type: str  # pass_only, not_implemented, todo_only, empty_body, suspiciously_short
    description: str


def validate_proposals(proposals: list) -> list[StubFinding]:
    """Scan a list of FileChange proposals for stub patterns."""
    findings: list[StubFinding] = []
    for proposal in proposals:
        file_path = getattr(proposal, "path", None) or proposal.get("path", "unknown")
        updated_code = getattr(proposal, "updated", None) or proposal.get("updated", "")
        if not updated_code or not updated_code.strip():
            continue
        if not _is_code_file(file_path):
            continue
        findings.extend(_scan_for_stubs(file_path, updated_code))
    return findings


def _is_code_file(path: str) -> bool:
    code_extensions = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
        ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp", ".swift", ".kt",
    }
    lower = path.lower()
    return any(lower.endswith(ext) for ext in code_extensions)


def _scan_for_stubs(file_path: str, code: str) -> list[StubFinding]:
    """Scan a single file's code for stub patterns."""
    findings: list[StubFinding] = []
    lines = code.split("\n")

    ALLOWED_PASS_FUNCTIONS = {
        "cli", "main", "app", "root", "command_group", "group", "cmd",
        "__init__", "__enter__", "__exit__", "__repr__", "__str__",
        "setup", "teardown", "setUp", "tearDown", "noop", "close",
        "render", "update", "run", "handle", "callback", "on_event", "execute"
    }

    # Python functions/methods
    py_func_re = re.compile(r"^([ \t]*)(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
    for match in py_func_re.finditer(code):
        indent = match.group(1)
        func_name = match.group(2)
        if func_name in ALLOWED_PASS_FUNCTIONS or file_path.endswith("__init__.py"):
            continue

        func_start = code[:match.start()].count("\n")
        
        # Skip decorated functions (e.g. @click.group(), @abstractmethod, @app.get())
        prev_line_idx = func_start - 1
        is_decorated = False
        while prev_line_idx >= 0:
            prev_line = lines[prev_line_idx].strip()
            if not prev_line or prev_line.startswith("#"):
                prev_line_idx -= 1
                continue
            if prev_line.startswith("@"):
                is_decorated = True
            break
        if is_decorated:
            continue
        body_lines = _extract_python_body(lines, func_start, indent)
        body_text = "\n".join(body_lines).strip()

        if not body_lines or not body_text:
            findings.append(StubFinding(
                file_path=file_path, function_name=func_name,
                line_number=func_start + 1, stub_type="empty_body",
                description=f"Function '{func_name}' has an empty body",
            ))
            continue

        body_stripped = _strip_docstring_and_comments(body_text)
        if body_stripped.strip() in ("pass", "pass\n", "..."):
            findings.append(StubFinding(
                file_path=file_path, function_name=func_name,
                line_number=func_start + 1, stub_type="pass_only",
                description=f"Function '{func_name}' body is only 'pass'",
            ))
            continue

        if re.match(r"^\s*raise\s+NotImplementedError", body_stripped.strip()):
            findings.append(StubFinding(
                file_path=file_path, function_name=func_name,
                line_number=func_start + 1, stub_type="not_implemented",
                description=f"Function '{func_name}' only raises NotImplementedError",
            ))
            continue

        non_comment = [l for l in body_lines if l.strip() and not l.strip().startswith("#")]
        if not non_comment:
            comment_text = " ".join(l.strip() for l in body_lines if l.strip().startswith("#"))
            if any(marker in comment_text.upper() for marker in ("TODO", "FIXME", "HACK", "PLACEHOLDER")):
                findings.append(StubFinding(
                    file_path=file_path, function_name=func_name,
                    line_number=func_start + 1, stub_type="todo_only",
                    description=f"Function '{func_name}' body contains only TODO/FIXME comments",
                ))
                continue

        docstring = _extract_docstring(body_lines)
        if docstring and len(docstring.split()) > 20:
            real_lines = [l for l in body_lines if l.strip()
                          and not l.strip().startswith("#")
                          and not l.strip().startswith('"""')
                          and not l.strip().startswith("'''")
                          and l.strip() not in ('"""', "'''")]
            if len(real_lines) < 2:
                findings.append(StubFinding(
                    file_path=file_path, function_name=func_name,
                    line_number=func_start + 1, stub_type="suspiciously_short",
                    description=(f"Function '{func_name}' has a detailed docstring "
                                 f"({len(docstring.split())} words) but only "
                                 f"{len(real_lines)} line(s) of code"),
                ))

    # JS/TS functions
    ALLOWED_JS_EMPTY = {"constructor", "noop", "setup", "teardown", "render", "update", "close"}
    js_func_re = re.compile(
        r"(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*="
        r"\s*(?:async\s+)?(?:\([^)]*\)|\w+)\s*=>)\s*\{",
        re.MULTILINE,
    )
    for match in js_func_re.finditer(code):
        func_name = match.group(1) or match.group(2)
        if func_name in ALLOWED_JS_EMPTY or file_path.endswith("index.ts") or file_path.endswith("index.js"):
            continue

        func_start = code[:match.start()].count("\n")
        brace_start = match.end() - 1
        body = _extract_braced_body(code, brace_start)
        if body is not None:
            bs = body.strip()
            if not bs:
                findings.append(StubFinding(
                    file_path=file_path, function_name=func_name,
                    line_number=func_start + 1, stub_type="empty_body",
                    description=f"Function '{func_name}' has an empty body",
                ))
            elif bs in ("throw new Error('Not implemented')",
                         'throw new Error("Not implemented")',
                         "throw new Error('TODO')", "// TODO", "// FIXME"):
                findings.append(StubFinding(
                    file_path=file_path, function_name=func_name,
                    line_number=func_start + 1, stub_type="not_implemented",
                    description=f"Function '{func_name}' only throws NotImplementedError or TODO",
                ))

    return findings


def _extract_python_body(lines: list[str], func_line: int, base_indent: str) -> list[str]:
    body_lines = []
    body_indent = None
    for i in range(func_line + 1, min(func_line + 100, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            body_lines.append(line)
            continue
        if body_indent is None:
            leading = len(line) - len(line.lstrip())
            if leading <= len(base_indent):
                break
            body_indent = leading
        current_leading = len(line) - len(line.lstrip())
        if current_leading <= len(base_indent) and stripped:
            break
        body_lines.append(line)
    return body_lines


def _strip_docstring_and_comments(body: str) -> str:
    body = re.sub(r'("""[\s\S]*?"""|' + r"'''[\s\S]*?''')", "", body)
    lines = [l for l in body.split("\n") if l.strip() and not l.strip().startswith("#")]
    return "\n".join(lines)


def _extract_docstring(body_lines: list[str]) -> str:
    in_docstring = False
    docstring_lines = []
    quote = '"""'
    for line in body_lines:
        stripped = line.strip()
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = True
                quote = stripped[:3]
                if stripped.endswith(quote) and len(stripped) > 3:
                    return stripped[3:-3]
                docstring_lines.append(stripped[3:])
            elif stripped:
                return ""
        else:
            if quote in stripped:
                docstring_lines.append(stripped.replace(quote, ""))
                return " ".join(docstring_lines)
            docstring_lines.append(stripped)
    return ""


def _extract_braced_body(code: str, brace_pos: int) -> str | None:
    if brace_pos >= len(code) or code[brace_pos] != "{":
        return None
    depth = 0
    for i in range(brace_pos, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[brace_pos + 1:i].strip()
    return None


def format_stub_findings(findings: list[StubFinding]) -> str:
    if not findings:
        return "No stub patterns detected."
    lines = [f"STUB DETECTION: Found {len(findings)} incomplete implementation(s):"]
    for f in findings:
        lines.append(f"  - {f.file_path}:{f.line_number} -- {f.function_name}: {f.description} [{f.stub_type}]")
    return "\n".join(lines)
