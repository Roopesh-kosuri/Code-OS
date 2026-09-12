"""Language-aware verifier selection for CODE OS.

Selects the optimal verification tool after edit_file on file X:
1. If test framework exists for X's language/project -> run targeted tests
2. Else if diagnostics available -> get_diagnostics(X)
3. Else if compiled language -> approval-gated syntax/compile check (e.g. g++ -fsyntax-only for C/C++)
4. NEVER pytest on non-Python or test-less projects
5. Log the chosen verifier in the activity log
"""

import json
import logging
from pathlib import Path
from typing import Any

from .activity_logger import _append_activity_log

logger = logging.getLogger(__name__)

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
}

COMPILED_LANGUAGES = {"cpp", "c", "rust", "go", "java", "csharp", "swift", "kotlin"}


def detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    suffix = Path(file_path).suffix.lower()
    return LANGUAGE_EXTENSIONS.get(suffix, "plaintext")


def _find_matching_test_file(ws_path: Path, file_path: str, lang: str) -> Path | None:
    """Check if a specific test file exists for the given file."""
    stem = Path(file_path).stem
    if lang == "python":
        candidates = [
            ws_path / "tests" / f"test_{stem}.py",
            ws_path / f"test_{stem}.py",
            ws_path / f"{stem}_test.py",
            ws_path / "tests" / f"{stem}_test.py",
        ]
    elif lang in ("typescript", "javascript"):
        candidates = [
            ws_path / f"{stem}.test.ts",
            ws_path / f"{stem}.test.tsx",
            ws_path / f"{stem}.spec.ts",
            ws_path / f"{stem}.test.js",
            ws_path / "tests" / f"{stem}.test.ts",
            ws_path / "src" / "__tests__" / f"{stem}.test.tsx",
            ws_path / "src" / "__tests__" / f"{stem}.test.ts",
        ]
    elif lang == "go":
        candidates = [ws_path / f"{stem}_test.go"]
    elif lang == "rust":
        candidates = [ws_path / "tests" / f"{stem}_test.rs", ws_path / "tests" / f"{stem}.rs"]
    else:
        candidates = []

    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _has_language_test_framework(ws_path: Path, lang: str, file_path: str) -> tuple[bool, str | None, str | None]:
    """Check whether a test framework exists for this language/project.
    
    Returns (has_framework, tool, command).
    """
    if lang == "python":
        matching = _find_matching_test_file(ws_path, file_path, lang)
        if matching:
            try:
                rel = str(matching.relative_to(ws_path)).replace("\\", "/")
            except ValueError:
                rel = str(matching)
            return True, "run_test", f"pytest {rel}"

        # General python test framework indicators
        has_tests_dir = (ws_path / "tests").is_dir() or (ws_path / "test").is_dir()
        has_pytest_config = (
            (ws_path / "pytest.ini").is_file()
            or (ws_path / "conftest.py").is_file()
            or (ws_path / "setup.cfg").is_file()
        )
        if has_tests_dir or has_pytest_config:
            # Check if any .py test files actually exist
            py_tests = list(ws_path.glob("**/test_*.py")) or list(ws_path.glob("**/*_test.py"))
            if py_tests:
                return True, "run_test", "pytest"

        return False, None, None

    if lang in ("typescript", "javascript"):
        matching = _find_matching_test_file(ws_path, file_path, lang)
        pkg_json = ws_path / "package.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    if matching:
                        try:
                            rel = str(matching.relative_to(ws_path)).replace("\\", "/")
                        except ValueError:
                            rel = str(matching)
                        return True, "run_test", f"npm test -- {rel}"
                    return True, "run_test", "npm test"
            except Exception:
                pass
        return False, None, None

    if lang == "rust":
        if (ws_path / "Cargo.toml").is_file():
            return True, "run_test", "cargo test"
        return False, None, None

    if lang == "go":
        matching = _find_matching_test_file(ws_path, file_path, lang)
        if matching or (ws_path / "go.mod").is_file():
            return True, "run_test", "go test ./..."
        return False, None, None

    if lang in ("cpp", "c"):
        # Only use tests if ctest or explicit CMake test target or Makefile exists
        cmake = ws_path / "CMakeLists.txt"
        if cmake.is_file():
            try:
                content = cmake.read_text(encoding="utf-8", errors="replace").lower()
                if "enable_testing()" in content or "add_test(" in content:
                    return True, "run_test", "ctest"
            except Exception:
                pass
        makefile = ws_path / "Makefile"
        if makefile.is_file():
            try:
                content = makefile.read_text(encoding="utf-8", errors="replace").lower()
                if "test:" in content or "check:" in content:
                    return True, "run_test", "make test"
            except Exception:
                pass
        return False, None, None

    return False, None, None


