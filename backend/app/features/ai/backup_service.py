"""
backup_service.py
Automatic daily backups, rotation (keep last 7 days), and restore workflow for <workspace>/.code_os/.
"""
from __future__ import annotations

import datetime
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKUP_RETENTION_DAYS = 7


def _get_backup_dir(workspace: str) -> Path:
    """Return the path to .code_os/backups directory within workspace."""
    b_dir = Path(workspace) / ".code_os" / "backups"
    b_dir.mkdir(parents=True, exist_ok=True)
    return b_dir


def create_workspace_backup(workspace: str, reason: str = "scheduled") -> str | None:
    """
    Compress .code_os/ directory (excluding backups/) into a zip archive.
    Enforces 7-day rotation by pruning older backup archives.
    Returns path to the newly created backup archive.
    """
    if not workspace:
        return None
    code_os_dir = Path(workspace) / ".code_os"
    if not code_os_dir.is_dir():
        return None

    backup_dir = _get_backup_dir(workspace)
    now_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"code_os_backup_{now_str}.zip"
    backup_path = backup_dir / backup_filename

    try:
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(code_os_dir):
                # Skip the backups directory itself to prevent recursive inclusion
                if "backups" in Path(root).parts:
                    continue
                for file in files:
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(code_os_dir)
                    zipf.write(file_path, arcname=str(rel_path))

        logger.info("backup_service: Created backup %s (reason: %s)", backup_path.name, reason)
        # Rotate old backups
        _rotate_backups(backup_dir, max_days=BACKUP_RETENTION_DAYS)
        return str(backup_path)
    except Exception as exc:
        logger.error("backup_service: Failed creating backup for %s: %s", workspace, exc)
        return None


def _rotate_backups(backup_dir: Path, max_days: int = 7) -> int:
    """Prune backup files older than max_days."""
    pruned = 0
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=max_days)

    try:
        for item in backup_dir.glob("code_os_backup_*.zip"):
            mtime = datetime.datetime.utcfromtimestamp(item.stat().st_mtime)
            if mtime < cutoff:
                item.unlink(missing_ok=True)
                pruned += 1
                logger.info("backup_service: Pruned expired backup archive %s", item.name)
    except Exception as exc:
        logger.warning("backup_service: Error during backup rotation: %s", exc)
    return pruned


def list_workspace_backups(workspace: str) -> list[dict[str, Any]]:
    """List available backup archives in workspace with metadata."""
    if not workspace:
        return []
    backup_dir = Path(workspace) / ".code_os" / "backups"
    if not backup_dir.is_dir():
        return []

    backups = []
    for item in sorted(backup_dir.glob("code_os_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = item.stat()
        backups.append({
            "filename": item.name,
            "path": str(item),
            "size_bytes": st.st_size,
            "created_at": datetime.datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
        })
    return backups


def restore_workspace_backup(workspace: str, backup_filename: str | None = None) -> bool:
    """
    Restore .code_os/ directory from specified backup or most recent backup.
    """
    if not workspace:
        return False
    backup_dir = Path(workspace) / ".code_os" / "backups"
    if not backup_dir.is_dir():
        return False

    target_archive: Path | None = None
    if backup_filename:
        target_archive = backup_dir / backup_filename
        if not target_archive.is_file():
            target_archive = Path(backup_filename)
    else:
        existing = sorted(backup_dir.glob("code_os_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        if existing:
            target_archive = existing[0]

    if not target_archive or not target_archive.is_file():
        logger.error("backup_service: No valid backup archive found for restore in %s", workspace)
        return False

    code_os_dir = Path(workspace) / ".code_os"

    try:
        # Extract archive over .code_os/ (preserving backups/ directory)
        with zipfile.ZipFile(target_archive, "r") as zipf:
            for member in zipf.infolist():
                # Avoid zip-slip security risk
                member_path = (code_os_dir / member.filename).resolve()
                try:
                    member_path.relative_to(code_os_dir.resolve())
                except ValueError:
                    # Zip-slip: path escapes target directory — skip silently.
                    continue
                zipf.extract(member, path=code_os_dir)

        logger.info("backup_service: Successfully restored .code_os from %s", target_archive.name)
        return True
    except Exception as exc:
        logger.error("backup_service: Failed to restore backup %s: %s", target_archive, exc)
        return False
