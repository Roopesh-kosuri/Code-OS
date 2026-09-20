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
from fastapi import HTTPException

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


def test_crash_recovery_stale_trash_cleaned_on_next_call(test_ws: Path):
    """A stale trash entry left behind by a crash is hidden from users and cleaned on next call."""
    crash_id = str(uuid.uuid4())
    crash_trash_dir = test_ws / ".code_os" / "trash" / crash_id / "leftover_dir"
    crash_trash_dir.mkdir(parents=True)
    crashed_file = crash_trash_dir / "crash_logic.py"
    crashed_file.write_text("def crash_symbol():\n    return 'crashed'\n", encoding="utf-8")

    # 1. Stale crash trash is hidden from users
    children = get_directory_children(str(test_ws))
    assert ".code_os" not in [c.name for c in children]
    assert len(search_files(str(test_ws), "crash_symbol")) == 0
    assert len(find_function(str(test_ws), "crash_symbol")) == 0

    # 2. Next call to apply_mutations runs
    mut = Mutation(kind=MutationKind.CREATE, path="normal_file.txt", new_content="recovered\n")
    res = apply_mutations(test_ws, [mut], mode="FS_OP")
    assert res.success is True

    # 3. Crash trash entry has been cleaned on next call
    stale_entry = test_ws / ".code_os" / "trash" / crash_id
    assert not stale_entry.exists()
    assert (test_ws / "normal_file.txt").read_text(encoding="utf-8") == "recovered\n"


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


# ── Files Adapter Tests ──────────────────────────────────────────────────────

def test_create_delete_rename_move_duplicate_keep_legacy_http_errors(test_ws: Path):
    """File CRUD operations maintain legacy HTTP error statuses (400, 404, 409, 403)."""
    from app.features.files.service import (
        create_entry,
        delete_entry,
        rename_entry,
        move_entry,
        duplicate_entry,
    )

    ws_str = str(test_ws)

    # 400 on empty name
    with pytest.raises(HTTPException) as exc_info:
        create_entry(ws_str, "", "file")
    assert exc_info.value.status_code == 400
    assert "empty" in exc_info.value.detail.lower()

    # 400 on invalid characters in filename
    with pytest.raises(HTTPException) as exc_info:
        create_entry(ws_str, "bad?name.txt", "file")
    assert exc_info.value.status_code == 400

    # 400 on invalid type
    with pytest.raises(HTTPException) as exc_info:
        create_entry(ws_str, "file.txt", "unknown")
    assert exc_info.value.status_code == 400

    # 409 on destination already exists
    create_entry(ws_str, "existing.txt", "file")
    with pytest.raises(HTTPException) as exc_info:
        create_entry(ws_str, "existing.txt", "file")
    assert exc_info.value.status_code == 409

    # 404 on delete not found
    with pytest.raises(HTTPException) as exc_info:
        delete_entry(ws_str, "nonexistent.txt")
    assert exc_info.value.status_code == 404

    # 404 on rename not found
    with pytest.raises(HTTPException) as exc_info:
        rename_entry(ws_str, "nonexistent.txt", "new.txt")
    assert exc_info.value.status_code == 404

    # 400 on invalid rename new name
    with pytest.raises(HTTPException) as exc_info:
        rename_entry(ws_str, "existing.txt", "sub/new.txt")
    assert exc_info.value.status_code == 400

    # 409 on rename destination exists
    create_entry(ws_str, "dest.txt", "file")
    with pytest.raises(HTTPException) as exc_info:
        rename_entry(ws_str, "existing.txt", "dest.txt")
    assert exc_info.value.status_code == 409

    # 404 on move source not found
    with pytest.raises(HTTPException) as exc_info:
        move_entry(ws_str, "nonexistent.txt", "dest2.txt")
    assert exc_info.value.status_code == 404

    # 409 on move destination exists
    with pytest.raises(HTTPException) as exc_info:
        move_entry(ws_str, "existing.txt", "dest.txt")
    assert exc_info.value.status_code == 409

    # 404 on duplicate source not found
    with pytest.raises(HTTPException) as exc_info:
        duplicate_entry(ws_str, "nonexistent.txt")
    assert exc_info.value.status_code == 404

    # 409 on duplicate destination exists
    with pytest.raises(HTTPException) as exc_info:
        duplicate_entry(ws_str, "existing.txt", "dest.txt")
    assert exc_info.value.status_code == 409

    # 400 / 403 on traversal
    with pytest.raises(HTTPException) as exc_info:
        create_entry(ws_str, "../../outside.txt", "file")
    assert exc_info.value.status_code in (400, 403)


