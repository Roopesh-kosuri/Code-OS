"""
test_staging_review.py — Unit and integration tests for Smart Staging / PR View.

Required Tests:
1. test_get_staged_changes_summary_returns_all_files
2. test_get_file_diff_returns_monaco_format
3. test_approve_files_marks_selected
4. test_reject_files_discards_selected
5. test_approve_chunk_granular_control
6. test_apply_approved_changes_writes_to_disk
"""

import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.features.ai.staging.staging_review_service import (
    stage_files_for_review,
    get_staged_changes_summary,
    get_file_diff,
    approve_files,
    reject_files,
    approve_chunk,
    reject_chunk,
    apply_approved_changes,
    clear_staged_changes,
)


@pytest.fixture(autouse=True)
def clean_staging():
    clear_staged_changes()
    yield
    clear_staged_changes()


def test_get_staged_changes_summary_returns_all_files():
    """Verify get_staged_changes_summary returns all files with correct status and chunk format."""
    job_id = "job_summary_test"
    workspace = "/test/workspace"
    files = [
        {
            "path": "src/new_feature.ts",
            "original": "",
            "updated": "export const a = 1;\nexport const b = 2;\n",
        },
        {
            "path": "src/utils.ts",
            "original": "function helper() {\n  return 1;\n}\n",
            "updated": "function helper() {\n  return 2;\n}\n// added comment\n",
        },
        {
            "path": "src/deprecated.ts",
            "original": "export const oldStuff = true;\n",
            "updated": "",
        },
    ]

    summary = stage_files_for_review(job_id, workspace, files)
    assert summary["total_files"] == 3
    assert len(summary["files"]) == 3

    file_map = {f["path"]: f for f in summary["files"]}

    # Added file
    added = file_map["src/new_feature.ts"]
    assert added["status"] == "added"
    assert added["lines_added"] == 2
    assert added["lines_removed"] == 0
    assert any(c["type"] == "insert" for c in added["chunks"])

    # Modified file
    modified = file_map["src/utils.ts"]
    assert modified["status"] == "modified"
    assert modified["lines_added"] > 0
    assert any(c["type"] == "context" for c in modified["chunks"])

    # Deleted file
    deleted = file_map["src/deprecated.ts"]
    assert deleted["status"] == "deleted"
    assert deleted["lines_removed"] == 1
    assert any(c["type"] == "delete" for c in deleted["chunks"])


def test_get_file_diff_returns_monaco_format():
    """Verify get_file_diff returns full diff with Monaco-compatible red/green lines and line numbers."""
    job_id = "job_diff_test"
    workspace = "/test/workspace"
    file_path = "src/calculator.ts"
    original = "line 1\nline 2 to delete\nline 3\n"
    updated = "line 1\nline 2 replaced\nline 3\nline 4 added\n"

    stage_files_for_review(job_id, workspace, [{"path": file_path, "original": original, "updated": updated}])

    diff_data = get_file_diff(job_id, file_path)
    assert diff_data["job_id"] == job_id
    assert diff_data["path"] == file_path
    assert diff_data["status"] == "modified"
    assert "lines" in diff_data
    assert len(diff_data["lines"]) > 0

    lines = diff_data["lines"]
    has_insert = any(l["type"] == "insert" and l["new_line_number"] is not None for l in lines)
    has_delete = any(l["type"] == "delete" and l["orig_line_number"] is not None for l in lines)
    has_context = any(l["type"] == "context" and l["orig_line_number"] is not None and l["new_line_number"] is not None for l in lines)

    assert has_insert, "Diff must contain insertion lines with new line numbers"
    assert has_delete, "Diff must contain deletion lines with original line numbers"
    assert has_context, "Diff must contain context lines"
    assert "diff_text" in diff_data and "---" in diff_data["diff_text"]


def test_approve_files_marks_selected():
    """Verify approve_files marks selected files and their diff chunks as approved."""
    job_id = "job_approve_test"
    workspace = "/test/workspace"
    files = [
        {"path": "file1.ts", "original": "a = 1", "updated": "a = 2"},
        {"path": "file2.ts", "original": "b = 1", "updated": "b = 2"},
        {"path": "file3.ts", "original": "c = 1", "updated": "c = 2"},
    ]
    stage_files_for_review(job_id, workspace, files)

    # Approve file1 and file3
    res = approve_files(job_id, ["file1.ts", "file3.ts"])
    assert res["success"] is True
    assert set(res["approved_files"]) == {"file1.ts", "file3.ts"}

    summary = get_staged_changes_summary(job_id)
    assert summary["approved_count"] == 2
    file_map = {f["path"]: f for f in summary["files"]}
    assert file_map["file1.ts"]["approved"] is True
    assert file_map["file2.ts"]["approved"] is False
    assert file_map["file3.ts"]["approved"] is True


def test_reject_files_discards_selected():
    """Verify reject_files marks selected files as rejected and unapproved."""
    job_id = "job_reject_test"
    workspace = "/test/workspace"
    files = [
        {"path": "file1.ts", "original": "a = 1", "updated": "a = 2"},
        {"path": "file2.ts", "original": "b = 1", "updated": "b = 2"},
    ]
    stage_files_for_review(job_id, workspace, files)

    # Initially approve file1
    approve_files(job_id, ["file1.ts"])
    assert get_staged_changes_summary(job_id)["approved_count"] == 1

    # Now reject file1
    res = reject_files(job_id, ["file1.ts"])
    assert res["success"] is True
    assert "file1.ts" in res["rejected_files"]

    summary = get_staged_changes_summary(job_id)
    file_map = {f["path"]: f for f in summary["files"]}
    assert file_map["file1.ts"]["approved"] is False
    assert summary["approved_count"] == 0


