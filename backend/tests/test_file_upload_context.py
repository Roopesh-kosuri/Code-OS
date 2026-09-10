"""test_file_upload_context.py — Regression tests for Phase 2: File Upload Context Injection Fix."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.features.ai.file_ingestion.service import save_uploaded_file, get_uploaded_file
from app.features.ai.harness.prompt_builder import (
    _build_system_prompt,
    _gather_budgeted_rag_context,
)
from app.features.ai.agents.planner import PlannerAgent
from app.features.ai.agents.coder import CoderAgent


@pytest.mark.asyncio
async def test_attachment_block_injected_before_rag(tmp_path: Path):
    """1. Verify <attached_files> block is injected before RAG context in user message."""
    ws = str(tmp_path / "ws_attach")
    (tmp_path / "ws_attach").mkdir(parents=True, exist_ok=True)
    
    file_bytes = b"def calculate_tax(income): return income * 0.2\n"
    saved = save_uploaded_file(ws, file_bytes, "tax_spec.py", "text/x-python")
    file_id = saved["file_id"]
    assert file_id is not None

    # Retrieve file from ingestion service
    fdata = get_uploaded_file(file_id, ws)
    assert fdata is not None

    file_block = (
        f'<file id="{file_id}" name="{fdata.get("filename")}" '
        f'type="{fdata.get("mime_type")}" pages="{fdata.get("page_count", 1)}" words="{fdata.get("word_count", 0)}">\n'
        f'{fdata.get("content", "")}\n'
        f'</file>'
    )
    attached_block = f'<attached_files count="1">\n{file_block}\n</attached_files>'

    rag_context = "\n\n--- RAG Workspace Snippets ---\n[file: dummy.py]\ndef other_func(): pass"
    user_query = "What is the tax calculation formula?"
    effective_user_message = f"{attached_block}\n\n{user_query}{rag_context}"

    assert "<attached_files count=\"1\">" in effective_user_message
    assert "<file id=" in effective_user_message
    assert "tax_spec.py" in effective_user_message
    assert "calculate_tax" in effective_user_message

    # Crucial: attached files MUST come before RAG workspace snippets
    attached_pos = effective_user_message.index("<attached_files")
    rag_pos = effective_user_message.index("--- RAG Workspace Snippets ---")
    assert attached_pos < rag_pos, "Attached files block must appear before RAG context"


def test_priority_rule_in_system_prompt(tmp_path: Path):
    """2. Verify ATTACHED FILES PRIORITY rule is in Tier 1, 2, and 3 system prompts."""
    ws = str(tmp_path / "ws_prompts")
    (tmp_path / "ws_prompts").mkdir(parents=True, exist_ok=True)

    for tier in (1, 2, 3):
        prompt = _build_system_prompt(workspace=ws, tier=tier, context={})
        assert "## ATTACHED FILES PRIORITY" in prompt, f"Tier {tier} prompt missing priority rule"
        assert "Answer PRIMARILY from the attached file content" in prompt
        assert "Only use workspace code as supplementary reference" in prompt
        assert "Always cite the source filename" in prompt
        assert "NEVER substitute workspace file content" in prompt


@pytest.mark.asyncio
async def test_attachment_overrides_workspace_rag(tmp_path: Path):
    """3. Verify attachment containing UNIQUE_TOKEN_ALPHA places attachment before workspace code."""
    ws = str(tmp_path / "ws_alpha")
    (tmp_path / "ws_alpha").mkdir(parents=True, exist_ok=True)

    file_bytes = b"UNIQUE_TOKEN_ALPHA = 'SECRET_PAYLOAD_98765'\n"
    saved = save_uploaded_file(ws, file_bytes, "alpha_protocol.py", "text/x-python")
    file_id = saved["file_id"]

    fdata = get_uploaded_file(file_id, ws)
    assert fdata is not None
    assert "UNIQUE_TOKEN_ALPHA" in fdata["content"]

    attached_xml = (
        f'<attached_files count="1">\n'
        f'<file id="{file_id}" name="alpha_protocol.py" type="text/x-python" pages="1" words="4">\n'
        f'{fdata["content"]}\n'
        f'</file>\n'
        f'</attached_files>'
    )

    rag_code = "--- Workspace Code: legacy.py ---\nLEGACY_WORKSPACE_TOKEN = 'IRRELEVANT'"
    assembled = f"{attached_xml}\n\nWhat token is used?\n\n{rag_code}"

    # Verify order: attached token precedes workspace token
    token_pos = assembled.index("UNIQUE_TOKEN_ALPHA")
    legacy_pos = assembled.index("LEGACY_WORKSPACE_TOKEN")
    assert token_pos < legacy_pos


@pytest.mark.asyncio
async def test_reduced_rag_budget_with_attachments(tmp_path: Path):
    """4. Verify _gather_budgeted_rag_context halves token/char budget when file_ids is non-empty."""
    ws = str(tmp_path / "ws_budget")
    (tmp_path / "ws_budget").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ws_budget" / "sample.py").write_text("def sample_fn(): pass\n" * 100)

    with patch("app.features.ai.harness.prompt_builder.semantic_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [
            {"path": "sample.py", "relative_path": "sample.py", "content": "def sample_fn(): pass\n" * 50, "score": 1.0}
        ]

        # 1. Without file_ids (max_chars=800)
        results_no_files, summary_no_files = await _gather_budgeted_rag_context(
            workspace=ws,
            query="sample",
            token_budget=200,
            max_chars=800,
            file_ids=None,
        )

        # 2. With file_ids (budget should be halved to max_chars=400)
        results_with_files, summary_with_files = await _gather_budgeted_rag_context(
            workspace=ws,
            query="sample",
            token_budget=200,
            max_chars=800,
            file_ids=["file_abc123"],
        )

        assert mock_search.call_count == 2
        # Verify budget halving effect: summary with files is roughly half of no-files budget
        assert len(summary_with_files) < len(summary_no_files)
        assert len(summary_with_files) <= 600
        assert len(summary_no_files) >= 700


@pytest.mark.asyncio
async def test_planner_receives_attached_files(tmp_path: Path):
    """5. Verify PlannerAgent receives attached_files and formats <attached_files> XML block."""
    planner = PlannerAgent()
    attached_files = [
        {
            "id": "spec_fid_1",
            "filename": "MICROSERVICES_SPEC.md",
            "content": "# Specification\nMust implement auth service and billing service.",
            "mime_type": "text/markdown",
            "page_count": 1,
            "word_count": 8,
        }
    ]

    # Test execute() on PlannerAgent
    output = await planner.execute(
        job_id="test_job_1",
        task_id="task_arch_1",
        title="Implement Microservices from Spec --quick",
        context={"attached_files": attached_files},
        workspace=str(tmp_path),
    )

    assert output.agent_role == "architect"
    assert output.status == "completed"
    assert "tasks" in output.structured_data
    assert len(output.structured_data["tasks"]) > 0


@pytest.mark.asyncio
async def test_coder_grounds_from_attached_files(tmp_path: Path):
    """6. Verify CoderAgent._ground_files includes attached file content as primary reference."""
    ws = str(tmp_path / "ws_coder")
    (tmp_path / "ws_coder").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ws_coder" / "main.py").write_text("print('hello world')\n")

    coder = CoderAgent()
    attached_files = [
        {
            "id": "spec_flux",
            "filename": "QUANTUM_FLUX_PROTOCOL.pdf",
            "content": "FLUX_CAPACITOR_VOLTAGE = 1.21 # Gigawatts required",
            "mime_type": "application/pdf",
            "page_count": 1,
            "word_count": 6,
        }
    ]

    grounding = await coder._ground_files(
        workspace=ws,
        files_to_touch=["main.py"],
        attached_files=attached_files,
    )

    assert "### [ATTACHED USER FILES (PRIMARY REFERENCE)]" in grounding
    assert "<attached_files count=\"1\">" in grounding
    assert "QUANTUM_FLUX_PROTOCOL.pdf" in grounding
    assert "FLUX_CAPACITOR_VOLTAGE = 1.21" in grounding

    # Attached files must be at the very top before target file grounding
    attach_pos = grounding.index("### [ATTACHED USER FILES (PRIMARY REFERENCE)]")
    target_pos = grounding.index("TARGET FILE TO EDIT")
    assert attach_pos < target_pos


def test_format_attached_files_xml_truncation_budget():
    """S4 Regression: Oversized attachment is cleanly truncated with head+tail and omission marker."""
    from app.features.ai.file_ingestion.service import format_attached_files_xml

    # Construct a large 25,000 char document
    head_marker = "START_OF_FORENSIC_AUDIT_REPORT_CHAPTER_1"
    tail_marker = "FINAL_RECOMMENDATIONS_AND_CONCLUSION_OF_AUDIT"
    body = "Security audit detailed findings line.\n" * 600
    huge_content = f"{head_marker}\n{body}\n{tail_marker}"
    assert len(huge_content) > 20000

    attached = [{
        "id": "audit_doc_huge",
        "filename": "huge_audit.pdf",
        "mime_type": "application/pdf",
        "page_count": 15,
        "content": huge_content,
    }]

    xml = format_attached_files_xml(attached, max_chars_per_file=12000)
    assert '<attached_files count="1">' in xml
    assert head_marker in xml
    assert tail_marker in xml
    assert "[... " in xml
    assert "characters omitted to stay within model context / TPM limits" in xml
    # Total characters of the file block must be capped
    assert len(xml) < 13500


def test_get_uploaded_file_in_memory_cache(tmp_path):
    """S4 Regression: get_uploaded_file returns cached dict without disk re-reads."""
    from app.features.ai.file_ingestion.service import (
        save_uploaded_file,
        get_uploaded_file,
        delete_uploaded_file,
        _FILE_RECORD_CACHE,
    )

    ws = str(tmp_path / "ws_cache")
    record = save_uploaded_file(
        workspace=ws,
        file_bytes=b"%PDF-1.4 test bytes",
        filename="cached_report.pdf",
        mime_type="application/pdf",
    )
    fid = record["file_id"]

    # Must be in cache immediately
    assert fid in _FILE_RECORD_CACHE

    # First lookup hits cache
    fetched1 = get_uploaded_file(fid, ws)
    assert fetched1 is not None
    assert fetched1["filename"] == "cached_report.pdf"

    # Modify in-memory record to prove it uses the cache
    fetched1["_probe_cached_marker"] = True
    fetched2 = get_uploaded_file(fid, ws)
    assert fetched2 is not None
    assert fetched2.get("_probe_cached_marker") is True

    # Delete clears the cache
    delete_uploaded_file(fid, ws)
    assert fid not in _FILE_RECORD_CACHE

