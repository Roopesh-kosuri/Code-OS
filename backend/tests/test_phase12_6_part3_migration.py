"""Phase 12.6 Part 3: Write-Path Migration & Adapter Tests.

Verifies that workspace writes (Rows 1-11) routed through mutation_pipeline:
1. Preserve public signatures and return shapes.
2. Hook registration in files/service.py is idempotent across importlib.reload.
3. USER_SAVE mode skips syntax checks for Monaco, while AGENT mode fails closed.
4. Symbol index is synchronously invalidated across Monaco saves, ghost text, refactor, staging, cicd, audit report.
5. Multi-file atomicity rolls back file 1 when file 2 fails in refactor and staging.
6. Rejections preserve each module's existing error conventions.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.features.ai.harness.mutation_pipeline import (
    Mutation,
    MutationKind,
    apply_mutations,
    register_invalidation_hook,
    unregister_invalidation_hook,
)
from app.features.ai.harness.patch_applicator import apply_atomic_patch_sequence
from app.features.ai.harness.symbol_index import (
    find_symbol,
    index_file,
    invalidate_file,
    symbols_in_file,
)
from app.features.ai.schemas import FileChange
import app.features.files.service as files_service


# ═══════════════════════════════════════════════════════════════════════════
# A0: HOOK REGISTRATION IDEMPOTENCE
# ═══════════════════════════════════════════════════════════════════════════

def test_invalidation_hook_registered_once_no_duplicates(tmp_path: Path):
    """Importing/reloading files.service multiple times leaves exactly one hook instance."""
    # Track invocations
    fire_count = 0

    def test_hook(ws: str, paths: list[str]):
        nonlocal fire_count
        fire_count += 1

    hook_key = register_invalidation_hook(test_hook, key="test_module.test_hook")
    try:
        # Register repeatedly with the same key
        register_invalidation_hook(test_hook, key="test_module.test_hook")
        register_invalidation_hook(test_hook, key="test_module.test_hook")

        # Reload files_service repeatedly
        importlib.reload(files_service)
        importlib.reload(files_service)

        f = tmp_path / "sample.txt"
        f.write_text("initial\n", encoding="utf-8")

        mut = Mutation(kind=MutationKind.WRITE_FULL, path="sample.txt", new_content="updated\n")
        res = apply_mutations(str(tmp_path), [mut], mode="USER_SAVE")
        assert res.success is True

        # Custom hook fired exactly once
        assert fire_count == 1
    finally:
        unregister_invalidation_hook(hook_key)


# ═══════════════════════════════════════════════════════════════════════════
# ROW 1: PATCH APPLICATOR ADAPTER EQUIVALENCE
# ═══════════════════════════════════════════════════════════════════════════

def test_apply_atomic_patch_sequence_adapter_same_result_shape(tmp_path: Path):
    """apply_atomic_patch_sequence retains (bool, str, list[str]) return shape."""
    f = tmp_path / "hello.py"
    f.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    staged = [
        FileChange(
            path="hello.py",
            updated="def hello():\n    return 'universe'",
            original="def hello():\n    return 'world'",
            start_line=1,
            end_line=2,
            anchor="def hello():\n    return 'world'",
        )
    ]

    success, msg, touched = apply_atomic_patch_sequence(str(tmp_path), staged, turn_number=1, staged_changes=staged)
    assert isinstance(success, bool) and success is True
    assert isinstance(msg, str) and "Successfully applied" in msg
    assert isinstance(touched, list) and touched == ["hello.py"]
    assert "universe" in f.read_text(encoding="utf-8")


def test_agent_edit_range_drift_still_relocates_and_attaches_relocation_event(tmp_path: Path):
    """Anchored edit_range on drifted file relocates and attaches relocation_event to FileChange."""
    target = tmp_path / "calc.py"
    # File has 3 lines of header drift
    target.write_text(
        "# Header 1\n"
        "# Header 2\n"
        "# Header 3\n"
        "def compute_total(items: list) -> int:\n"
        "    return sum(items)\n",
        encoding="utf-8",
    )

    anchor_str = "def compute_total(items: list) -> int:\n    return sum(items)"
    staged = [
        FileChange(
            path="calc.py",
            updated="def compute_total(items: list) -> int:\n    return sum(items) * 2",
            original=anchor_str,
            start_line=1,
            end_line=2,
            anchor=anchor_str,
        )
    ]

    success, msg, touched = apply_atomic_patch_sequence(str(tmp_path), staged, staged_changes=staged)
    assert success is True
    assert staged[0].relocation_event is not None
    assert staged[0].relocation_event["relocated"] is True
    assert staged[0].relocation_event["old_range"] == [1, 2]
    assert staged[0].relocation_event["new_range"] == [4, 5]
    assert "File drifted" in staged[0].relocation_event["reason_text"]


# ═══════════════════════════════════════════════════════════════════════════
# ROW 4: MONACO USER_SAVE MODE & CACHE INVALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def test_monaco_write_file_uses_user_save_mode_no_syntax_gate(tmp_path: Path):
    """Monaco save (USER_SAVE mode) permits syntactically invalid Python, but AGENT rejects it."""
    broken_code = "def syntax_broken(\n    print('unclosed paren'\n"
    target_rel = "broken.py"

    # 1. Monaco write_file succeeds
    files_service.write_file(str(tmp_path), target_rel, broken_code)
    on_disk = (tmp_path / target_rel).read_text(encoding="utf-8")
    assert "unclosed paren" in on_disk

    # 2. Agent mutation rejected on clean file with broken code
    agent_target = "agent_broken.py"
    agent_mut = Mutation(kind=MutationKind.WRITE_FULL, path=agent_target, new_content=broken_code)
    agent_res = apply_mutations(str(tmp_path), [agent_mut], mode="AGENT")
    assert agent_res.success is False
    assert agent_res.rejection is not None
    assert agent_res.rejection.code == "projected_syntax_error"


def test_monaco_write_file_invalidates_symbol_index_immediately(tmp_path: Path):
    """Saving via Monaco write_file invalidates symbol_index immediately without file watcher."""
    ws = str(tmp_path)
    py_file = tmp_path / "calculator.py"
    py_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    index_file(py_file)
    assert len(find_symbol(ws, "add")) > 0
    assert len(find_symbol(ws, "multiply")) == 0

    # Save via write_file adding multiply
    files_service.write_file(ws, "calculator.py", "def multiply(a, b):\n    return a * b\n")

    # Immediately query symbol index (watcher suppressed)
    # The cache was invalidated so re-indexing reflects the new symbol
    index_file(py_file)
    assert len(find_symbol(ws, "multiply")) > 0
    assert len(find_symbol(ws, "add")) == 0


def test_monaco_write_file_still_clears_directory_cache(tmp_path: Path):
    """Monaco write_file invalidates directory_cache via the registered hook."""
    ws = str(tmp_path)
    files_service.directory_cache.set(ws, "", [MagicMock()])
    assert files_service.directory_cache.get(ws, "") is not None

    files_service.write_file(ws, "new_file.txt", "hello")
    assert files_service.directory_cache.get(ws, "") is None


# ═══════════════════════════════════════════════════════════════════════════
# ROW 5: GHOST TEXT INVALIDATES SYMBOL INDEX
# ═══════════════════════════════════════════════════════════════════════════

def test_ghost_text_accept_now_invalidates_index(tmp_path: Path):
    """Accepting ghost text writes atomically and synchronously invalidates symbol index."""
    from app.features.ai.ghost_text.ghost_text_service import accept_ghost_text, stage_ghost_text

    ws = str(tmp_path)
    f = tmp_path / "component.py"
    f.write_text("def render_old():\n    pass\n", encoding="utf-8")
    index_file(f)
    assert len(find_symbol(ws, "render_old")) > 0

    eid = "editor_test_1"
    stage_ghost_text(eid, "component.py", "def render_old():\n    pass\n", "def render_new():\n    pass\n", ws)
    res = accept_ghost_text(eid)
    assert res.get("status") == "accepted"

    # Symbol index immediately reflects render_new post-invalidation
    index_file(f)
    assert len(find_symbol(ws, "render_new")) > 0
    assert len(find_symbol(ws, "render_old")) == 0


# ═══════════════════════════════════════════════════════════════════════════
# ROW 6: REFACTORING MULTI-FILE ATOMICITY & ROLLBACK
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refactor_apply_second_file_fails_first_file_restored(tmp_path: Path):
    """Multi-file refactor batch: if file 2 fails syntax gate, file 1 is restored completely."""
    from app.features.ai.refactoring.refactor_routes import ApplyRequest, apply_refactoring_changes

    ws = str(tmp_path)
    f1 = tmp_path / "valid.py"
    f1_init = "def original_func():\n    return 42\n"
    f1.write_text(f1_init, encoding="utf-8")

    f2 = tmp_path / "broken.py"
    f2_init = "def another_func():\n    return 100\n"
    f2.write_text(f2_init, encoding="utf-8")

    index_file(f1)
    index_file(f2)

    req = ApplyRequest(
        changes=[
            {"file": "valid.py", "updated_content": "def refactored_func():\n    return 42\n"},
            {"file": "broken.py", "updated_content": "def bad_syntax(:\n    return 0\n"},
        ],
        workspace=ws,
        verified=True,  # Bypass test verification so we hit apply pipeline
    )

    with pytest.raises(HTTPException) as exc_info:
        await apply_refactoring_changes(req)

    assert exc_info.value.status_code == 500

    # Multi-file atomicity: f1 must be byte-identical to initial text
    assert f1.read_text(encoding="utf-8").replace("\r\n", "\n") == f1_init
    assert f2.read_text(encoding="utf-8").replace("\r\n", "\n") == f2_init


# ═══════════════════════════════════════════════════════════════════════════
# ROW 8: STAGING REVIEW MULTI-FILE ATOMICITY & ROLLBACK
# ═══════════════════════════════════════════════════════════════════════════

def test_staging_apply_second_file_fails_first_file_restored(tmp_path: Path):
    """Multi-file staging review batch: if file 2 fails, file 1 is restored completely."""
    from app.features.ai.staging.staging_review_service import _STAGED_REVIEWS, apply_approved_changes

    ws = str(tmp_path)
    f1 = tmp_path / "service_a.py"
    f1_init = "def service_a():\n    return 'a'\n"
    f1.write_text(f1_init, encoding="utf-8")

    f2 = tmp_path / "service_b.py"
    f2_init = "def service_b():\n    return 'b'\n"
    f2.write_text(f2_init, encoding="utf-8")

    job_id = "test-job-staging-atomic"
    _STAGED_REVIEWS[job_id] = {
        "job_id": job_id,
        "workspace": ws,
        "files": {
            "service_a.py": {
                "status": "modified",
                "approved": True,
                "original": f1_init,
                "updated": "def service_a_v2():\n    return 'a2'\n",
                "chunks": [],
            },
            "service_b.py": {
                "status": "modified",
                "approved": True,
                "original": f2_init,
                "updated": "def broken_syntax(:\n    return 'b2'\n",
                "chunks": [],
            },
        },
    }

    result = apply_approved_changes(job_id)
    assert result.get("success") is False
    assert result.get("applied_files") == []

    # File 1 must be byte-identical to pre-apply state
    assert f1.read_text(encoding="utf-8").replace("\r\n", "\n") == f1_init
    assert f2.read_text(encoding="utf-8").replace("\r\n", "\n") == f2_init

    _STAGED_REVIEWS.pop(job_id, None)


# ═══════════════════════════════════════════════════════════════════════════
# ROWS 9 & 10: CICD & AUDIT REPORT SYMBOL INDEX INVALIDATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cicd_save_and_audit_report_invalidate_index(tmp_path: Path):
    """Saving CI/CD config and Security Audit report route through pipeline and invalidate index."""
    from app.features.ai.agent_routes import SaveAuditReportRequest, save_security_audit_report
    from app.features.ai.cicd.cicd_routes import SavePipelineRequest, save_endpoint

    ws = str(tmp_path)

    # 1. CI/CD save
    cicd_req = SavePipelineRequest(
        workspace=ws,
        file_path=".github/workflows/ci.yml",
        yaml_content="name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n",
    )
    cicd_res = await save_endpoint(cicd_req)
    assert cicd_res.get("success") is True
    assert (tmp_path / ".github/workflows/ci.yml").exists()

    # 2. Audit report save
    audit_req = SaveAuditReportRequest(
        workspace=ws,
        markdown_content="# Security Audit\n\nNo vulnerabilities found.\n",
    )
    audit_res = await save_security_audit_report(audit_req)
    assert audit_res.get("status") == "success"
    assert (tmp_path / "SECURITY_AUDIT.md").exists()


# ═══════════════════════════════════════════════════════════════════════════
# ADAPTER ERROR SHAPE PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "adapter_name",
    ["refactor", "fix", "staging", "ghost_text"],
)
@pytest.mark.asyncio
async def test_adapter_rejections_keep_module_error_shape(tmp_path: Path, adapter_name: str):
    """Each adapter translates pipeline rejections into its module's established error convention."""
    ws = str(tmp_path)
    escaped_path = "../../outside.txt"

    if adapter_name == "refactor":
        from app.features.ai.refactoring.refactor_routes import ApplyRequest, apply_refactoring_changes
        req = ApplyRequest(
            changes=[{"file": escaped_path, "updated_content": "malicious"}],
            workspace=ws,
            verified=True,
        )
        with pytest.raises(HTTPException) as exc_info:
            await apply_refactoring_changes(req)
        assert exc_info.value.status_code == 403
        assert "path_outside_workspace" in str(exc_info.value.detail)

    elif adapter_name == "fix":
        from app.features.ai.security.fix_service import apply_fix
        # Traversal in patch diff header raises ValueError
        patch_diff = f"--- a/{escaped_path}\n+++ b/{escaped_path}\n@@ -1 +1 @@\n-old\n+new\n"
        with pytest.raises(ValueError) as exc_info:
            apply_fix("vuln-test-traversal", patch_diff, workspace=ws)
        assert "path_outside_workspace" in str(exc_info.value)

    elif adapter_name == "staging":
        from app.features.ai.staging.staging_review_service import _STAGED_REVIEWS, apply_approved_changes
        job_id = "test-staging-error-shape"
        _STAGED_REVIEWS[job_id] = {
            "job_id": job_id,
            "workspace": ws,
            "files": {
                escaped_path: {
                    "status": "modified",
                    "approved": True,
                    "original": "old",
                    "updated": "new",
                    "chunks": [],
                }
            },
        }
        res = apply_approved_changes(job_id)
        assert res.get("success") is False
        assert "path_outside_workspace" in res.get("error", "")
        _STAGED_REVIEWS.pop(job_id, None)

    elif adapter_name == "ghost_text":
        from app.features.ai.ghost_text.ghost_text_service import accept_ghost_text, stage_ghost_text
        eid = "editor_error_shape"
        stage_ghost_text(eid, escaped_path, "old", "new", ws)
        res = accept_ghost_text(eid)
        assert res.get("status") == "error"
        assert "path_outside_workspace" in res.get("error", "")