def test_file_tree_ops_clear_directory_cache_once(test_ws: Path):
    """File CRUD operations clear directory_cache via the pipeline invalidation hook exactly once."""
    from app.features.files.service import (
        directory_cache,
        create_entry,
        delete_entry,
        rename_entry,
        move_entry,
        duplicate_entry,
    )

    ws_str = str(test_ws)

    with patch.object(directory_cache, "invalidate", wraps=directory_cache.invalidate) as mock_inv:
        # 1. create_entry
        create_entry(ws_str, "doc.txt", "file")
        assert mock_inv.call_count == 1
        mock_inv.reset_mock()

        # 2. duplicate_entry
        duplicate_entry(ws_str, "doc.txt", "doc_copy.txt")
        assert mock_inv.call_count == 1
        mock_inv.reset_mock()

        # 3. rename_entry
        rename_entry(ws_str, "doc_copy.txt", "doc_renamed.txt")
        assert mock_inv.call_count == 1
        mock_inv.reset_mock()

        # 4. move_entry
        create_entry(ws_str, "sub", "directory")
        mock_inv.reset_mock()
        move_entry(ws_str, "doc_renamed.txt", "sub/doc_moved.txt")
        assert mock_inv.call_count == 1
        mock_inv.reset_mock()

        # 5. delete_entry
        delete_entry(ws_str, "sub/doc_moved.txt")
        assert mock_inv.call_count == 1


def test_file_tree_ops_do_not_run_syntax_gate(test_ws: Path):
    """File operations use FS_OP mode and do not block on syntactically broken code."""
    from app.features.files.service import create_entry, rename_entry, move_entry

    ws_str = str(test_ws)

    # Creating an empty python file succeeds
    p = create_entry(ws_str, "module.py", "file")
    assert p.exists()

    # Write syntactically broken python
    p.write_text("def unclosed_paren(\n", encoding="utf-8")

    # Rename should succeed because FS_OP mode skips syntax validation
    p_renamed = rename_entry(ws_str, "module.py", "renamed_module.py")
    assert p_renamed.exists()
    assert not p.exists()
    assert p_renamed.read_text(encoding="utf-8") == "def unclosed_paren(\n"

    # Move should also succeed
    create_entry(ws_str, "folder", "directory")
    p_moved = move_entry(ws_str, "renamed_module.py", "folder/moved_module.py")
    assert p_moved.exists()
    assert p_moved.read_text(encoding="utf-8") == "def unclosed_paren(\n"


# ── Replace Text Adapter Tests ──────────────────────────────────────────────

def test_replace_text_failure_on_file_8_of_15_rolls_back_files_1_to_7(test_ws: Path, monkeypatch):
    """Failure on file 8 during multi-file text replace rolls back files 1..7 atomically."""
    from app.features.search.service import replace_text

    ws_str = str(test_ws)
    files = []
    for i in range(1, 16):
        f = test_ws / f"file_{i:02d}.txt"
        f.write_text("target_token is here\n", encoding="utf-8")
        files.append(f)

    # Hook os.replace to fail on file_08.txt
    orig_replace = os.replace

    def fake_replace(src, dst, *args, **kwargs):
        if "file_08.txt" in str(dst):
            raise OSError("Simulated disk error on file 8")
        return orig_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fake_replace)

    with pytest.raises(HTTPException) as exc_info:
        replace_text(ws_str, "target_token", "replaced_token", apply=True)
    assert exc_info.value.status_code == 500

    # Verify atomic rollback: files 1 to 7 must still have original content!
    for i in range(1, 16):
        assert (test_ws / f"file_{i:02d}.txt").read_text(encoding="utf-8") == "target_token is here\n"


