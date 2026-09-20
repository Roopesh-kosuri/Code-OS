"""
test_phase12_6_part1_5_security_patch.py — Security Containment & Undo Invalidation Test Suite.

Verifies:
1. Directory traversal containment across all 5 write paths.
2. Multi-file atomicity (zero writes if any path escapes).
3. Legit in-workspace paths continue to work across all 5 sites.
4. Synchronous symbol index invalidation on turn undo (restore and delete).
"""
import os
import subprocess
import pytest
from pathlib import Path
from fastapi import HTTPException

from app.features.ai.cicd.cicd_routes import save_endpoint, SavePipelineRequest
from app.features.ai.ghost_text.ghost_text_service import (
    register_editor,
    stage_ghost_text,
    accept_ghost_text,
    clear_all_editors,
)
from app.features.ai.refactoring.refactor_routes import apply_refactoring_changes, ApplyRequest
from app.features.ai.security.fix_service import apply_fix
from app.features.ai.staging.staging_review_service import (
    stage_files_for_review,
    approve_files,
    apply_approved_changes,
    clear_staged_changes,
)
from app.features.ai.harness.checkpoint_manager import undo_turn_files
from app.features.ai.harness.symbol_index import (
    index_file,
    _symbol_index,
    clear_symbol_index,
)


@pytest.fixture(autouse=True)
def cleanup_registries():
    clear_all_editors()
    clear_staged_changes()
    clear_symbol_index()
    yield
    clear_all_editors()
    clear_staged_changes()
    clear_symbol_index()


# ─── TRAVERSAL TESTS ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cicd_save_rejects_traversal_writes_nothing(tmp_path: Path):
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()

    sentinel = outside / "sentinel.yml"
    original_bytes = b"safe: true\nversion: 1\n"
    sentinel.write_bytes(original_bytes)

    req = SavePipelineRequest(
        workspace=str(ws),
        yaml_content="malicious: true",
        file_path="../outside/sentinel.yml",
    )

    with pytest.raises(HTTPException) as exc_info:
        await save_endpoint(req)

    assert exc_info.value.status_code == 403
    assert "path_outside_workspace" in exc_info.value.detail
    assert sentinel.read_bytes() == original_bytes


def test_ghost_text_accept_rejects_absolute_path_outside_workspace(tmp_path: Path):
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()

    sentinel = outside / "sentinel.txt"
    original_bytes = b"important outside file content"
    sentinel.write_bytes(original_bytes)

    editor_id = "editor_traversal"
    register_editor(workspace=str(ws), file_path=str(sentinel), editor_id=editor_id)
    stage_ghost_text(
        editor_id=editor_id,
        file_path=str(sentinel),
        original="important outside file content",
        updated="corrupted outside content",
        workspace=str(ws),
        job_id="job_gt_bad",
    )

    res = accept_ghost_text(editor_id)
    assert res.get("status") == "error"
    assert "path_outside_workspace" in res.get("error", "")
    assert sentinel.read_bytes() == original_bytes


