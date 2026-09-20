"""Phase 12.6 Part 3b — Tests for DELETE, RENAME_MOVE, COPY, MKDIR, preflight conflicts, and directory snapshots.

Covers:
- DELETE file snapshot and rollback
- DELETE small directory rollback
- DELETE large directory trash move and rollback
- Large directory trash purge on commit
- Trash directory exclusion from listing, search, and indexing
- DELETE missing path tolerance (missing_ok)
- Protected path rejection (.git, workspace root, .code_os)
- DELETE synchronous invalidation for all files under deleted directory
- RENAME_MOVE invalidation of old and new paths in index
- RENAME_MOVE directory invalidation for all files
- RENAME_MOVE overwrite guard
- RENAME_MOVE cannot_move_into_self
- RENAME_MOVE rollback
- COPY directory rollback
- MKDIR and CREATE empty file
- Path traversal rejection on rename
- Preflight conflict rejection (same path, delete dir containing target)
- Symlink delete safety (unlinks link only, never touches target contents)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.features.ai.harness import mutation_pipeline as mp
from app.features.ai.harness.mutation_pipeline import (
    DIR_SNAPSHOT_MAX_BYTES,
    DIR_SNAPSHOT_MAX_FILES,
    Mutation,
    MutationKind,
    apply_mutations,
)
from app.features.ai.agents.agent_tools import _handle_find_function
from app.features.ai.harness.symbol_index import find_symbol, index_file
from app.features.files.service import get_directory_children
from app.features.search.service import search_files


def find_function(workspace: str, name: str) -> list:
    """Helper to query symbol index for a function name."""
    return find_symbol(workspace, name)


@pytest.fixture
def test_ws():
    """Create a temporary workspace directory for testing."""
    tmp = tempfile.TemporaryDirectory()
    ws = Path(tmp.name).resolve()
    yield ws
    tmp.cleanup()


# ── DELETE Tests ─────────────────────────────────────────────────────────────

def test_delete_file_snapshots_and_rolls_back_on_later_failure(test_ws: Path):
    target = test_ws / "target.txt"
    target.write_text("critical data", encoding="utf-8")

    # Batch with DELETE followed by a failing mutation in AGENT mode (broken syntax)
    mutations = [
        Mutation(kind=MutationKind.DELETE, path="target.txt"),
        Mutation(kind=MutationKind.WRITE_FULL, path="broken.py", new_content="def broken_syntax("),
    ]

    res = apply_mutations(test_ws, mutations, mode="AGENT")
    assert not res.success
    assert res.rejection is not None
    assert res.rejection.stage in ("validate", "apply")
    # File must be preserved with exact contents
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "critical data"


def test_delete_small_directory_rollback_restores_full_tree_bytes(test_ws: Path):
    folder = test_ws / "small_pkg"
    folder.mkdir(parents=True)
    sub = folder / "sub"
    sub.mkdir()
    (folder / "a.py").write_text("a = 1\n", encoding="utf-8")
    (sub / "b.txt").write_bytes(b"binary\x00data")

    mutations = [
        Mutation(kind=MutationKind.DELETE, path="small_pkg"),
        Mutation(kind=MutationKind.WRITE_FULL, path="broken.py", new_content="class :"),
    ]

    res = apply_mutations(test_ws, mutations, mode="AGENT")
    assert not res.success
    # Entire tree must be restored byte-exact
    assert folder.is_dir()
    assert (folder / "a.py").read_text(encoding="utf-8") == "a = 1\n"
    assert (sub / "b.txt").read_bytes() == b"binary\x00data"


def test_delete_large_directory_uses_trash_move_not_byte_copy(test_ws: Path, monkeypatch):
    big_dir = test_ws / "big_tree"
    big_dir.mkdir(parents=True)
    (big_dir / "large1.bin").write_bytes(b"X" * 100)
    (big_dir / "large2.bin").write_bytes(b"Y" * 100)

    # Monkeypatch the byte cap low so 200 bytes triggers the trash-move branch
    monkeypatch.setattr(mp, "DIR_SNAPSHOT_MAX_BYTES", 50)

    # Mock stage_apply to simulate failure on a subsequent mutation
    orig_apply = mp.stage_apply

    def failing_stage_apply(ws_root, projected, initial_snapshots, resolved_mutations=None):
        ok, rej, applied, state = orig_apply(ws_root, projected, initial_snapshots, resolved_mutations=resolved_mutations)
        # Verify that dir_snapshots used trash
        assert "big_tree" in state.dir_snapshots
        assert state.dir_snapshots["big_tree"].is_trash is True
        assert len(state.active_trash_roots) == 1
        trash_root = state.active_trash_roots[0]
        assert trash_root.exists()
        # Now simulate a failure on next operation
        return False, mp.RejectionDict(code="apply_failed", reason_text="Simulated failure", stage="apply"), applied, state

    monkeypatch.setattr(mp, "stage_apply", failing_stage_apply)

    mutations = [
        Mutation(kind=MutationKind.DELETE, path="big_tree"),
        Mutation(kind=MutationKind.WRITE_FULL, path="other.txt", new_content="hello"),
    ]

    res = apply_mutations(test_ws, mutations, mode="FS_OP")
    assert not res.success
    assert res.rejection.code == "apply_failed"

    # Rollback must restore big_tree byte-exact from trash
    assert big_dir.is_dir()
    assert (big_dir / "large1.bin").read_bytes() == b"X" * 100
    assert (big_dir / "large2.bin").read_bytes() == b"Y" * 100


def test_delete_large_directory_commit_purges_trash(test_ws: Path, monkeypatch):
    big_dir = test_ws / "big_tree_purge"
    big_dir.mkdir(parents=True)
    (big_dir / "data.bin").write_bytes(b"Z" * 100)

    monkeypatch.setattr(mp, "DIR_SNAPSHOT_MAX_BYTES", 20)

    res = apply_mutations(test_ws, [Mutation(kind=MutationKind.DELETE, path="big_tree_purge")], mode="FS_OP")
    assert res.success
    assert not big_dir.exists()

    # Trash directory under .code_os/trash must be purged on commit
    trash_dir = test_ws / ".code_os" / "trash"
    if trash_dir.exists():
        entries = list(trash_dir.iterdir())
        assert len(entries) == 0


def test_trash_dir_excluded_from_listing_search_and_index(test_ws: Path):
    trash_folder = test_ws / ".code_os" / "trash" / str(uuid.uuid4()) / "hidden_dir"
    trash_folder.mkdir(parents=True)
    trash_file = trash_folder / "secret_logic.py"
    trash_file.write_text("def secret_treasure():\n    return 42\n", encoding="utf-8")

    # 1. File listing exclusion
    children = get_directory_children(str(test_ws))
    child_names = [c.name for c in children]
    assert ".code_os" not in child_names

    # 2. Search exclusion
    search_res = search_files(str(test_ws), "secret_treasure")
    assert len(search_res) == 0

    # 3. Symbol index exclusion
    fns = find_function(str(test_ws), "secret_treasure")
    assert len(fns) == 0


def test_delete_missing_path_rejected_unless_missing_ok(test_ws: Path):
    res = apply_mutations(test_ws, [Mutation(kind=MutationKind.DELETE, path="nonexistent.txt")], mode="FS_OP")
    assert not res.success
    assert res.rejection.code == "path_not_found"

    # With missing_ok=True, it should succeed cleanly
    res_ok = apply_mutations(test_ws, [Mutation(kind=MutationKind.DELETE, path="nonexistent.txt", missing_ok=True)], mode="FS_OP")
    assert res_ok.success


def test_delete_protected_paths_rejected(test_ws: Path):
    (test_ws / ".git").mkdir(exist_ok=True)
    (test_ws / ".code_os").mkdir(exist_ok=True)

    protected_targets = ["", ".", ".git", ".git/config", ".code_os", ".code_os/state.json"]
    for p in protected_targets:
        res = apply_mutations(test_ws, [Mutation(kind=MutationKind.DELETE, path=p)], mode="FS_OP")
        assert not res.success, f"Deleting protected path '{p}' was not rejected"
        assert res.rejection.code == "protected_path"


def test_delete_invalidates_index_for_every_file_under_deleted_directory(test_ws: Path):
    pkg = test_ws / "mod_pkg"
    pkg.mkdir()
    sub = pkg / "sub"
    sub.mkdir()
    f1 = pkg / "mod1.py"
    f2 = sub / "mod2.py"
    f1.write_text("def func_mod1():\n    pass\n", encoding="utf-8")
    f2.write_text("def func_mod2():\n    pass\n", encoding="utf-8")

    index_file(f1)
    index_file(f2)
    assert len(find_function(str(test_ws), "func_mod1")) == 1
    assert len(find_function(str(test_ws), "func_mod2")) == 1

    res = apply_mutations(test_ws, [Mutation(kind=MutationKind.DELETE, path="mod_pkg")], mode="FS_OP")
    assert res.success

    assert len(find_function(str(test_ws), "func_mod1")) == 0
    assert len(find_function(str(test_ws), "func_mod2")) == 0


# ── RENAME_MOVE / COPY / MKDIR Tests ─────────────────────────────────────────

def test_rename_invalidates_old_and_new_paths_in_index(test_ws: Path):
    old_f = test_ws / "old_name.py"
    new_f = test_ws / "new_name.py"
    old_f.write_text("def unique_metric_calc():\n    return 100\n", encoding="utf-8")

    index_file(old_f)
    matches_before = find_function(str(test_ws), "unique_metric_calc")
    assert len(matches_before) == 1
    assert "old_name.py" in matches_before[0].path

    res = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="old_name.py", new_path="new_name.py")],
        mode="FS_OP",
    )
    assert res.success
    assert not old_f.exists()
    assert new_f.exists()

    # Querying the index now reflects new path
    matches_after = find_function(str(test_ws), "unique_metric_calc")
    assert len(matches_after) == 1
    assert "new_name.py" in matches_after[0].path


def test_rename_directory_invalidates_all_files_old_and_new(test_ws: Path):
    d_old = test_ws / "service_v1"
    d_old.mkdir()
    f1 = d_old / "handler.py"
    f1.write_text("def handle_v1_request():\n    return 'v1'\n", encoding="utf-8")

    index_file(f1)
    assert len(find_function(str(test_ws), "handle_v1_request")) == 1

    res = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="service_v1", new_path="service_v2")],
        mode="FS_OP",
    )
    assert res.success

    matches = find_function(str(test_ws), "handle_v1_request")
    assert len(matches) == 1
    assert "service_v2" in matches[0].path
    assert "service_v1" not in matches[0].path


def test_rename_to_existing_destination_rejected_unless_overwrite(test_ws: Path):
    f1 = test_ws / "source.txt"
    f2 = test_ws / "dest.txt"
    f1.write_text("source content", encoding="utf-8")
    f2.write_text("dest content", encoding="utf-8")

    res = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="source.txt", new_path="dest.txt")],
        mode="FS_OP",
    )
    assert not res.success
    assert res.rejection.code == "destination_exists"
    assert f1.read_text(encoding="utf-8") == "source content"
    assert f2.read_text(encoding="utf-8") == "dest content"

    # With overwrite=True, succeeds
    res_ovw = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="source.txt", new_path="dest.txt", overwrite=True)],
        mode="FS_OP",
    )
    assert res_ovw.success
    assert not f1.exists()
    assert f2.read_text(encoding="utf-8") == "source content"


def test_move_directory_into_itself_rejected(test_ws: Path):
    folder = test_ws / "parent_dir"
    folder.mkdir()

    # Move into subdirectory of itself
    res = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="parent_dir", new_path="parent_dir/child")],
        mode="FS_OP",
    )
    assert not res.success
    assert res.rejection.code == "cannot_move_into_self"

    # Move into itself
    res_self = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="parent_dir", new_path="parent_dir")],
        mode="FS_OP",
    )
    assert not res_self.success
    assert res_self.rejection.code in ("cannot_move_into_self", "destination_exists")


def test_rename_rollback_moves_back_when_later_mutation_fails(test_ws: Path):
    src = test_ws / "rename_me.txt"
    dst = test_ws / "renamed.txt"
    src.write_text("hello rename", encoding="utf-8")

    mutations = [
        Mutation(kind=MutationKind.RENAME_MOVE, old_path="rename_me.txt", new_path="renamed.txt"),
        Mutation(kind=MutationKind.WRITE_FULL, path="broken.py", new_content="def (" ),
    ]

    res = apply_mutations(test_ws, mutations, mode="AGENT")
    assert not res.success
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "hello rename"
    assert not dst.exists()


def test_copy_directory_rollback_removes_partial_copy(test_ws: Path):
    src_dir = test_ws / "template_dir"
    src_dir.mkdir()
    (src_dir / "conf.json").write_text("{}", encoding="utf-8")

    mutations = [
        Mutation(kind=MutationKind.COPY, src_path="template_dir", dst_path="copied_dir"),
        Mutation(kind=MutationKind.WRITE_FULL, path="fail.py", new_content="def (broken"),
    ]

    res = apply_mutations(test_ws, mutations, mode="AGENT")
    assert not res.success
    assert src_dir.exists()
    assert not (test_ws / "copied_dir").exists()


def test_mkdir_and_create_empty_file_via_pipeline(test_ws: Path):
    mutations = [
        Mutation(kind=MutationKind.MKDIR, path="deep/nested/dir"),
        Mutation(kind=MutationKind.CREATE, path="deep/nested/dir/empty.txt", content=""),
    ]

    res = apply_mutations(test_ws, mutations, mode="FS_OP")
    assert res.success
    target_f = test_ws / "deep/nested/dir/empty.txt"
    assert target_f.is_file()
    assert target_f.read_text(encoding="utf-8") == ""


def test_traversal_on_either_path_of_rename_rejected_zero_disk_touch(test_ws: Path):
    (test_ws / "legit.txt").write_text("legit", encoding="utf-8")

    # Source traversal
    res_src = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="../../outside.txt", new_path="legit2.txt")],
        mode="FS_OP",
    )
    assert not res_src.success
    assert res_src.rejection.code in ("path_outside_workspace", "symlink_escape")

    # Destination traversal
    res_dst = apply_mutations(
        test_ws,
        [Mutation(kind=MutationKind.RENAME_MOVE, old_path="legit.txt", new_path="../../outside.txt")],
        mode="FS_OP",
    )
    assert not res_dst.success
    assert res_dst.rejection.code in ("path_outside_workspace", "symlink_escape")
    assert (test_ws / "legit.txt").exists()


# ── Preflight Conflict Tests ────────────────────────────────────────────────

def test_batch_two_mutations_same_path_rejected_zero_disk_touch(test_ws: Path):
    (test_ws / "file.txt").write_text("v1", encoding="utf-8")

    mutations = [
        Mutation(kind=MutationKind.WRITE_FULL, path="file.txt", new_content="v2"),
        Mutation(kind=MutationKind.DELETE, path="file.txt"),
    ]

    res = apply_mutations(test_ws, mutations, mode="FS_OP")
    assert not res.success
    assert res.rejection.code == "conflicting_mutations"
    assert (test_ws / "file.txt").read_text(encoding="utf-8") == "v1"


def test_batch_delete_dir_and_write_inside_it_rejected(test_ws: Path):
    folder = test_ws / "work"
    folder.mkdir()
    child = folder / "task.txt"
    child.write_text("task", encoding="utf-8")

    mutations = [
        Mutation(kind=MutationKind.DELETE, path="work"),
        Mutation(kind=MutationKind.WRITE_FULL, path="work/task.txt", new_content="new task"),
    ]

    res = apply_mutations(test_ws, mutations, mode="FS_OP")
    assert not res.success
    assert res.rejection.code == "conflicting_mutations"
    assert child.read_text(encoding="utf-8") == "task"


# ── Symlink Safety Tests ────────────────────────────────────────────────────

def test_delete_does_not_follow_symlink_out_of_workspace(test_ws: Path):
    """Real Windows symlink test (runs if privilege available; skips with explicit reason if not)."""
    outside_dir = tempfile.TemporaryDirectory()
    outside_path = Path(outside_dir.name).resolve()
    secret_file = outside_path / "secret.txt"
    secret_file.write_text("top secret", encoding="utf-8")

    link_path = test_ws / "symlink_dir"
    try:
        os.symlink(str(outside_path), str(link_path), target_is_directory=True)
    except OSError as e:
        outside_dir.cleanup()
        pytest.skip(f"Windows Developer Mode / symlink privilege not held: {e}")

    assert link_path.is_symlink()

    res = apply_mutations(test_ws, [Mutation(kind=MutationKind.DELETE, path="symlink_dir")], mode="FS_OP")
    assert res.success
    # The symlink inside the workspace should be gone
    assert not link_path.exists()
    assert not link_path.is_symlink()
    # But the outside target and its contents MUST be untouched
    assert outside_path.exists()
    assert secret_file.exists()
    assert secret_file.read_text(encoding="utf-8") == "top secret"

    outside_dir.cleanup()


def test_delete_does_not_follow_symlink_out_of_workspace_mocked(test_ws: Path, monkeypatch):
    """Mock-based version guaranteeing the symlink branch is always exercised."""
    mock_link = test_ws / "mock_link"
    mock_link.write_text("stub", encoding="utf-8")

    unlinked = False
    rmtree_called = False

    orig_unlink = Path.unlink
    def fake_unlink(self, *args, **kwargs):
        nonlocal unlinked
        if self == mock_link:
            unlinked = True
        return orig_unlink(self, *args, **kwargs)

    orig_rmtree = shutil.rmtree
    def fake_rmtree(path, *args, **kwargs):
        nonlocal rmtree_called
        if str(mock_link) in str(path):
            rmtree_called = True
        return orig_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_symlink", lambda self: True if self == mock_link else False)
    monkeypatch.setattr(os, "readlink", lambda path: "D:\\external\\target")
    monkeypatch.setattr(Path, "unlink", fake_unlink)
    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    res = apply_mutations(test_ws, [Mutation(kind=MutationKind.DELETE, path="mock_link")], mode="FS_OP")
    assert res.success
    assert unlinked is True
    assert rmtree_called is False