def _is_diagnostics_available(workspace: str, file_path: str, lang: str) -> bool:
    """Check if DiagnosticsService can analyze file X."""
    try:
        from .diagnostics_service import DiagnosticsService
        return DiagnosticsService.is_supported_language(file_path)
    except Exception:
        # If diagnostics service is available for the language or general files
        return lang in ("python", "typescript", "javascript", "cpp", "c", "rust", "go")


def _get_compile_check_command(file_path: str, lang: str) -> str | None:
    """Return approval-gated syntax/compile check command for compiled languages."""
    clean_p = file_path.replace("\\", "/")
    if lang == "cpp":
        return f"g++ -fsyntax-only {clean_p}"
    if lang == "c":
        return f"gcc -fsyntax-only {clean_p}"
    if lang == "rust":
        return f"rustc --emit=metadata {clean_p}"
    if lang == "go":
        return f"go vet {clean_p}"
    return None


def select_verifier(workspace: str, file_path: str, log_choice: bool = True) -> dict[str, Any]:
    """Select the optimal verifier for file X according to language & project rules.
    
    Hierarchy:
    1. test framework exists for X's language/project -> run targeted tests
    2. else diagnostics available -> get_diagnostics(X)
    3. else compiled language -> approval-gated syntax/compile check (e.g. g++ -fsyntax-only for C/C++)
    4. NEVER pytest on non-Python or test-less projects
    """
    ws_path = Path(workspace) if workspace else Path(".")
    lang = detect_language(file_path)

    # 1. Test framework check
    has_tests, test_tool, test_cmd = _has_language_test_framework(ws_path, lang, file_path)
    if has_tests and test_tool:
        result = {
            "verifier": "tests",
            "tool": test_tool,
            "command": test_cmd,
            "language": lang,
            "file": file_path,
            "reason": f"Active {lang} test framework detected; running targeted tests",
        }
    # 2. Diagnostics check
    elif _is_diagnostics_available(workspace, file_path, lang):
        result = {
            "verifier": "diagnostics",
            "tool": "get_diagnostics",
            "command": None,
            "language": lang,
            "file": file_path,
            "reason": f"Diagnostics available for {lang} ({file_path}); checking compiler/syntax diagnostics",
        }
    # 3. Compiled language check
    elif lang in COMPILED_LANGUAGES:
        compile_cmd = _get_compile_check_command(file_path, lang)
        if compile_cmd:
            result = {
                "verifier": "compile_check",
                "tool": "run_command",
                "command": compile_cmd,
                "language": lang,
                "file": file_path,
                "reason": f"Compiled language {lang}; running syntax/compile check ({compile_cmd})",
            }
        else:
            result = {
                "verifier": "diagnostics",
                "tool": "get_diagnostics",
                "command": None,
                "language": lang,
                "file": file_path,
                "reason": f"Compiled language {lang}; falling back to diagnostics",
            }
    # 4. Fallback for non-compiled / test-less
    else:
        result = {
            "verifier": "diagnostics",
            "tool": "get_diagnostics",
            "command": None,
            "language": lang,
            "file": file_path,
            "reason": f"No test suite found for {lang}; using get_diagnostics",
        }

    # Strict assertion: Never return pytest for non-python files
    if lang != "python" and result.get("command") and "pytest" in str(result.get("command")):
        logger.error("VIOLATION PREVENTED: Attempted to assign pytest to %s file: %s", lang, file_path)
        result = {
            "verifier": "compile_check" if lang in COMPILED_LANGUAGES else "diagnostics",
            "tool": "run_command" if lang in COMPILED_LANGUAGES else "get_diagnostics",
            "command": _get_compile_check_command(file_path, lang),
            "language": lang,
            "file": file_path,
            "reason": f"Overrode verifier to avoid pytest on {lang}",
        }

    # Log selection in activity log
    if log_choice and workspace:
        try:
            _append_activity_log(workspace, {
                "action_type": "verifier_selection",
                "file": file_path,
                "language": lang,
                "verifier": result["verifier"],
                "tool": result["tool"],
                "command": result.get("command"),
                "reason": result["reason"],
                "details": f"Selected verifier '{result['verifier']}' ({result['tool']}) for {file_path}",
            })
        except Exception as exc:
            logger.warning("verifier_selector: failed to log activity: %s", exc)

    return result
