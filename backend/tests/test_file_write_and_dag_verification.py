import pytest
import asyncio
from pathlib import Path
from app.features.ai.service import extract_proposals_robust
from app.features.ai.schemas import FileChange, EditProposalRequest
from app.features.workspaces.trust_service import set_workspace_trust
from app.features.ai.dag_engine import DAGEngine
from app.features.ai.job_service import create_job, get_job, get_job_manifest


def test_extract_proposals_robust_formats():
    # 1. Standard format
    text1 = "[PROPOSAL: notewatch.py]\n<<<< ORIGINAL\n====\nimport os\nprint('hello')\n>>>>"
    p1 = extract_proposals_robust(text1)
    assert len(p1) == 1
    assert p1[0].path == "notewatch.py"
    assert "import os" in p1[0].updated

    # 2. Relaxed format without ORIGINAL delimiter
    text2 = "[PROPOSAL: utils/helper.py]\n<<<<\n====\ndef helper():\n    return True\n>>>>"
    p2 = extract_proposals_robust(text2)
    assert len(p2) == 1
    assert p2[0].path == "utils/helper.py"
    assert "def helper" in p2[0].updated

    # 3. Markdown header + code block
    text3 = "Here is the code:\n### notewatch.py\n```python\nimport click\n@click.group()\ndef cli(): pass\n```"
    p3 = extract_proposals_robust(text3)
    assert len(p3) == 1
    assert p3[0].path == "notewatch.py"
    assert "@click.group()" in p3[0].updated

    # 4. Code block with tag
    text4 = "```python:notewatch.py\nimport math\n```"
    p4 = extract_proposals_robust(text4)
    assert len(p4) == 1
    assert p4[0].path == "notewatch.py"
    assert "import math" in p4[0].updated

    # 5. Code block with first line comment
    text5 = "```python\n# filepath: notewatch.py\nimport sys\n```"
    p5 = extract_proposals_robust(text5)
    assert len(p5) == 1
    assert p5[0].path == "notewatch.py"
    assert "import sys" in p5[0].updated

    # 6. Single code block with single planned file
    text6 = "```python\ndef run():\n    pass\n```"
    p6 = extract_proposals_robust(text6, planned_files=["single_script.py"])
    assert len(p6) == 1
    assert p6[0].path == "single_script.py"


@pytest.mark.asyncio
async def test_dag_writes_and_verifies_files_on_disk(tmp_path):
    import uuid
    from app.features.ai.job_service import create_task
    from app.features.workspaces.service import open_workspace
    ws_dir = str(tmp_path / "test_dag_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await open_workspace(ws_dir)
    await set_workspace_trust(ws_dir, trusted=True)

    job_id = str(uuid.uuid4())
    await create_job(
        job_id=job_id,
        workspace=ws_dir,
        workflow="Feature Development",
        user_request="Build notewatch CLI tool"
    )

    await create_task(job_id, "task_coding_1", "Create notewatch.py CLI module", "Coding Agent", [], "30 mins")
    await create_task(job_id, "task_docs_1", "Synchronize README.md documentation", "Documentation Agent", ["task_coding_1"], "15 mins")

    engine = DAGEngine(job_id)
    await engine.run()

    job_data = await get_job(job_id)
    assert job_data["status"] == "completed"

    # DIRECT FILESYSTEM VERIFICATION
    notewatch_file = Path(ws_dir) / "notewatch.py"
    readme_file = Path(ws_dir) / "README.md"

    assert notewatch_file.is_file(), f"Expected {notewatch_file} to physically exist on disk"
    assert notewatch_file.stat().st_size > 0, "notewatch.py should be non-empty"

    assert readme_file.is_file(), f"Expected {readme_file} to physically exist on disk"
    assert readme_file.stat().st_size > 0, "README.md should be non-empty"

    # Verify DB files_modified matches
    files_modified = job_data["files_modified"]
    assert "notewatch.py" in files_modified
    assert "README.md" in files_modified

    # Verify manifest tracking
    manifest = await get_job_manifest(job_id)
    assert "notewatch.py" in manifest.get("files", {})
    assert "README.md" in manifest.get("files", {})


@pytest.mark.asyncio
async def test_full_notewatch_dag_creates_all_artifacts_on_disk(tmp_path):
    import uuid
    from app.features.ai.job_service import create_task
    from app.features.workspaces.service import open_workspace
    ws_dir = str(tmp_path / "stresstest_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    await open_workspace(ws_dir)
    await set_workspace_trust(ws_dir, trusted=True)

    user_req = (
        "Build a Python CLI tool called 'notewatch' that watches a local folder for new .txt files, "
        "extracts the top 3 key phrases from each new file using TF-IDF, and appends results to an index."
    )

    job_id = str(uuid.uuid4())
    await create_job(
        job_id=job_id,
        workspace=ws_dir,
        workflow="Feature Development",
        user_request=user_req
    )

    await create_task(job_id, "task_coding_nw", f"Implement changes for '{user_req}'", "Coding Agent", [], "45 mins")
    await create_task(job_id, "task_review_nw", "Perform static code review and quality checks", "Review Agent", ["task_coding_nw"], "20 mins")
    await create_task(job_id, "task_testing_nw", "Generate validation unit tests for notewatch", "Testing Agent", ["task_coding_nw"], "30 mins")
    await create_task(job_id, "task_docs_nw", "Synchronize project README.md documentation", "Documentation Agent", ["task_coding_nw"], "15 mins")

    engine = DAGEngine(job_id)
    await engine.run()

    job_data = await get_job(job_id)
    assert job_data["status"] == "completed"

    # Check that files exist on the filesystem
    created_files = [f.name for f in Path(ws_dir).rglob("*") if f.is_file()]
    print(f"Created files in workspace: {created_files}")

    assert len(created_files) > 0, "Files MUST exist on disk in workspace directory!"
    assert any("notewatch" in f.lower() for f in created_files), "notewatch file must exist on disk"
    assert "README.md" in created_files, "README.md must exist on disk"
