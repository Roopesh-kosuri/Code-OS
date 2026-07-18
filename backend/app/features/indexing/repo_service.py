import json
from pathlib import Path
from backend.app.db.database import get_connection
from backend.app.core.paths import normalize_path

async def get_repo_summary(workspace: str) -> dict:
    workspace_path = str(normalize_path(workspace))
    db = await get_connection()
    try:
        # 1. Fetch index status/overview
        cursor = await db.execute("SELECT * FROM repo_index_status WHERE workspace = ?", (workspace_path,))
        status_row = await cursor.fetchone()
        if not status_row:
            return {"error": "Workspace not indexed yet"}
            
        language_summary = json.loads(status_row["language_summary"])
        frameworks = json.loads(status_row["frameworks"])
        entry_points = json.loads(status_row["entry_points"])
        
        # 2. Fetch dependencies
        dep_cursor = await db.execute("SELECT name, version, source FROM repo_dependencies WHERE workspace = ?", (workspace_path,))
        dep_rows = await dep_cursor.fetchall()
        dependencies = [{"name": r["name"], "version": r["version"], "source": r["source"]} for r in dep_rows]
        
        # 3. Fetch key symbols (e.g. Classes and functions to show structure)
        sym_cursor = await db.execute(
            "SELECT path, name, kind, language FROM repo_symbols WHERE workspace = ? AND kind IN ('class', 'interface', 'struct') LIMIT 100",
            (workspace_path,)
        )
        sym_rows = await sym_cursor.fetchall()
        key_symbols = [{"path": Path(r["path"]).name, "name": r["name"], "kind": r["kind"], "language": r["language"]} for r in sym_rows]
        
        # 4. Generate structured architecture summary text
        primary_lang = max(language_summary.items(), key=lambda x: x[1])[0] if language_summary else "unknown"
        summary_text = (
            f"This is a {status_row['project_type'].upper()} project primarily written in {primary_lang.capitalize()}.\n"
        )
        if frameworks:
            summary_text += f"It integrates the following frameworks/libraries: {', '.join(frameworks)}.\n"
        if entry_points:
            summary_text += f"Key entry points identified: {', '.join(entry_points)}.\n"
            
        summary_text += f"\nThe workspace contains {status_row['total_files']} files and is structured with "
        summary_text += f"{len(key_symbols)} major components/classes."

        return {
            "workspace": workspace_path,
            "project_type": status_row["project_type"],
            "total_files": status_row["total_files"],
            "languages": language_summary,
            "frameworks": frameworks,
            "entry_points": entry_points,
            "dependencies": dependencies,
            "architecture_summary": summary_text,
            "key_symbols": key_symbols
        }
    finally:
        await db.close()

async def get_repo_graph(workspace: str) -> dict:
    workspace_path = str(normalize_path(workspace))
    db = await get_connection()
    try:
        # Fetch all import edges where target_path is resolved (not None)
        cursor = await db.execute(
            "SELECT source_path, target_path, module FROM repo_import_edges WHERE workspace = ? AND target_path IS NOT NULL",
            (workspace_path,)
        )
        rows = await cursor.fetchall()
        
        nodes = set()
        edges = []
        
        for r in rows:
            src = Path(r["source_path"]).name
            tgt = Path(r["target_path"]).name
            nodes.add(src)
            nodes.add(tgt)
            edges.append({"source": src, "target": tgt, "module": r["module"]})
            
        return {
            "nodes": [{"id": name} for name in sorted(nodes)],
            "edges": edges
        }
    finally:
        await db.close()