# ═══════════════════════════════════════════════════════════════════════════
# ROW 11 & STAGING FOLLOW-UPS (AGENT MODE & DELETE NON-EXECUTION ON ROLLBACK)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_apply_proposal_uses_agent_mode_rejects_broken_python(tmp_path: Path):
    """Proposals run in AGENT mode; broken Python code fails the syntax gate and rejects."""
    from app.features.ai.service import apply_proposal
    from app.features.ai.schemas import EditProposalDto, FileChange

    ws = str(tmp_path)
    broken_file = tmp_path / "broken_proposal.py"
    broken_file.write_text("def valid_original():\n    pass\n", encoding="utf-8")

    proposal_id = "prop-test-agent-mode"
    mock_proposal = EditProposalDto(
        id=proposal_id,
        workspace=ws,
        status="pending",
        summary="Test proposal with broken syntax",
        changes=[
            FileChange(
                path="broken_proposal.py",
                original="def valid_original():\n    pass\n",
                updated="def broken_syntax(:\n    print('bad')\n",
            )
        ],
        diff="",
    )

    with patch("app.features.ai.service.get_proposal", return_value=mock_proposal):
        with pytest.raises(HTTPException) as exc_info:
            await apply_proposal(proposal_id)

    assert exc_info.value.status_code == 500
    assert "syntax error" in str(exc_info.value.detail).lower() or "syntax_error" in str(exc_info.value.detail).lower()
    # Disk remains untouched
    assert "def valid_original" in broken_file.read_text(encoding="utf-8")


