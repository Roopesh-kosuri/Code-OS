import os
import tempfile
from pathlib import Path
import pytest
from app.core.paths import (
    ensure_within_workspace,
    verify_path_unchanged,
    safe_write_file,
    safe_read_file,
)
from fastapi import HTTPException


def test_similar_prefix_rejected():
    with tempfile.TemporaryDirectory() as tmp_base:
        base = Path(tmp_base)
        proj = base / "proj"
        proj_evil = base / "proj-evil"
        proj.mkdir()
        proj_evil.mkdir()

        evil_file = proj_evil / "file.txt"
        evil_file.write_text("evil", encoding="utf-8")

        # Must reject evil_file as not within proj
        with pytest.raises(HTTPException) as exc:
            ensure_within_workspace(str(proj), str(evil_file))
        assert exc.value.status_code == 403


def test_exact_workspace_allowed():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        test_file = ws / "test.txt"
        test_file.write_text("hello", encoding="utf-8")

        res = ensure_within_workspace(str(ws), "test.txt")
        assert res.resolve() == test_file.resolve()


def test_subdirectory_allowed():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        sub = ws / "subdir"
        sub.mkdir()
        sub_file = sub / "sub.txt"
        sub_file.write_text("nested", encoding="utf-8")

        res = ensure_within_workspace(str(ws), "subdir/sub.txt")
        assert res.resolve() == sub_file.resolve()


def test_symlink_swap_detected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        target1 = ws / "target1.txt"
        target1.write_text("one", encoding="utf-8")

        target2 = ws / "target2.txt"
        target2.write_text("two", encoding="utf-8")

        # Initial check resolution
        check_path = target1.resolve()

        # If unchanged:
        assert verify_path_unchanged(target1, check_path) is True

        # If path is swapped to target2:
        assert verify_path_unchanged(target2, check_path) is False


def test_safe_write_and_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        written = safe_write_file(str(ws), "output.txt", "safe content")
        assert written.exists()

        content = safe_read_file(str(ws), "output.txt")
        assert content == "safe content"