def test_replace_text_invalid_encoding_file_reported_skipped_batch_continues(test_ws: Path):
    """Files with non-UTF-8 bytes are reported as skipped while valid files are replaced."""
    from app.features.search.service import replace_text

    ws_str = str(test_ws)
    f_valid = test_ws / "valid.txt"
    f_valid.write_text("replace_me please\n", encoding="utf-8")

    f_bin = test_ws / "binary.txt"
    f_bin.write_bytes(b"hello \x80\x81 world\n")

    results = replace_text(ws_str, "replace_me", "done", apply=True)

    # Valid file was replaced
    assert f_valid.read_text(encoding="utf-8") == "done please\n"
    # Binary file untouched
    assert f_bin.read_bytes() == b"hello \x80\x81 world\n"

    # Verify reported results
    skipped_entries = [r for r in results if r.skipped]
    applied_entries = [r for r in results if not r.skipped]

    assert len(skipped_entries) == 1
    assert skipped_entries[0].path == f_bin
    assert skipped_entries[0].skip_reason == "encoding"

    assert len(applied_entries) == 1
    assert applied_entries[0].path == f_valid
    assert applied_entries[0].count == 1


def test_replace_text_response_shape_unchanged(test_ws: Path):
    """ReplaceEntry preserves 2-tuple unpacking (path, count) and exposes skipped metadata."""
    from app.features.search.service import replace_text

    ws_str = str(test_ws)
    f = test_ws / "doc.txt"
    f.write_text("apple apple apple\n", encoding="utf-8")

    results = replace_text(ws_str, "apple", "orange", apply=False)
    assert len(results) == 1

    # 2-tuple unpacking
    path, count = results[0]
    assert path == f
    assert count == 3
    assert results[0].skipped is False
    assert results[0].skip_reason is None


def test_replace_text_invalidates_index_for_every_changed_file(test_ws: Path):
    """Synchronous invalidation runs for every file modified by replace_text."""
    from app.features.search.service import replace_text
    from app.features.ai.harness.symbol_index import _symbol_index, index_file

    ws_str = str(test_ws)
    f1 = test_ws / "mod1.py"
    f1.write_text("def find_symbol_alpha(): pass\n", encoding="utf-8")
    f2 = test_ws / "mod2.py"
    f2.write_text("def find_symbol_beta(): pass\n", encoding="utf-8")

    index_file(f1, workspace=ws_str)
    index_file(f2, workspace=ws_str)

    assert str(f1.resolve()) in _symbol_index._cache
    assert str(f2.resolve()) in _symbol_index._cache

    replace_text(ws_str, "find_symbol_", "indexed_", apply=True)

    # Both must be synchronously invalidated by pipeline S5
    assert str(f1.resolve()) not in _symbol_index._cache
    assert str(f2.resolve()) not in _symbol_index._cache


# ── Staging Review Adapter Tests ─────────────────────────────────────────────

def test_staging_write_fails_delete_not_executed_and_write_rolled_back(test_ws: Path):
    """When a write fails syntax in AGENT mode, delete is not executed and write is rolled back."""
    from app.features.ai.staging.staging_review_service import (
        _STAGED_REVIEWS,
        apply_approved_changes,
    )

    ws_str = str(test_ws)
    existing_del = test_ws / "delete_target.txt"
    existing_del.write_text("keep or delete", encoding="utf-8")

    job_id = "test_job_atomic_fail"
    _STAGED_REVIEWS[job_id] = {
        "workspace": ws_str,
        "files": {
            "broken.py": {
                "status": "modified",
                "approved": True,
                "updated": "def broken_syntax(\n",
                "original": "",
                "chunks": [{"type": "insert", "content": "def broken_syntax(\n", "approved": True}],
            },
            "delete_target.txt": {
                "status": "deleted",
                "approved": True,
                "chunks": [],
            },
        },
    }

    res = apply_approved_changes(job_id)
    assert res["success"] is False
    assert "syntax" in res.get("error", "").lower() or "rejected" in res.get("error", "").lower()

    # Delete must NOT have been executed
    assert existing_del.exists()
    assert existing_del.read_text(encoding="utf-8") == "keep or delete"
    # Broken write must NOT be on disk
    assert not (test_ws / "broken.py").exists()