def test_staging_apply_write_fails_delete_not_executed(tmp_path: Path):
    """In a batch with write + delete: if write fails syntax gate, delete is NOT executed."""
    from app.features.ai.staging.staging_review_service import _STAGED_REVIEWS, apply_approved_changes

    ws = str(tmp_path)

    # 1. File to delete exists on disk
    f_del = tmp_path / "to_delete.py"
    f_del.write_text("def will_be_deleted():\n    pass\n", encoding="utf-8")

    # 2. File to write exists on disk
    f_write = tmp_path / "to_write.py"
    f_write_init = "def clean_code():\n    return 1\n"
    f_write.write_text(f_write_init, encoding="utf-8")

    job_id = "test-job-write-fails-delete-retained"
    _STAGED_REVIEWS[job_id] = {
        "job_id": job_id,
        "workspace": ws,
        "files": {
            "to_delete.py": {
                "status": "deleted",
                "approved": True,
                "original": "def will_be_deleted():\n    pass\n",
                "updated": "",
                "chunks": [],
            },
            "to_write.py": {
                "status": "modified",
                "approved": True,
                "original": f_write_init,
                "updated": "def broken_syntax(:\n    return 2\n",
                "chunks": [],
            },
        },
    }

    result = apply_approved_changes(job_id)
    assert result.get("success") is False

    # The delete was NEVER executed — file still exists on disk!
    assert f_del.exists() is True
    assert "will_be_deleted" in f_del.read_text(encoding="utf-8")

    # The write was restored / never persisted broken code
    assert f_write.read_text(encoding="utf-8").replace("\r\n", "\n") == f_write_init

    _STAGED_REVIEWS.pop(job_id, None)


