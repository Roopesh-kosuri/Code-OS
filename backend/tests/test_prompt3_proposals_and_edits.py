import pytest
from pathlib import Path
from app.features.workspaces.trust_service import set_workspace_trust
from app.features.ai.service import create_proposal, get_proposal, apply_proposal
from app.features.ai.schemas import EditProposalRequest, FileChange
from app.features.ai.agents.coder import CoderAgent

@pytest.mark.asyncio
async def test_bug_a_proposal_approval_clears_from_pending_list(async_client, tmp_path, temp_db):
    ws_dir = str(tmp_path / "trusted_prop_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)

    # Create a test file
    test_file = Path(ws_dir) / "app.py"
    test_file.write_text("print('hello')\n")


    # 1. Create a proposal
    req = EditProposalRequest(
        workspace=ws_dir,
        summary="Task: Update app.py (Coding Agent)",
        changes=[
            FileChange(
                path="app.py",
                original="print('hello')\n",
                updated="print('hello world')\n"
            )
        ]
    )
    proposal = await create_proposal(req)
    assert proposal.status == "pending"

    # 2. Query pending proposals list — must include proposal
    res1 = await async_client.get(f"/api/ai/edit-proposals?workspace={ws_dir}")
    assert res1.status_code == 200
    pending1 = [p for p in res1.json() if p["status"] == "pending"]
    assert any(p["id"] == proposal.id for p in pending1)

    # 3. Apply/Approve proposal
    res_apply = await async_client.post(f"/api/ai/edit-proposals/{proposal.id}/apply")
    assert res_apply.status_code == 200

    # 4. Query pending proposals list again — approved proposal MUST NOT be in pending list
    res2 = await async_client.get(f"/api/ai/edit-proposals?workspace={ws_dir}")
    assert res2.status_code == 200
    pending2 = [p for p in res2.json() if p["status"] == "pending"]
    assert not any(p["id"] == proposal.id for p in pending2)


@pytest.mark.asyncio
async def test_bug_b_editing_existing_file_twice_in_a_row(tmp_path, temp_db):
    ws_dir = str(tmp_path / "trusted_edit_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)

    # 1. Create an existing file with initial content (> 150 lines)
    existing_file = Path(ws_dir) / "calculator.py"
    lines = [f"def func_{i}(): return {i}" for i in range(150)]
    existing_file.write_text("\n".join(lines) + "\n")


    coder = CoderAgent()

    # 2. Ground existing file — verify full content is captured without corruption
    grounded = await coder._ground_files(ws_dir, ["calculator.py"])
    assert "func_149" in grounded
    assert "... (" not in grounded  # No artificial truncation artifact

    # 3. First edit on existing file
    orig_block = "\n".join(lines[:10]) + "\n"
    updated_block = "# Calculator Header\n" + orig_block
    req1 = EditProposalRequest(
        workspace=ws_dir,
        summary="First Edit",
        changes=[
            FileChange(
                path="calculator.py",
                original=orig_block,
                updated=updated_block
            )
        ]
    )
    p1 = await create_proposal(req1)
    await apply_proposal(p1.id)

    # Verify file content updated
    updated_text_1 = existing_file.read_text(encoding="utf-8")
    assert "# Calculator Header" in updated_text_1

    # 4. Second grounding immediately after first edit — must read fresh file content
    grounded_fresh = await coder._ground_files(ws_dir, ["calculator.py"])
    assert "# Calculator Header" in grounded_fresh

    # 5. Second edit on the SAME existing file immediately after
    orig_block_2 = "\n".join(lines[140:150]) + "\n"
    updated_block_2 = orig_block_2 + "\ndef func_150(): return 150\n"
    req2 = EditProposalRequest(
        workspace=ws_dir,
        summary="Second Edit",
        changes=[
            FileChange(
                path="calculator.py",
                original=orig_block_2,
                updated=updated_block_2
            )
        ]
    )
    p2 = await create_proposal(req2)

    # Must apply successfully without merge conflict error
    applied_dto = await apply_proposal(p2.id)
    assert applied_dto.status == "applied"

    # Verify second edit took effect
    final_text = existing_file.read_text(encoding="utf-8")
    assert "func_150" in final_text
    assert "# Calculator Header" in final_text


@pytest.mark.asyncio
async def test_apply_proposal_preserves_no_trailing_newline_when_original_lacks_it(tmp_path, temp_db):
    """(b) When the original block being replaced lacks a trailing newline, replacement must not inject one."""
    ws_dir = str(tmp_path / "ws_no_newline")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)

    file_path = Path(ws_dir) / "module.py"
    initial_content = "VALUE = 42\nRESULT = VALUE + 1\n"
    file_path.write_text(initial_content, encoding="utf-8")

    # Replace inline 'VALUE = 42' (no trailing newline) with 'VALUE = 100'
    orig_block = "VALUE = 42"  # NO trailing newline
    updated_block = "```python\nVALUE = 100\n```"  # Outer fences with internal newline

    req = EditProposalRequest(
        workspace=ws_dir,
        summary="Update value inline",
        changes=[
            FileChange(
                path="module.py",
                original=orig_block,
                updated=updated_block,
            )
        ],
    )
    p = await create_proposal(req)
    applied = await apply_proposal(p.id)
    assert applied.status == "applied"

    result_text = file_path.read_text(encoding="utf-8")
    expected = "VALUE = 100\nRESULT = VALUE + 1\n"
    assert result_text == expected
    # Ensure no extra newline was injected between lines
    assert "VALUE = 100\n\nRESULT" not in result_text
    assert "VALUE = 100\nRESULT" in result_text


@pytest.mark.asyncio
async def test_apply_proposal_crlf_file_case_preserves_crlf(tmp_path, temp_db):
    """(c) CRLF file case: CRLF-encoded file and CRLF original block preserve CRLF throughout without line join."""
    ws_dir = str(tmp_path / "ws_crlf")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await set_workspace_trust(ws_dir, trusted=True)

    file_path = Path(ws_dir) / "crlf_app.py"
    initial_bytes = b"def greet():\r\n    msg = 'hello'\r\n    return msg\r\n\r\ndef farewell():\r\n    return 'bye'\r\n"
    file_path.write_bytes(initial_bytes)

    # Edit greet function with CRLF block
    orig_block = "def greet():\r\n    msg = 'hello'\r\n    return msg\r\n"
    updated_block = "```python\r\ndef greet():\r\n    msg = 'hi'\r\n    return msg\r\n```"

    req = EditProposalRequest(
        workspace=ws_dir,
        summary="Update greeting in CRLF file",
        changes=[
            FileChange(
                path="crlf_app.py",
                original=orig_block,
                updated=updated_block,
            )
        ],
    )
    p = await create_proposal(req)
    applied = await apply_proposal(p.id)
    assert applied.status == "applied"

    result_bytes = file_path.read_bytes()
    result_text = result_bytes.decode("utf-8")

    # 1. CRLF line endings preserved
    assert b"\r\n" in result_bytes
    # No lone \n without \r
    assert result_bytes.count(b"\n") == result_bytes.count(b"\r\n")

    # 2. Replacement preserved trailing CRLF; farewell is NOT joined to return msg
    assert "return msg\r\n\r\ndef farewell" in result_text
    assert "return msgdef farewell" not in result_text
    assert "msg = 'hi'" in result_text