def test_staging_delete_fails_earlier_writes_rolled_back(test_ws: Path, monkeypatch):
    """When a delete fails during apply, earlier writes in the batch are rolled back."""
    from app.features.ai.staging.staging_review_service import (
        _STAGED_REVIEWS,
        apply_approved_changes,
    )

    ws_str = str(test_ws)
    written_file = test_ws / "valid.py"
    written_file.write_text("initial = 1\n", encoding="utf-8")

    del_file = test_ws / "del.txt"
    del_file.write_text("to be deleted", encoding="utf-8")

    job_id = "test_job_delete_fail"
    _STAGED_REVIEWS[job_id] = {
        "workspace": ws_str,
        "files": {
            "valid.py": {
                "status": "modified",
                "approved": True,
                "updated": "initial = 2\n",
                "original": "initial = 1\n",
                "chunks": [{"type": "insert", "content": "initial = 2\n", "approved": True}],
            },
            "del.txt": {
                "status": "deleted",
                "approved": True,
                "chunks": [],
            },
        },
    }

    # Inject failure on delete in Path.unlink
    orig_unlink = Path.unlink

    def fake_unlink(self, *args, **kwargs):
        if "del.txt" in str(self):
            raise OSError("Simulated delete disk failure")
        return orig_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fake_unlink)

    res = apply_approved_changes(job_id)
    assert res["success"] is False

    # Earlier write must be rolled back to initial = 1
    assert written_file.read_text(encoding="utf-8") == "initial = 1\n"


def test_staging_response_shape_unchanged_rejected_files_populated(test_ws: Path):
    """apply_approved_changes response maintains required dict shape and rejected list."""
    from app.features.ai.staging.staging_review_service import (
        _STAGED_REVIEWS,
        apply_approved_changes,
    )

    ws_str = str(test_ws)
    f_ok = test_ws / "ok.txt"
    f_ok.write_text("old", encoding="utf-8")

    job_id = "test_job_shape"
    _STAGED_REVIEWS[job_id] = {
        "workspace": ws_str,
        "files": {
            "ok.txt": {
                "status": "modified",
                "approved": True,
                "updated": "new",
                "original": "old",
                "chunks": [{"type": "insert", "content": "new", "approved": True}],
            },
            "unapproved.txt": {
                "status": "modified",
                "approved": False,
                "updated": "new2",
                "original": "old2",
                "chunks": [],
            },
        },
    }

    res = apply_approved_changes(job_id)
    assert res["success"] is True
    assert res["job_id"] == job_id
    assert "ok.txt" in res["applied_files"]
    assert "unapproved.txt" in res["rejected_files"]
    assert "remaining_files" in res


# ── Undo Turn Adapter Tests ──────────────────────────────────────────────────