def test_ghost_text_accept_still_accepts_path_inside_workspace(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    target = ws / "module.py"
    target.write_text("def run(): pass\n", encoding="utf-8")

    editor_id = "editor_legit"
    register_editor(workspace=str(ws), file_path=str(target), editor_id=editor_id)
    stage_ghost_text(
        editor_id=editor_id,
        file_path=str(target),
        original="def run(): pass\n",
        updated="def run(): return 42\n",
        workspace=str(ws),
        job_id="job_gt_ok",
    )

    res = accept_ghost_text(editor_id)
    assert res.get("status") in ("accepted", "applied")
    assert target.read_text(encoding="utf-8") == "def run(): return 42\n"


@pytest.mark.asyncio
async def test_refactor_apply_rejects_traversal_writes_nothing(tmp_path: Path):
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()

    sentinel = outside / "sentinel.py"
    original_bytes = b"# pristine external library\n"
    sentinel.write_bytes(original_bytes)

    req = ApplyRequest(
        workspace=str(ws),
        changes=[
            {"file": "../outside/sentinel.py", "updated_content": "# hacked"}
        ],
        verified=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await apply_refactoring_changes(req)

    assert exc_info.value.status_code == 403
    assert "path_outside_workspace" in exc_info.value.detail
    assert sentinel.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_refactor_apply_one_bad_path_rejects_whole_request_zero_writes(tmp_path: Path):
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()

    legit_file = ws / "legit.py"
    legit_original = "print('untouched')\n"
    legit_file.write_text(legit_original, encoding="utf-8")

    sentinel = outside / "sentinel.py"
    original_bytes = b"# sentinel\n"
    sentinel.write_bytes(original_bytes)

    req = ApplyRequest(
        workspace=str(ws),
        changes=[
            {"file": "legit.py", "updated_content": "print('modified')\n"},
            {"file": "../outside/sentinel.py", "updated_content": "# hacked\n"},
        ],
        verified=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await apply_refactoring_changes(req)

    assert exc_info.value.status_code == 403
    assert "path_outside_workspace" in exc_info.value.detail
    # Zero writes: legit file MUST NOT have been modified
    assert legit_file.read_text(encoding="utf-8") == legit_original
    assert sentinel.read_bytes() == original_bytes


def test_security_fix_rejects_traversal_writes_nothing(tmp_path: Path):
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()

    sentinel = outside / "sentinel.py"
    original_bytes = b"SELECT * FROM users\n"
    sentinel.write_bytes(original_bytes)

    patch_diff = (
        "--- a/../outside/sentinel.py\n"
        "+++ b/../outside/sentinel.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-SELECT * FROM users\n"
        "+SELECT * FROM users WHERE id = %s\n"
    )

    with pytest.raises(ValueError) as exc_info:
        apply_fix("vuln_outside", patch_diff, workspace=str(ws))

    assert "path_outside_workspace" in str(exc_info.value)
    assert sentinel.read_bytes() == original_bytes


def test_staging_apply_rejects_traversal_delete_and_write(tmp_path: Path):
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()

    sentinel_write = outside / "write_target.txt"
    orig_write = b"original write content\n"
    sentinel_write.write_bytes(orig_write)

    sentinel_del = outside / "delete_target.txt"
    orig_del = b"must not be deleted\n"
    sentinel_del.write_bytes(orig_del)

    job_id = "job_staging_traversal"
    files = [
        {"path": "../outside/write_target.txt", "original": "original write content\n", "updated": "overwritten\n"},
        {"path": "../outside/delete_target.txt", "original": "must not be deleted\n", "updated": ""},
    ]
    stage_files_for_review(job_id, str(ws), files)
    approve_files(job_id, ["../outside/write_target.txt", "../outside/delete_target.txt"])

    res = apply_approved_changes(job_id)
    assert res["success"] is False
    assert "path_outside_workspace" in res["error"]
    assert sentinel_write.read_bytes() == orig_write
    assert sentinel_del.exists()
    assert sentinel_del.read_bytes() == orig_del


def test_staging_apply_one_bad_path_rejects_whole_request_zero_writes(tmp_path: Path):
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()

    good_file = ws / "good.txt"
    orig_good = "good untouched\n"
    good_file.write_text(orig_good, encoding="utf-8")

    sentinel = outside / "sentinel.txt"
    orig_sentinel = b"sentinel content\n"
    sentinel.write_bytes(orig_sentinel)

    job_id = "job_staging_partial"
    files = [
        {"path": "good.txt", "original": "good untouched\n", "updated": "good modified\n"},
        {"path": "../outside/sentinel.txt", "original": "sentinel content\n", "updated": "sentinel hacked\n"},
    ]
    stage_files_for_review(job_id, str(ws), files)
    approve_files(job_id, ["good.txt", "../outside/sentinel.txt"])

    res = apply_approved_changes(job_id)
    assert res["success"] is False
    assert "path_outside_workspace" in res["error"]
    # Zero writes to good_file
    assert good_file.read_text(encoding="utf-8") == orig_good
    assert sentinel.read_bytes() == orig_sentinel


@pytest.mark.asyncio
async def test_legit_relative_paths_still_work_at_all_five_sites(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    # 1. T1.1: cicd save
    req_cicd = SavePipelineRequest(
        workspace=str(ws),
        yaml_content="name: Test\n",
        file_path=".github/workflows/test.yml",
    )
    res_cicd = await save_endpoint(req_cicd)
    assert res_cicd["success"] is True
    assert (ws / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8") == "name: Test\n"

    # 2. T1.2: ghost text
    gt_file = ws / "gt_file.py"
    gt_file.write_text("initial\n", encoding="utf-8")
    register_editor(workspace=str(ws), file_path="gt_file.py", editor_id="ed_1")
    stage_ghost_text("ed_1", "gt_file.py", "initial\n", "accepted\n", str(ws), "job_gt")
    res_gt = accept_ghost_text("ed_1")
    assert res_gt.get("status") in ("accepted", "applied")
    assert gt_file.read_text(encoding="utf-8") == "accepted\n"

    # 3. T1.3: refactor
    ref_file = ws / "ref_file.py"
    ref_file.write_text("def a(): pass\n", encoding="utf-8")
    req_ref = ApplyRequest(
        workspace=str(ws),
        changes=[{"file": "ref_file.py", "updated_content": "def b(): pass\n"}],
        verified=True,
    )
    res_ref = await apply_refactoring_changes(req_ref)
    assert res_ref["success"] is True
    assert ref_file.read_text(encoding="utf-8") == "def b(): pass\n"

    # 4. T1.4: security fix
    sec_file = ws / "sec_file.py"
    sec_file.write_text("query = 'raw'\n", encoding="utf-8")
    patch = (
        "--- a/sec_file.py\n"
        "+++ b/sec_file.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-query = 'raw'\n"
        "+query = 'param'\n"
    )
    success_sec = apply_fix("vuln_local", patch, workspace=str(ws))
    assert success_sec is True
    assert sec_file.read_text(encoding="utf-8") == "query = 'param'\n"

    # 5. T1.5: staging apply
    stg_file = ws / "stg_file.ts"
    stg_file.write_text("version 1\n", encoding="utf-8")
    job_id = "job_stg_legit"
    stage_files_for_review(job_id, str(ws), [{"path": "stg_file.ts", "original": "version 1\n", "updated": "version 2\n"}])
    approve_files(job_id, ["stg_file.ts"])
    res_stg = apply_approved_changes(job_id)
    assert res_stg["success"] is True
    assert stg_file.read_text(encoding="utf-8") == "version 2\n"


# ─── UNDO INVALIDATION TESTS ──────────────────────────────────────────────────

def _init_git_repo(ws_path: Path) -> str:
    """Helper to initialize a real git repo and make an initial commit."""
    subprocess.run(["git", "init"], cwd=str(ws_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(ws_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(ws_path), check=True, capture_output=True)

    base_file = ws_path / "tracked.py"
    base_file.write_text("def base_symbol(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(ws_path), check=True, capture_output=True)
    res = subprocess.run(["git", "commit", "-m", "initial checkpoint"], cwd=str(ws_path), check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ws_path), check=True, capture_output=True, text=True)
    return commit.stdout.strip()


def test_undo_turn_invalidates_index_for_restored_files(tmp_path: Path):
    ws = tmp_path / "repo"
    ws.mkdir()
    commit_hash = _init_git_repo(ws)

    tracked_file = ws / "tracked.py"
    # Index initial state
    syms_before = index_file(tracked_file, workspace=str(ws))
    assert any(s.name == "base_symbol" for s in syms_before)
    # Check cache has the file
    resolved_key = str(tracked_file.resolve())
    assert resolved_key in _symbol_index._cache

    # Modify file with new symbol
    tracked_file.write_text("def modified_symbol(): pass\n", encoding="utf-8")
    # Manually re-index to update cache to reflect modified state
    _symbol_index.invalidate(tracked_file)
    syms_modified = index_file(tracked_file, workspace=str(ws))
    assert any(s.name == "modified_symbol" for s in syms_modified)
    assert resolved_key in _symbol_index._cache

    # Undo turn files
    ok, msg, restored = undo_turn_files(str(ws), commit_hash, ["tracked.py"])
    assert ok is True
    assert "tracked.py" in restored

    # Assert symbol index cache was synchronously invalidated
    assert resolved_key not in _symbol_index._cache
    # Re-indexing must reflect the restored base symbol, NOT modified symbol
    fresh_syms = index_file(tracked_file, workspace=str(ws))
    assert any(s.name == "base_symbol" for s in fresh_syms)
    assert not any(s.name == "modified_symbol" for s in fresh_syms)


def test_undo_turn_invalidates_index_for_deleted_new_files(tmp_path: Path):
    ws = tmp_path / "repo"
    ws.mkdir()
    commit_hash = _init_git_repo(ws)

    new_file = ws / "new_module.py"
    new_file.write_text("def new_feature_symbol(): pass\n", encoding="utf-8")

    # Index new file
    syms = index_file(new_file, workspace=str(ws))
    assert any(s.name == "new_feature_symbol" for s in syms)
    resolved_key = str(new_file.resolve())
    assert resolved_key in _symbol_index._cache

    # Undo turn files (new file did not exist in checkpoint, so git show fails -> unlinked)
    ok, msg, restored = undo_turn_files(str(ws), commit_hash, ["new_module.py"])
    assert ok is True
    assert not new_file.exists()

    # Assert symbol index cache was synchronously invalidated
    assert resolved_key not in _symbol_index._cache
    syms_after = index_file(new_file, workspace=str(ws))
    assert len(syms_after) == 0
