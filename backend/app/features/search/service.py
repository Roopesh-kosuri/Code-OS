import re
import time
from pathlib import Path
from fastapi import HTTPException

from ...core.paths import IGNORED_DIRS, normalize_path

TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".html", ".css",
    ".scss", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bash",
    ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".xml", ".sql", ".env"
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".pdf",
    ".zip", ".tar", ".gz", ".7z", ".exe", ".dll", ".so", ".dylib", ".bin",
    ".pyc", ".wasm", ".iso", ".obj", ".o", ".a", ".lib"
}

IGNORED_SEARCH_DIRS = set(IGNORED_DIRS) | {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".vscode", ".idea", "coverage", ".cache", "out", "target"
}

MAX_SCAN_FILES = 500
REGEX_TIMEOUT_SECONDS = 2.0

# Catastrophic backtracking regex detector (nested quantifiers like (a+)+ or (a*)* or (a|b)+)
BACKTRACKING_PATTERN = re.compile(
    r"\([^\)]*[\+\*]\)[\+\*]|\([^\)]*\{[0-9,]+\}\)[\+\*]|\([^\)]*\|[^\)]*\)[\+\*]"
)

SYMBOL_PATTERN = re.compile(
    r"^\s*(class|def|function|const|let|var|export\s+function|export\s+class)\s+([A-Za-z_$][\w$]*)"
)


def is_binary_file(path: Path) -> bool:
    """Check whether a file is binary by extension or NULL byte presence."""
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\0" in chunk
    except Exception:
        return True


def iter_project_files(workspace: str, limit: int = MAX_SCAN_FILES) -> list[Path]:
    root = normalize_path(workspace)
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in IGNORED_SEARCH_DIRS for part in path.parts):
            continue
        if path.is_file() and not is_binary_file(path):
            files.append(path)
            if len(files) >= limit:
                break
    return files


def search_files(workspace: str, query: str, limit: int = 50) -> list[Path]:
    lowered = query.lower()
    return [path for path in iter_project_files(workspace) if lowered in path.name.lower()][:limit]


def _pattern(query: str, regex: bool, case_sensitive: bool, whole_word: bool) -> re.Pattern[str]:
    if regex:
        # Check for catastrophic backtracking nested quantifiers
        if BACKTRACKING_PATTERN.search(query):
            raise HTTPException(
                status_code=400,
                detail="Regex rejected: contains nested quantifiers that can cause catastrophic backtracking (ReDoS)"
            )
        source = query
    else:
        source = re.escape(query)

    if whole_word:
        source = rf"\b{source}\b"

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(source, flags)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"Invalid regular expression: {e}")

    # Pre-flight probe on synthetic repetitive input to catch backtracking that evaded static check
    if regex:
        t0 = time.monotonic()
        try:
            compiled.search("a" * 30 + "!")
        except Exception:
            pass
        if (time.monotonic() - t0) > 0.5:
            raise HTTPException(
                status_code=400,
                detail="Regex execution timed out (potential catastrophic backtracking)"
            )

    return compiled


def search_text(
    workspace: str,
    query: str,
    limit: int = 100,
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
) -> list[tuple[Path, int, int, str]]:
    matches: list[tuple[Path, int, int, str]] = []
    if not query:
        return matches

    matcher = _pattern(query, regex, case_sensitive, whole_word)
    start_time = time.monotonic()

    for path in iter_project_files(workspace):
        if time.monotonic() - start_time > REGEX_TIMEOUT_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"Regex execution timed out (> {REGEX_TIMEOUT_SECONDS}s)"
            )
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            for index, line in enumerate(content.splitlines(), start=1):
                if time.monotonic() - start_time > REGEX_TIMEOUT_SECONDS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Regex execution timed out (> {REGEX_TIMEOUT_SECONDS}s)"
                    )
                # Cap line length to 5000 chars to avoid pathological strings
                truncated_line = line[:5000]
                match = matcher.search(truncated_line)
                if match:
                    matches.append((path, index, match.start() + 1, line.strip()[:240]))
                    if len(matches) >= limit:
                        return matches
        except OSError:
            continue
    return matches


def replace_text(
    workspace: str,
    query: str,
    replacement: str,
    apply: bool,
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
    files: list[str] | None = None,
) -> list[tuple[Path, int]]:
    results: list[tuple[Path, int]] = []
    if not query:
        return results

    matcher = _pattern(query, regex, case_sensitive, whole_word)
    start_time = time.monotonic()

    target_files = iter_project_files(workspace)
    if files:
        # Normalize filter file paths
        normalized_targets = {str(normalize_path(f)).lower().replace("\\", "/") for f in files}
        target_files = [
            f for f in target_files
            if str(f).lower().replace("\\", "/") in normalized_targets
        ]

    for path in target_files:
        if time.monotonic() - start_time > REGEX_TIMEOUT_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"Regex execution timed out (> {REGEX_TIMEOUT_SECONDS}s)"
            )
        try:
            original = path.read_text(encoding="utf-8", errors="ignore")
            updated, count = matcher.subn(replacement, original)
            if count > 0:
                results.append((path, count))
                if apply:
                    path.write_text(updated, encoding="utf-8")
        except OSError:
            continue

    return results


def search_symbols(workspace: str, query: str, limit: int = 100) -> list[tuple[Path, int, str, str]]:
    results: list[tuple[Path, int, str, str]] = []
    lowered = query.lower()
    for path in iter_project_files(workspace):
        try:
            for index, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                match = SYMBOL_PATTERN.match(line)
                if match and lowered in match.group(2).lower():
                    results.append((path, index, match.group(2), match.group(1)))
                    if len(results) >= limit:
                        return results
        except OSError:
            continue
    return results