def _setup_git_repo(ws: Path) -> str:
    """Helper to initialize a git repo with user configs."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(ws), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(ws), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(ws), capture_output=True, check=True)
    f = ws / "init.txt"
    f.write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(ws), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(ws), capture_output=True, check=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ws), capture_output=True, text=True, check=True).stdout.strip()
    return commit


def test_undo_turn_routes_through_pipeline_and_invalidates_once(test_ws: Path):
    """undo_turn_files routes writes through mutation_pipeline and invalidates index exactly once."""
    from app.features.ai.harness.checkpoint_manager import undo_turn_files
    import app.features.ai.harness.symbol_index as si

    ws_str = str(test_ws)
    commit_hash = _setup_git_repo(test_ws)

    # Add a tracked file
    code_file = test_ws / "tracked.py"
    code_file.write_text("def base_func(): pass\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "tracked.py"], cwd=ws_str, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add tracked.py"], cwd=ws_str, capture_output=True, check=True)
    commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws_str, capture_output=True, text=True, check=True).stdout.strip()

    # Modify file
    code_file.write_text("def modified_func(): pass\n", encoding="utf-8")

    with patch("app.features.ai.harness.mutation_pipeline.invalidate_file", wraps=si.invalidate_file) as mock_inv:
        ok, msg, restored = undo_turn_files(ws_str, commit_hash, ["tracked.py"])
        assert ok is True
        assert "tracked.py" in restored
        assert code_file.read_text(encoding="utf-8") == "def base_func(): pass\n"
        assert mock_inv.call_count == 1


def test_undo_turn_hash_mismatch_reported_not_swallowed(test_ws: Path, monkeypatch):
    """Hash mismatch after restore write is reported in failures and not swallowed."""
    from app.features.ai.harness.checkpoint_manager import undo_turn_files

    ws_str = str(test_ws)
    commit_hash = _setup_git_repo(test_ws)

    code_file = test_ws / "tracked.py"
    code_file.write_text("def base_func(): pass\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "tracked.py"], cwd=ws_str, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add tracked.py"], cwd=ws_str, capture_output=True, check=True)
    commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws_str, capture_output=True, text=True, check=True).stdout.strip()

    code_file.write_text("def modified(): pass\n", encoding="utf-8")

    # Simulate hash mismatch by tampering with file bytes right after write
    import app.features.ai.harness.mutation_pipeline as mp_module
    orig_apply = mp_module.apply_mutations

    def tampering_apply(ws, mutations, mode="FS_OP"):
        res = orig_apply(ws, mutations, mode=mode)
        (test_ws / "tracked.py").write_text("corrupted content", encoding="utf-8")
        return res

    monkeypatch.setattr(mp_module, "apply_mutations", tampering_apply)

    ok, msg, restored = undo_turn_files(ws_str, commit_hash, ["tracked.py"])
    assert ok is False
    assert "restored bytes do not match checkpoint" in msg


def test_undo_turn_restoring_syntactically_broken_prior_version_succeeds(test_ws: Path):
    """undo_turn_files in FS_OP mode restores syntactically broken code without syntax errors."""
    from app.features.ai.harness.checkpoint_manager import undo_turn_files

    ws_str = str(test_ws)
    commit_hash = _setup_git_repo(test_ws)

    broken_file = test_ws / "broken.py"
    broken_file.write_text("def syntax_error(\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "broken.py"], cwd=ws_str, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add broken.py"], cwd=ws_str, capture_output=True, check=True)
    commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws_str, capture_output=True, text=True, check=True).stdout.strip()

    # Now make it valid
    broken_file.write_text("def valid_func(): pass\n", encoding="utf-8")

    # Undo to broken version
    ok, msg, restored = undo_turn_files(ws_str, commit_hash, ["broken.py"])
    assert ok is True
    assert "broken.py" in restored
    assert broken_file.read_text(encoding="utf-8") == "def syntax_error(\n"


def test_undo_turn_partial_failure_reports_per_file_state(test_ws: Path):
    """Partial failure in undo_turn_files restores valid files and reports failing files."""
    from app.features.ai.harness.checkpoint_manager import undo_turn_files

    ws_str = str(test_ws)
    commit_hash = _setup_git_repo(test_ws)

    f1 = test_ws / "valid.py"
    f1.write_text("def f1(): pass\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "valid.py"], cwd=ws_str, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add valid.py"], cwd=ws_str, capture_output=True, check=True)
    commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws_str, capture_output=True, text=True, check=True).stdout.strip()

    # Modify f1 and create a directory named f2.py (which causes git show error / directory collision)
    f1.write_text("def f1_mod(): pass\n", encoding="utf-8")
    f2_dir = test_ws / "dir_as_file"
    f2_dir.mkdir()

    # dir_as_file is not in checkpoint, but on disk it's a directory -> git show fails, fp.is_dir() causes failure!
    ok, msg, restored = undo_turn_files(ws_str, commit_hash, ["valid.py", "dir_as_file"])
    assert ok is False
    assert "dir_as_file: expected file path is a directory" in msg
    assert "valid.py" in restored
    assert f1.read_text(encoding="utf-8") == "def f1(): pass\n"


# ── Write-Primitive Scan Guard ───────────────────────────────────────────────

def test_no_unrouted_workspace_writes_scan():
    """Repo-wide AST scan across backend/app asserting ZERO unrouted workspace writes and ZERO deferred items."""
    import ast
    from pathlib import Path

    app_dir = Path("backend/app")

    def is_write_call(node: ast.Call):
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in ("write_text", "write_bytes", "unlink", "mkdir", "rmdir"):
                return True, f"Path.{attr}"
            if attr == "rename":
                return True, "rename"
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                if attr in ("replace", "remove", "unlink", "rmdir", "mkdir", "makedirs", "rename"):
                    return True, f"os.{attr}"
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "shutil":
                if attr in ("move", "copy", "copy2", "copytree", "rmtree"):
                    return True, f"shutil.{attr}"
        elif isinstance(node.func, ast.Name):
            if node.func.id == "NamedTemporaryFile":
                return True, "NamedTemporaryFile"
            if node.func.id == "open":
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and any(m in arg.value for m in ("w", "a")):
                        return True, f"open({arg.value})"
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str) and any(m in kw.value.value for m in ("w", "a")):
                        return True, f"open(mode={kw.value.value})"
        return False, ""

    class FunctionVisitor(ast.NodeVisitor):
        def __init__(self):
            self.scope_stack = ["<module>"]
            self.calls = []

        def visit_FunctionDef(self, node):
            self.scope_stack.append(node.name)
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_AsyncFunctionDef(self, node):
            self.scope_stack.append(node.name)
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_Call(self, node):
            ok, name = is_write_call(node)
            if ok:
                self.calls.append((node.lineno, self.scope_stack[-1], name))
            self.generic_visit(node)

    ALLOWED_FUNCTIONS = {
        ("core/auth.py", "load_token"): "non-workspace (app session token cleanup)",
        ("core/auth.py", "generate_and_store_token"): "non-workspace (app session token creation)",
        ("core/config.py", "get_settings"): "non-workspace (app storage directory setup)",
        ("core/logging.py", "configure_logging"): "non-workspace (app logs directory setup)",
        ("core/security.py", "_load_or_create_key"): "non-workspace (app secret key store)",
        ("db/database.py", "init_db"): "non-workspace (app sqlite db setup)",
        ("core/paths.py", "safe_write_file"): "unused-helper (safe_write_file in core/paths.py)",
        ("core/plugins/plugin_manager.py", "__init__"): "non-workspace (plugin cache)",
        ("core/plugins/routes.py", "install_plugin"): "non-workspace (plugin cache / install)",
        ("features/ai/file_ingestion/service.py", "get_uploads_dir"): "non-workspace (unpacked upload cache)",
        ("features/ai/file_ingestion/service.py", "save_uploaded_file"): "non-workspace (unpacked upload cache)",
        ("features/ai/file_ingestion/service.py", "delete_uploaded_file"): "non-workspace (unpacked upload cache)",
        ("features/ai/backup_service.py", "_get_backup_dir"): "non-workspace (app backups)",
        ("features/ai/backup_service.py", "_rotate_backups"): "non-workspace (app backups)",
        ("features/ai/harness/activity_logger.py", "_rotate_activity_log"): "non-workspace (.code_os activity log)",
        ("features/ai/harness/activity_logger.py", "_append_activity_log"): "non-workspace (.code_os activity log)",
        ("features/ai/harness/activity_logger.py", "_get_interrupted_state_path"): "non-workspace (.code_os activity log)",
        ("features/ai/harness/activity_logger.py", "_save_interrupted_state"): "non-workspace (.code_os activity log)",
        ("features/ai/harness/activity_logger.py", "_clear_interrupted_state"): "non-workspace (.code_os activity log)",
        ("features/ai/harness/approval_coordinator.py", "_get_trusted_commands_path"): "non-workspace (.code_os trusted commands)",
        ("features/ai/harness/approval_coordinator.py", "_save_trusted_command"): "non-workspace (.code_os trusted commands)",
        ("features/ai/harness/approval_coordinator.py", "_remove_trusted_command"): "non-workspace (.code_os trusted commands)",
        ("features/ai/harness/checkpoint_manager.py", "_ensure_git_checkpoint"): "non-workspace (.gitignore creation in checkpoint repo)",
        ("features/ai/harness/checkpoint_manager.py", "undo_turn_files"): "pipeline-adapter (cleanup empty parent directories on undo)",
        ("features/ai/harness/mutation_pipeline.py", "stage_apply"): "pipeline-internal (S4 atomic disk execution engine)",
        ("features/ai/harness/mutation_pipeline.py", "stage_rollback"): "pipeline-internal (S6 exact byte restoration engine)",
        ("features/ai/harness/mutation_pipeline.py", "apply_mutations"): "pipeline-internal (commit trash cleanup)",
        ("features/ai/harness/mutation_pipeline.py", "_cleanup_stale_trash"): "pipeline-internal (stale crash trash cleanup)",
        ("features/ai/indexing/code_intelligence.py", "_extract_style_conventions"): "non-workspace (.code_os style cache)",
        ("features/ai/marathon/marathon_service.py", "_state_file_path"): "non-workspace (.code_os marathon state)",
        ("features/ai/marathon/marathon_service.py", "save_state"): "non-workspace (.code_os marathon state)",
        ("features/ai/marathon/marathon_service.py", "delete_state_file"): "non-workspace (.code_os marathon state)",
        ("features/ai/memory/memory_service.py", "_get_memory_collection"): "non-workspace (.code_os memory dir)",
        ("features/ai/providers/catalog.py", "_get_sqlite_connection"): "non-workspace (.code_os provider catalog db)",
        ("features/ai/rag/vector_index_service.py", "init_vector_store"): "non-workspace (chroma vector store)",
        ("features/ai/refactoring/verify_service.py", "verify_refactor_safety"): "non-workspace (isolated temp sandbox dir)",
        ("features/ai/sandbox/executor.py", "_launch_windows_sandbox"): "non-workspace (isolated temp sandbox config)",
        ("features/ai/voice/tts_service.py", "speak"): "non-workspace (tts audio cache)",
        ("features/ai/voice/whisper_stt_service.py", "init_whisper"): "non-workspace (whisper models cache)",
        ("features/automation/browser_controller.py", "profile_path"): "non-workspace (browser profile dir)",
        ("features/automation/browser_controller.py", "screenshots_dir"): "non-workspace (browser screenshots dir)",
        ("features/automation/browser_controller.py", "trust_browser"): "non-workspace (browser trace logs)",
        ("features/automation/computer_controller.py", "audit_dir"): "non-workspace (automation audit dir)",
        ("features/git/github_auth.py", "validate_and_store_token"): "non-workspace (github auth token store)",
        ("features/git/github_service.py", "push_current_branch"): "non-workspace (git credential helper store)",
        ("features/terminal/run_service.py", "kill_run_process"): "non-workspace (terminal pty temp buffers)",
        ("features/terminal/run_service.py", "run_file_stream"): "non-workspace (terminal pty temp buffers)",
    }

    unrouted = []
    total_calls = 0
    for p in sorted(app_dir.rglob("*.py")):
        rel = p.relative_to(app_dir).as_posix()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        v = FunctionVisitor()
        v.visit(tree)
        for lineno, fn, prim in v.calls:
            total_calls += 1
            key = (rel, fn)
            if key not in ALLOWED_FUNCTIONS:
                unrouted.append(f"{rel}:{lineno} in {fn}(): {prim}")

    assert unrouted == [], f"Found unrouted workspace write primitives:\n" + "\n".join(unrouted)


def test_prose_rejection_empty_original_rejected():
    """Prove that empty or whitespace original cannot be replaced with conversational prose into a .ts file."""
    from app.features.ai.harness.content_integrity import validate_language_syntax
    conversational_text = "Here is the code you requested to handle authentication.\n"
    
    # 1. Empty original -> REJECTED
    ok, err = validate_language_syntax("auth.ts", conversational_text, original_content="")
    assert ok is False
    assert "conversational prose" in err

    # Whitespace-only original -> REJECTED
    ok_ws, err_ws = validate_language_syntax("auth.ts", conversational_text, original_content="   \n\t  ")
    assert ok_ws is False
    assert "conversational prose" in err_ws

    # None original -> REJECTED
    ok_none, err_none = validate_language_syntax("auth.ts", conversational_text, original_content=None)
    assert ok_none is False
    assert "conversational prose" in err_none


def test_prose_rejection_todo_stub_original_rejected():
    """Prove that comment stubs like '// TODO\\n' cannot be replaced with conversational prose."""
    from app.features.ai.harness.content_integrity import validate_language_syntax
    conversational_text = "Here is the implementation of the user service.\n"

    # 2. original="// TODO\n" -> REJECTED
    ok, err = validate_language_syntax("service.ts", conversational_text, original_content="// TODO\n")
    assert ok is False
    assert "conversational prose" in err

    # Block comment stub -> REJECTED
    ok_block, err_block = validate_language_syntax("service.ts", conversational_text, original_content="/* TODO: write code */\n")
    assert ok_block is False
    assert "conversational prose" in err_block


def test_prose_rejection_version_stub_allowed():
    """Prove that legacy staging version stubs ('version 1\\n' -> 'version 2\\n') remain allowed,
    while prose smuggling into version stubs is strictly blocked.
    """
    from app.features.ai.harness.content_integrity import validate_language_syntax

    # 3. original="version 1\n" + "version 2\n" -> ALLOWED
    ok, err = validate_language_syntax("stg_file.ts", "version 2\n", original_content="version 1\n")
    assert ok is True
    assert err == ""

    # Smuggle attempt: original="version 1\n" + conversational prose -> REJECTED
    smuggle_text = "Here is the updated version with bug fixes and improvements.\n"
    ok_smuggle, err_smuggle = validate_language_syntax("stg_file.ts", smuggle_text, original_content="version 1\n")
    assert ok_smuggle is False
    assert "conversational prose" in err_smuggle

    # Real code replaced with version stub -> REJECTED (original had code)
    ok_code, err_code = validate_language_syntax("real.ts", "version 2\n", original_content="const active = true;\n")
    assert ok_code is False
    assert "conversational prose" in err_code


def test_safe_write_file_has_zero_production_callers():
    """Prove that safe_write_file in app.core.paths has zero production callers anywhere in backend/app."""
    import ast
    backend_app_dir = Path(__file__).resolve().parent.parent / "app"
    matches = []
    for py_file in backend_app_dir.rglob("*.py"):
        if py_file.name == "paths.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "safe_write_file":
                matches.append(f"{py_file.relative_to(backend_app_dir)}:{node.lineno}")
            elif isinstance(node, ast.Attribute) and node.attr == "safe_write_file":
                matches.append(f"{py_file.relative_to(backend_app_dir)}:{node.lineno}")

    assert matches == [], f"Found unexpected callers of safe_write_file in production code:\n" + "\n".join(matches)
