from fastapi import APIRouter, Query

from backend.app.features.search.schemas import FileSearchResult, ReplaceRequest, ReplaceResult, SymbolResult, TextMatch, SemanticSearchResult
from backend.app.features.search.service import replace_text, search_files, search_symbols, search_text
from backend.app.features.search.semantic_service import semantic_search
from backend.app.db.database import get_connection

router = APIRouter()


async def _ensure_trusted(workspace: str):
    from fastapi import HTTPException
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. File modifications are disabled.")


@router.get("/semantic", response_model=list[SemanticSearchResult])
async def semantic(workspace: str = Query(...), query: str = Query(""), limit: int = Query(50)) -> list[SemanticSearchResult]:
    results = await semantic_search(workspace, query, limit)
    return [SemanticSearchResult(**item) for item in results]


@router.get("/files", response_model=list[FileSearchResult])
async def files(workspace: str = Query(...), query: str = Query("")) -> list[FileSearchResult]:
    return [FileSearchResult(path=str(path), name=path.name) for path in search_files(workspace, query)]


@router.get("/text", response_model=list[TextMatch])
async def text(
    workspace: str = Query(...),
    query: str = Query(""),
    regex: bool = Query(False),
    case_sensitive: bool = Query(False),
    whole_word: bool = Query(False),
) -> list[TextMatch]:
    return [
        TextMatch(path=str(path), line=line, column=column, preview=preview)
        for path, line, column, preview in search_text(workspace, query, regex=regex, case_sensitive=case_sensitive, whole_word=whole_word)
    ]


@router.post("/replace", response_model=list[ReplaceResult])
async def replace(payload: ReplaceRequest) -> list[ReplaceResult]:
    if payload.apply:
        await _ensure_trusted(payload.workspace)
    return [
        ReplaceResult(path=str(path), replacements=count)
        for path, count in replace_text(
            payload.workspace,
            payload.query,
            payload.replacement,
            payload.apply,
            payload.regex,
            payload.case_sensitive,
            payload.whole_word,
        )
    ]


@router.get("/symbols", response_model=list[SymbolResult])
async def symbols(workspace: str = Query(...), query: str = Query("")) -> list[SymbolResult]:
    # Normalize workspace path to lowercase forward-slashes for comparison
    normalized_ws = workspace.lower().replace("\\", "/").rstrip("/")
    db = await get_connection()
    try:
        # The DB may store workspace as absolute path with any slash style.
        # Query all symbols whose workspace normalizes to the same value.
        cursor = await db.execute(
            "SELECT path, line, name, kind, workspace FROM repo_symbols WHERE name LIKE ? ORDER BY line LIMIT 200",
            (f"%{query}%",)
        )
        rows = await cursor.fetchall()
        # Filter by workspace on the Python side using normalized comparison
        matched = [
            row for row in rows
            if row["workspace"].lower().replace("\\", "/").rstrip("/") == normalized_ws
        ]
        if matched:
            return [SymbolResult(path=row["path"], line=row["line"], symbol=row["name"], kind=row["kind"]) for row in matched]
    except Exception:
        pass
    finally:
        await db.close()
    # Fallback to live scanning if index is empty or query fails
    return [SymbolResult(path=str(path), line=line, symbol=symbol, kind=kind) for path, line, symbol, kind in search_symbols(workspace, query)]
