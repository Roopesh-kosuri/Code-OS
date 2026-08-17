"""Workspace Manifest — tracks files created/modified across a DAG job run.

The manifest is a lightweight registry that gives each DAG step visibility
into what prior steps have already produced, preventing the context-loss bug
where later steps blindly recreate files that earlier steps already built.
"""
import json
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ManifestEntry:
    """A single file tracked in the workspace manifest."""
    path: str
    purpose: str
    created_by_task_id: str
    created_by_task_title: str
    agent_role: str
    exports: list[str] = field(default_factory=list)
    is_new_file: bool = False


class WorkspaceManifest:
    """In-memory workspace manifest for a single job run.

    Persisted to the workspace_manifest JSON column on agent_jobs
    so it survives process restarts.
    """

    def __init__(self, entries: Optional[dict[str, dict]] = None) -> None:
        self._entries: dict[str, dict] = entries or {}

    def to_json(self) -> str:
        return json.dumps(self._entries, default=str)

    @classmethod
    def from_json(cls, raw: str) -> "WorkspaceManifest":
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        return cls(entries=data)

    def add_entry(self, entry: ManifestEntry) -> None:
        self._entries[entry.path] = asdict(entry)

    def add_file(self, path: str, purpose: str, task_id: str,
                 task_title: str, agent_role: str,
                 code_content: str = "", is_new_file: bool = False) -> None:
        exports = extract_exports(code_content) if code_content else []
        self.add_entry(ManifestEntry(
            path=path, purpose=purpose,
            created_by_task_id=task_id, created_by_task_title=task_title,
            agent_role=agent_role, exports=exports, is_new_file=is_new_file,
        ))

    def get_entries(self) -> dict[str, dict]:
        return dict(self._entries)

    def get_files_by_task(self, task_id: str) -> list[dict]:
        return [e for e in self._entries.values()
                if e.get("created_by_task_id") == task_id]

    def get_all_paths(self) -> list[str]:
        return list(self._entries.keys())

    def summary_text(self) -> str:
        """Human-readable manifest summary for injecting into agent prompts."""
        if not self._entries:
            return "(no files created by prior steps yet)"
        lines = ["=== WORKSPACE MANIFEST (files created/modified by prior steps in this run) ==="]
        for fpath, entry in self._entries.items():
            exports_str = ", ".join(entry.get("exports", [])[:10])
            exports_display = f" | exports: [{exports_str}]" if exports_str else ""
            lines.append(
                f"  - {fpath} -- {entry.get('purpose', '?')}{exports_display}"
                f" (by {entry.get('agent_role', '?')}: '{entry.get('created_by_task_title', '?')}')"
            )
        return "\n".join(lines)

    def check_duplicates(self, new_path: str, new_purpose: str,
                         new_exports: list[str]) -> list[dict]:
        """Check if a newly created file potentially duplicates an existing entry."""
        duplicates = []
        new_purpose_words = set(new_purpose.lower().split())
        new_export_set = set(e.lower() for e in new_exports)
        filler = {"the", "a", "an", "and", "or", "for", "to", "in",
                  "of", "with", "is", "on", "at", "by"}

        for existing_path, entry in self._entries.items():
            if existing_path == new_path:
                continue
            existing_purpose_words = set(entry.get("purpose", "").lower().split())
            purpose_overlap = (new_purpose_words & existing_purpose_words) - filler
            existing_exports = set(e.lower() for e in entry.get("exports", []))
            export_overlap = new_export_set & existing_exports
            purpose_ratio = len(purpose_overlap) / max(len(new_purpose_words), 1)
            if purpose_ratio >= 0.5 or len(export_overlap) >= 2:
                duplicates.append({
                    "existing_path": existing_path,
                    "existing_purpose": entry.get("purpose", ""),
                    "purpose_overlap_words": list(purpose_overlap),
                    "export_overlap": list(export_overlap),
                    "existing_task": entry.get("created_by_task_title", ""),
                })
        return duplicates


def extract_exports(code: str) -> list[str]:
    """Extract top-level function and class names from Python/JS/TS code."""
    exports: list[str] = []
    for m in re.finditer(r"^(?:async\s+)?def\s+(\w+)\s*\(", code, re.MULTILINE):
        name = m.group(1)
        if not name.startswith("_"):
            exports.append(name)
    for m in re.finditer(r"^class\s+(\w+)", code, re.MULTILINE):
        exports.append(m.group(1))
    for m in re.finditer(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|class)\s+(\w+)", code, re.MULTILINE):
        exports.append(m.group(1))
    for m in re.finditer(r"^(?:async\s+)?function\s+(\w+)\s*\(", code, re.MULTILINE):
        name = m.group(1)
        if name not in exports:
            exports.append(name)
    for m in re.finditer(r"@(?:app|router)\.\w+\(['\"]([^'\"]+)['\"]", code):
        exports.append(f"route:{m.group(1)}")
    return exports[:50]


def build_prior_steps_context(manifest: WorkspaceManifest,
                               completed_tasks: list[dict],
                               dependency_task_ids: list[str],
                               workspace: str) -> str:
    """Build a context string from prior completed steps for agent prompts."""
    sections: list[str] = []
    sections.append(manifest.summary_text())

    if completed_tasks:
        task_lines = ["\n=== COMPLETED PREDECESSOR TASKS ==="]
        for t in completed_tasks:
            task_lines.append(
                f"  [done] [{t.get('agent_role', '?')}] {t.get('title', '?')}"
                f"\n    Summary: {t.get('reasoning_summary', 'N/A')[:300]}"
            )
            for f in manifest.get_files_by_task(t["id"]):
                task_lines.append(f"    -> Created: {f.get('path', '?')}")
        sections.append("\n".join(task_lines))

    if dependency_task_ids:
        dep_file_entries = []
        for dep_id in dependency_task_ids:
            dep_file_entries.extend(manifest.get_files_by_task(dep_id))
        if dep_file_entries:
            file_sections = [
                "\n=== FULL FILE CONTENTS FROM DIRECT DEPENDENCY TASKS ===",
                "(These files were created by tasks that this task depends on. "
                "You MUST reference/reuse them rather than creating competing implementations.)\n",
            ]
            for entry in dep_file_entries[:8]:
                file_path = entry.get("path", "")
                try:
                    full_path = Path(workspace) / file_path
                    if full_path.is_file():
                        content = full_path.read_text(encoding="utf-8", errors="ignore")
                        if len(content) > 15000:
                            content = content[:15000] + "\n... (truncated)"
                        file_sections.append(
                            f"### FILE: {file_path}\n"
                            f"Purpose: {entry.get('purpose', '?')}\n"
                            f"Exports: {', '.join(entry.get('exports', []))}\n"
                            f"```\n{content}\n```\n"
                        )
                except Exception as exc:
                    logger.debug("Could not read dependency file %s: %s", file_path, exc)
            sections.append("\n".join(file_sections))

    return "\n\n".join(sections)
