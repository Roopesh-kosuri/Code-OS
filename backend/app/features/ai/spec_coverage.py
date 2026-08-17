"""Spec Coverage — extracts key requirements from user requests and checks
them against what was actually built in the DAG run.

Used as a final validation gate before marking a job as completed.
"""
import re
import logging

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "over", "after",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "must", "shall", "can", "need", "dare", "ought",
    "used", "using", "use", "build", "create", "make", "implement",
    "add", "write", "that", "this", "it", "i", "you", "we", "they",
    "my", "your", "our", "their", "its", "me", "him", "her", "us",
    "them", "what", "which", "who", "whom", "whose", "when", "where",
    "how", "not", "no", "nor", "as", "if", "then", "than", "too",
    "very", "just", "also", "so", "such", "each", "every", "all",
    "both", "few", "more", "most", "other", "some", "any", "many",
    "much", "own", "same", "able", "across", "back", "because",
    "before", "between", "come", "get", "give", "go", "keep",
    "let", "put", "say", "still", "take", "tell", "thing", "try",
    "work", "call", "first", "last", "long", "great", "little", "right",
    "old", "new", "good", "bad", "high", "low", "end", "set", "run",
    "only", "while", "here", "there", "out", "off", "well", "part",
    "even", "want", "full", "please", "app", "application", "project",
    "code", "file", "files", "system", "function", "functions", "module",
})


def extract_requirements(user_request: str) -> list[str]:
    """Extract key requirement phrases/nouns from a user request."""
    requirements: list[str] = []

    # 1. Extract quoted terms (explicit requirements)
    for m in re.finditer(r"""["'](.+?)["']""", user_request):
        term = m.group(1).strip()
        if 2 < len(term) < 60:
            requirements.append(term)

    # 2. Extract multi-word technical phrases (bigrams)
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", user_request)
    words_lower = [w.lower() for w in words]
    for i in range(len(words_lower) - 1):
        bigram = f"{words_lower[i]} {words_lower[i+1]}"
        if words_lower[i] not in _STOPWORDS and words_lower[i+1] not in _STOPWORDS:
            if len(bigram) > 5:
                requirements.append(bigram)

    # 3. Extract single technical keywords
    technical_patterns = [
        r"\b(api|cli|gui|ui|rag|llm|crud|rest|graphql|websocket|oauth|jwt)\b",
        r"\b(pipeline|endpoint|middleware|decorator|handler|controller|service)\b",
        r"\b(database|schema|model|migration|query|index|table)\b",
        r"\b(embeddings?|vectors?|retriever|similarity|search|cosine)\b",
        r"\b(authentication|authorization|permission|role|token|session)\b",
        r"\b(test(?:ing|s)?|benchmark|profil(?:e|ing)|logging|monitoring)\b",
        r"\b(cache|queue|worker|scheduler|cron|webhook|notification)\b",
    ]
    for pattern in technical_patterns:
        for m in re.finditer(pattern, user_request, re.IGNORECASE):
            term = m.group(1).lower()
            if term not in _STOPWORDS:
                requirements.append(term)

    # Deduplicate
    seen = set()
    unique = []
    for r in requirements:
        key = r.lower().strip()
        if key not in seen and len(key) > 2:
            seen.add(key)
            unique.append(r)
    return unique[:30]


def check_coverage(requirements: list[str],
                   manifest_entries: dict[str, dict],
                   completed_tasks: list[dict]) -> dict:
    """Check which requirements from the original spec are covered."""
    if not requirements:
        return {"covered": [], "uncovered": [], "coverage_ratio": 1.0}

    corpus_parts = []
    for path, entry in manifest_entries.items():
        corpus_parts.append(path.lower())
        corpus_parts.append(entry.get("purpose", "").lower())
        corpus_parts.extend(e.lower() for e in entry.get("exports", []))
    for task in completed_tasks:
        corpus_parts.append(task.get("title", "").lower())
        corpus_parts.append(task.get("reasoning_summary", "").lower())
    corpus = " ".join(corpus_parts)

    covered = []
    uncovered = []
    for req in requirements:
        req_lower = req.lower()
        if len(req_lower.split()) == 1:
            if re.search(r"\b" + re.escape(req_lower) + r"\b", corpus):
                covered.append((req, _find_evidence(req_lower, manifest_entries, completed_tasks)))
            else:
                uncovered.append(req)
        else:
            if req_lower in corpus:
                covered.append((req, _find_evidence(req_lower, manifest_entries, completed_tasks)))
            else:
                words = req_lower.split()
                if all(w in corpus for w in words):
                    covered.append((req, _find_evidence(req_lower, manifest_entries, completed_tasks)))
                else:
                    uncovered.append(req)

    ratio = len(covered) / len(requirements) if requirements else 1.0
    return {"covered": covered, "uncovered": uncovered, "coverage_ratio": round(ratio, 2)}


def _find_evidence(req: str, manifest_entries: dict, completed_tasks: list) -> str:
    for path, entry in manifest_entries.items():
        searchable = f"{path} {entry.get('purpose', '')} {' '.join(entry.get('exports', []))}".lower()
        if req in searchable:
            return f"File: {path}"
    for task in completed_tasks:
        searchable = f"{task.get('title', '')} {task.get('reasoning_summary', '')}".lower()
        if req in searchable:
            return f"Task: {task.get('title', '')}"
    return "matched in corpus"


def format_coverage_report(coverage: dict) -> str:
    lines = []
    ratio = coverage.get("coverage_ratio", 0)
    if ratio >= 1.0:
        lines.append(f"Spec coverage: {ratio:.0%} -- all extracted requirements appear addressed.")
    else:
        lines.append(f"Spec coverage: {ratio:.0%} -- some requirements may not be addressed:")
        for req in coverage.get("uncovered", []):
            lines.append(f"  [MISSING] Not found in output: '{req}'")
    if coverage.get("covered"):
        lines.append(f"  [OK] Covered ({len(coverage['covered'])} requirements matched)")
    return "\n".join(lines)
