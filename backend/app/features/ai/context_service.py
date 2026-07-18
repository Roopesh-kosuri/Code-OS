import logging
from pathlib import Path
from backend.app.core.paths import normalize_path
from backend.app.features.git.service import status as git_status
from backend.app.features.search.semantic_service import semantic_search
from backend.app.db.database import get_connection

logger = logging.getLogger(__name__)

async def gather_context(
    workspace: str,
    active_path: str | None = None,
    selection: str | None = None,
    open_tabs: list[str] | None = None,
    query: str | None = None,
    provider_config: dict | None = None
) -> dict:
    workspace_path = str(normalize_path(workspace))
    context = {
        "workspace": workspace_path,
        "active_file": None,
        "git_status": None,
        "dependencies": [],
        "open_tabs": [],
        "readme": None,
        "semantic_matches": []
    }
    
    # Scale budget based on model capability tier
    is_large = False
    if provider_config:
        raw_provider = provider_config.get("provider") or provider_config.get("preset", "auto")
        if raw_provider not in ("ollama", "local_reasoning", "local_fast"):
            is_large = True

    active_file_limit = 120000 if is_large else 30000
    readme_limit = 40000 if is_large else 10000
    semantic_limit = 15 if is_large else 5
    
    # 1. Gather active file content and selection
    if active_path:
        file_path = Path(active_path)
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                context["active_file"] = {
                    "path": str(file_path),
                    "name": file_path.name,
                    "content": content[:active_file_limit],  # Truncate if extremely large to save token window
                    "selection": selection
                }
            except OSError as exc:
                logger.warning("context.gather failed to read active file %s: %s", active_path, exc)

    # 2. Gather git status
    try:
        git_info = git_status(workspace_path)
        context["git_status"] = {
            "branch": git_info.get("branch"),
            "dirty": git_info.get("dirty"),
            "staged": git_info.get("staged"),
            "unstaged": git_info.get("unstaged")
        }
    except Exception:
        context["git_status"] = {"status": "No git repository found"}

    # 3. Gather open tabs metadata
    if open_tabs:
        for tab in open_tabs:
            tab_path = Path(tab)
            if tab_path.is_file():
                context["open_tabs"].append({
                    "path": str(tab_path),
                    "name": tab_path.name
                })

    # 4. Gather readme.md documentation
    readme_path = Path(workspace_path) / "README.md"
    if not readme_path.is_file():
        # Check lowercase
        readme_path = Path(workspace_path) / "readme.md"
    if readme_path.is_file():
        try:
            context["readme"] = readme_path.read_text(encoding="utf-8", errors="ignore")[:readme_limit]
        except OSError:
            pass

    # 5. Gather project dependencies from database
    db = await get_connection()
    try:
        dep_cursor = await db.execute("SELECT name, version FROM repo_dependencies WHERE workspace = ?", (workspace_path,))
        dep_rows = await dep_cursor.fetchall()
        context["dependencies"] = [{"name": r["name"], "version": r["version"]} for r in dep_rows]
    except Exception as exc:
        logger.warning("context.gather failed to query dependencies: %s", exc)
    finally:
        await db.close()

    # 6. Gather semantic search results if query is provided
    if query:
        try:
            matches = await semantic_search(workspace_path, query, limit=semantic_limit)
            context["semantic_matches"] = matches
        except Exception as exc:
            logger.warning("context.gather failed to run semantic search: %s", exc)

    return context