def test_approve_chunk_granular_control():
    """Verify approving and rejecting individual diff chunks within a file."""
    job_id = "job_chunk_test"
    workspace = "/test/workspace"
    file_path = "src/service.ts"
    original = "start\nblock 1\nmiddle\nblock 2\nend"
    updated = "start\nblock 1 modified\nmiddle\nblock 2 modified\nend"

    stage_files_for_review(job_id, workspace, [{"path": file_path, "original": original, "updated": updated}])

    diff_data = get_file_diff(job_id, file_path)
    diff_chunks = [c for c in diff_data["chunks"] if c["type"] in ("insert", "delete")]
    assert len(diff_chunks) >= 2

    c1_idx = diff_chunks[0]["index"]
    c2_idx = diff_chunks[1]["index"]

    # Approve chunk 1
    res1 = approve_chunk(job_id, file_path, c1_idx)
    assert res1["success"] is True
    assert res1["approved"] is True

    # Reject chunk 2
    res2 = reject_chunk(job_id, file_path, c2_idx)
    assert res2["success"] is True
    assert res2["approved"] is False

    # Check updated chunks in diff
    updated_diff = get_file_diff(job_id, file_path)
    chunk_map = {c["index"]: c for c in updated_diff["chunks"]}
    assert chunk_map[c1_idx]["approved"] is True
    assert chunk_map[c2_idx]["approved"] is False


def test_apply_approved_changes_writes_to_disk(tmp_path: Path):
    """Verify apply_approved_changes writes all approved files/chunks to disk and discards rejected ones."""
    job_id = "job_apply_test"
    workspace = str(tmp_path)

    # Prepare existing file on disk
    file1 = tmp_path / "app.ts"
    file1.write_text("console.log('original v1');\n", encoding="utf-8")

    file2 = tmp_path / "config.json"
    file2.write_text('{"env": "dev"}\n', encoding="utf-8")

    file3_new = tmp_path / "new_module.ts"

    files = [
        {"path": "app.ts", "original": "console.log('original v1');\n", "updated": "console.log('updated v2');\n"},
        {"path": "config.json", "original": '{"env": "dev"}\n', "updated": '{"env": "prod"}\n'},
        {"path": "new_module.ts", "original": "", "updated": "export const isNew = true;\n"},
    ]
    stage_files_for_review(job_id, workspace, files)

    # Approve app.ts and new_module.ts, reject config.json
    approve_files(job_id, ["app.ts", "new_module.ts"])
    reject_files(job_id, ["config.json"])

    # Apply changes
    result = apply_approved_changes(job_id)
    assert result["success"] is True
    assert "app.ts" in result["applied_files"]
    assert "new_module.ts" in result["applied_files"]
    assert "config.json" in result["rejected_files"]

    # Verify disk contents
    assert file1.read_text(encoding="utf-8") == "console.log('updated v2');\n"
    assert file3_new.exists()
    assert file3_new.read_text(encoding="utf-8") == "export const isNew = true;\n"

    # Rejected file remains unchanged on disk
    assert file2.read_text(encoding="utf-8") == '{"env": "dev"}\n'


@pytest.mark.asyncio
async def test_staging_routes_api_full_flow(tmp_path: Path):
    """Verify complete HTTP API flow for /api/staging endpoints."""
    from app.core.auth import get_token
    headers = {"Authorization": f"Bearer {get_token()}"}
    transport = ASGITransport(app=app)

    job_id = "job_api_test"
    workspace = str(tmp_path)
    test_file = tmp_path / "api_test.ts"
    test_file.write_text("old text\n", encoding="utf-8")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Stage files
        stage_resp = await client.post(
            "/api/staging/stage",
            json={
                "job_id": job_id,
                "workspace": workspace,
                "files": [
                    {"path": "api_test.ts", "original": "old text\n", "updated": "new text\n"},
                    {"path": "unwanted.ts", "original": "stay\n", "updated": "change\n"},
                ],
            },
            headers=headers,
        )
        assert stage_resp.status_code == 200

        # 2. Get summary
        summary_resp = await client.get(f"/api/staging/summary?job_id={job_id}", headers=headers)
        assert summary_resp.status_code == 200
        summary_data = summary_resp.json()
        assert summary_data["total_files"] == 2

        # 3. Get diff for file
        diff_resp = await client.get(f"/api/staging/diff/{job_id}/api_test.ts", headers=headers)
        assert diff_resp.status_code == 200
        diff_data = diff_resp.json()
        assert len(diff_data["lines"]) > 0

        # 4. Approve file
        appr_resp = await client.post(
            "/api/staging/approve-files",
            json={"job_id": job_id, "file_paths": ["api_test.ts"]},
            headers=headers,
        )
        assert appr_resp.status_code == 200
        assert "api_test.ts" in appr_resp.json()["approved_files"]

        # 5. Reject other file
        rej_resp = await client.post(
            "/api/staging/reject-files",
            json={"job_id": job_id, "file_paths": ["unwanted.ts"]},
            headers=headers,
        )
        assert rej_resp.status_code == 200

        # 6. Apply approved
        apply_resp = await client.post(
            "/api/staging/apply",
            json={"job_id": job_id},
            headers=headers,
        )
        assert apply_resp.status_code == 200
        assert "api_test.ts" in apply_resp.json()["applied_files"]

        # Verify disk
        assert test_file.read_text(encoding="utf-8") == "new text\n"
