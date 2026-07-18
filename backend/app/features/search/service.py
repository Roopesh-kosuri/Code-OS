import re
from pathlib import Path

from backend.app.core.paths import IGNORED_DIRS, normalize_path

TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".html", ".css", ".scss", ".txt", ".yml", ".yaml"}
SYMBOL_PATTERN = re.compile(r"^\s*(class|def|function|const|let|var|export\s+function|export\s+class)\s+([A-Za-z_$][\w$]*)")


def iter_project_files(workspace: str) -> list[Path]:
    root = normalize_path(workspace)
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def search_files(workspace: str, query: str, limit: int = 50) -> list[Path]:
    lowered = query.lower()
    return [path for path in iter_project_files(workspace) if lowered in path.name.lower()][:limit]


def _pattern(query: str, regex: bool, case_sensitive: bool, whole_word: bool) -> re.Pattern[str]:
    source = query if regex else re.escape(query)
    if whole_word:
        source = rf"\b{source}\b"
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(source, flags)


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
    for path in iter_project_files(workspace):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            for index, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                match = matcher.search(line)
                if match:
                    matches.append((path, index, match.start() + 1, line.strip()[:240]))
                    if len(matches) >= limit:
                        return matches
        except (OSError, re.error):
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
) -> list[tuple[Path, int]]:
    results: list[tuple[Path, int]] = []
    if not query:
        return results
    matcher = _pattern(query, regex, case_sensitive, whole_word)
    for path in iter_project_files(workspace):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        original = path.read_text(encoding="utf-8", errors="ignore")
        updated, count = matcher.subn(replacement, original)
        if count:
            results.append((path, count))
            if apply:
                path.write_text(updated, encoding="utf-8")
    return results


def search_symbols(workspace: str, query: str, limit: int = 100) -> list[tuple[Path, int, str, str]]:
    results: list[tuple[Path, int, str, str]] = []
    lowered = query.lower()
    for path in iter_project_files(workspace):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        for index, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            match = SYMBOL_PATTERN.match(line)
            if match and lowered in match.group(2).lower():
                results.append((path, index, match.group(2), match.group(1)))
                if len(results) >= limit:
                    return results
    return results