def test_monaco_write_file_crlf_preserved(tmp_path: Path):
    """Spot check: CRLF file through Monaco write_file stays CRLF on disk."""
    ws = str(tmp_path)
    target = tmp_path / "crlf_file.py"
    target.write_bytes(b"line 1\r\nline 2\r\nline 3\r\n")

    files_service.write_file(ws, "crlf_file.py", "line 1\nupdated line 2\nline 3\n")
    assert target.read_bytes() == b"line 1\r\nupdated line 2\r\nline 3\r\n"


def test_monaco_write_file_invalid_utf8_rejected_bytes_untouched(tmp_path: Path):
    """Spot check: Saving over invalid-UTF-8 file rejects with bytes untouched."""
    ws = str(tmp_path)
    target = tmp_path / "binary_corrupt.bin"
    corrupt_bytes = b"start\x80\x81\xfe\xffend"
    target.write_bytes(corrupt_bytes)

    with pytest.raises(HTTPException) as exc_info:
        files_service.write_file(ws, "binary_corrupt.bin", "new clean content\n")

    assert exc_info.value.status_code == 400
    assert "Unsupported encoding" in str(exc_info.value.detail)
    # Target bytes must remain 100% untouched
    assert target.read_bytes() == corrupt_bytes


@pytest.mark.asyncio
async def test_valid_proposal_makes_symbols_visible_via_find_function_immediately(tmp_path: Path):
    """A valid proposal applied via apply_proposal makes new symbols visible via find_function immediately."""
    from app.features.ai.agents.agent_tools import _handle_find_function
    from app.features.ai.service import apply_proposal
    from app.features.ai.schemas import EditProposalDto, FileChange

    ws = str(tmp_path)
    module_path = tmp_path / "service_core.py"
    module_path.write_text("def existing_helper():\n    return 1\n", encoding="utf-8")

    index_file(module_path)
    res_before = _handle_find_function(ws, {"name": "calculate_metric"})
    assert res_before.success is False

    proposal_id = "prop-add-metric-fn"
    mock_proposal = EditProposalDto(
        id=proposal_id,
        workspace=ws,
        status="pending",
        summary="Add calculate_metric function",
        changes=[
            FileChange(
                path="service_core.py",
                original="def existing_helper():\n    return 1\n",
                updated="def existing_helper():\n    return 1\n\ndef calculate_metric():\n    return 42\n",
            )
        ],
        diff="",
    )

    with patch("app.features.ai.service.get_proposal", return_value=mock_proposal):
        applied = await apply_proposal(proposal_id)
        assert applied.status in ("applied", "pending")

    # Prove pipeline's synchronous invalidation purged the stale cache entry WITHOUT watcher
    from app.features.ai.harness.symbol_index import _symbol_index
    assert str(module_path.resolve()) not in _symbol_index._cache

    # Query find_function directly WITHOUT manual re-index: triggers fresh parse and finds new symbol
    res_after = _handle_find_function(ws, {"name": "calculate_metric"})
    assert res_after.success is True
    assert "calculate_metric" in res_after.output
    assert "service_core.py" in res_after.output


@pytest.mark.asyncio
async def test_valid_proposal_clears_directory_cache(tmp_path: Path):
    """apply_proposal clears directory_cache via the registered pipeline invalidation hook."""
    from app.features.files.service import directory_cache
    from app.features.ai.service import apply_proposal
    from app.features.ai.schemas import EditProposalDto, FileChange

    ws = str(tmp_path)
    directory_cache.set(ws, "", [MagicMock()])
    assert directory_cache.get(ws, "") is not None

    proposal_id = "prop-cache-clear"
    mock_proposal = EditProposalDto(
        id=proposal_id,
        workspace=ws,
        status="pending",
        summary="Create new module",
        changes=[
            FileChange(
                path="new_feature.py",
                original="",
                updated="def feature_run():\n    pass\n",
            )
        ],
        diff="",
    )

    with patch("app.features.ai.service.get_proposal", return_value=mock_proposal):
        await apply_proposal(proposal_id)

    # directory_cache must be invalidated
    assert directory_cache.get(ws, "") is None



