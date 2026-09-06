"""
test_git_autopilot.py — Unit and integration tests for Git Autopilot.

Required Tests:
1. test_analyze_changes_groups_files_by_category (temp git repo)
2. test_generate_commit_message_conventional_format (mock LLM / heuristic)
3. test_generate_pr_description_structure (mock LLM / fallback)
4. test_stage_and_commit_creates_commit (temp git repo, verify git log contains message)
5. test_push_constructs_plain_push_only (assert no --force flag)
6. test_pr_creation_requires_token (400 without token)
"""

import asyncio
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.features.ai.git_autopilot.service import (
    analyze_changes,
    categorize_file,
    generate_commit_message,
    generate_pr_description,
    create_branch,
    stage_and_commit,
    push_branch,
    create_pull_request,
    parse_github_remote,
    get_github_token,
    save_github_token,
)


@pytest.fixture(autouse=True)
def mock_tracker():
    with patch("app.features.ai.git_autopilot.service.track_spawned_process", new_callable=AsyncMock), \
         patch("app.features.ai.git_autopilot.service.untrack_process", new_callable=AsyncMock):
        yield


def _init_test_git_repo(repo_path: Path) -> None:
    """Initialize a git repo with dummy user identity and initial commit."""
    p = str(repo_path)
    subprocess.run(["git", "init"], cwd=p, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@code-os.local"], cwd=p, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Code OS Test"], cwd=p, check=True, capture_output=True)
    # Create initial commit so HEAD exists
    init_file = repo_path / "init.txt"
    init_file.write_text("initial commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=p, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=p, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_analyze_changes_groups_files_by_category(tmp_path: Path):
    """Verify changes are analyzed with correct additions, deletions, and categories."""
    _init_test_git_repo(tmp_path)

    # Create files in 4 categories
    test_file = tmp_path / "tests" / "test_calc.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_add(): assert 1 + 1 == 2\n", encoding="utf-8")

    doc_file = tmp_path / "docs" / "guide.md"
    doc_file.parent.mkdir(parents=True, exist_ok=True)
    doc_file.write_text("# Guide\nDocumentation content here\n", encoding="utf-8")

    style_file = tmp_path / "src" / "theme.css"
    style_file.parent.mkdir(parents=True, exist_ok=True)
    style_file.write_text(".button { color: cyan; }\n", encoding="utf-8")

    feat_file = tmp_path / "src" / "calc.py"
    feat_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    analysis = await analyze_changes(str(tmp_path))

    assert analysis["totals"]["files"] == 4
    assert analysis["totals"]["additions"] > 0
    by_cat = analysis["totals"]["by_category"]

    assert by_cat.get("test") == 1
    assert by_cat.get("docs") == 1
    assert by_cat.get("style") == 1
    assert by_cat.get("feat") == 1

    file_cats = {f["path"]: f["category"] for f in analysis["files"]}
    assert file_cats.get("tests/test_calc.py") == "test"
    assert file_cats.get("docs/guide.md") == "docs"
    assert file_cats.get("src/theme.css") == "style"
    assert file_cats.get("src/calc.py") == "feat"


@pytest.mark.asyncio
async def test_generate_commit_message_conventional_format(tmp_path: Path):
    """Verify generated commit message adheres to Conventional Commits and 72-char subject limit."""
    _init_test_git_repo(tmp_path)

    calc_file = tmp_path / "calc.py"
    calc_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    class MockProvider:
        async def stream_chat(self, *args, **kwargs):
            yield "feat(calc): add basic addition functionality\n\n- support adding two numbers"

    with patch("app.features.ai.service.provider_for", new_callable=AsyncMock) as mock_prov_for:
        mock_prov_for.return_value = MockProvider()
        msg = await generate_commit_message(str(tmp_path))

    assert msg is not None
    assert len(msg.strip()) > 0

    first_line = msg.splitlines()[0].strip()
    # Enforce 72-char limit
    assert len(first_line) <= 72
    # Verify Conventional Commits syntax: type(scope): summary
    assert first_line.startswith("feat(calc):")
    assert "add basic addition functionality" in first_line


@pytest.mark.asyncio
async def test_generate_pr_description_structure(tmp_path: Path):
    """Verify generated PR description contains title and required markdown sections."""
    _init_test_git_repo(tmp_path)

    calc_file = tmp_path / "feature.py"
    calc_file.write_text("def feature(): pass\n", encoding="utf-8")

    class MockPRProvider:
        async def stream_chat(self, *args, **kwargs):
            import json
            yield json.dumps({
                "title": "feat(api): implement feature endpoint",
                "body": "## Summary\nImplemented feature endpoint.\n\n## Changes\n- Add feature.py\n\n## Testing\n- Unit tests pass\n\n## Screenshots\n_No screenshots provided._"
            })

    with patch("app.features.ai.service.provider_for", new_callable=AsyncMock) as mock_prov_for:
        mock_prov_for.return_value = MockPRProvider()
        pr_desc = await generate_pr_description(str(tmp_path), commit_message="feat(api): implement feature")

    assert pr_desc["title"] == "feat(api): implement feature endpoint"
    assert "body" in pr_desc

    body = pr_desc["body"]
    assert "## Summary" in body
    assert "## Changes" in body
    assert "## Testing" in body
    assert "## Screenshots" in body
    assert "_No screenshots provided._" in body


@pytest.mark.asyncio
async def test_stage_and_commit_creates_commit(tmp_path: Path):
    """Verify stage_and_commit creates a valid commit in the target repository."""
    _init_test_git_repo(tmp_path)

    new_file = tmp_path / "app.py"
    new_file.write_text("print('hello code-os')\n", encoding="utf-8")

    commit_msg = "feat(core): implement autopilot test"
    commit_hash = await stage_and_commit(str(tmp_path), commit_msg)

    assert commit_hash is not None
    assert len(commit_hash) == 40  # SHA-1 hex hash

    # Check git log in that repository
    res = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )
    assert commit_msg in res.stdout


@pytest.mark.asyncio
async def test_push_constructs_plain_push_only(tmp_path: Path):
    """Verify push_branch executes strictly plain push and rejects --force."""
    # 1. Verify --force is rejected immediately
    with pytest.raises(HTTPException) as exc_info:
        await push_branch(str(tmp_path), "main --force")
    assert exc_info.value.status_code == 400
    assert "Force push is strictly prohibited" in exc_info.value.detail

    with pytest.raises(HTTPException) as exc_info_short:
        await push_branch(str(tmp_path), "main -f")
    assert exc_info_short.value.status_code == 400

    # 2. Verify plain push arguments
    with patch("app.features.ai.git_autopilot.service._run_git_cmd", new_callable=AsyncMock) as mock_git:
        mock_git.return_value = (0, "Everything up-to-date", "")
        res = await push_branch(str(tmp_path), "feat/autopilot-ship")

        assert res["ok"] is True
        assert res["branch"] == "feat/autopilot-ship"
        args_passed = mock_git.call_args[0][1]
        assert args_passed == ["push", "-u", "origin", "feat/autopilot-ship"]
        assert "--force" not in args_passed
        assert "-f" not in args_passed


@pytest.mark.asyncio
async def test_pr_creation_requires_token(tmp_path: Path):
    """Verify create_pull_request raises 400 with helpful instructions when token is missing."""
    _init_test_git_repo(tmp_path)

    # Add dummy GitHub remote
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test-owner/test-repo.git"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )

    with patch("app.features.ai.git_autopilot.service.get_github_token", new_callable=AsyncMock) as mock_get_tok:
        mock_get_tok.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await create_pull_request(
                workspace=str(tmp_path),
                title="feat: test PR",
                body="## Summary\nTest",
                token=None,
            )

        assert exc_info.value.status_code == 400
        assert "GitHub Personal Access Token is required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_git_autopilot_remote_parsing():
    """Verify parse_github_remote parses both HTTPS and SSH URLs."""
    https_url = "https://github.com/acme-corp/project-alpha.git"
    owner, repo = parse_github_remote(https_url)
    assert owner == "acme-corp"
    assert repo == "project-alpha"

    ssh_url = "git@github.com:my-org/core-engine.git"
    owner_ssh, repo_ssh = parse_github_remote(ssh_url)
    assert owner_ssh == "my-org"
    assert repo_ssh == "core-engine"


@pytest.mark.asyncio
async def test_git_autopilot_routes_api(temp_db, tmp_path: Path):
    """Verify Git Autopilot HTTP endpoints: analyze, generate-commit, generate-pr, token."""
    _init_test_git_repo(tmp_path)
    (tmp_path / "app.py").write_text("print('test route')\n", encoding="utf-8")

    from app.core.auth import get_token
    headers = {"Authorization": f"Bearer {get_token()}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Analyze changes
        resp = await client.get(f"/api/git-autopilot/analyze?workspace={str(tmp_path)}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["totals"]["files"] >= 1

        # 2. Generate commit message
        commit_resp = await client.post(
            "/api/git-autopilot/generate-commit",
            json={"workspace": str(tmp_path)},
            headers=headers,
        )
        assert commit_resp.status_code == 200
        assert "commit_message" in commit_resp.json()

        # 3. Generate PR
        pr_resp = await client.post(
            "/api/git-autopilot/generate-pr",
            json={"workspace": str(tmp_path), "commit_message": "feat: test"},
            headers=headers,
        )
        assert pr_resp.status_code == 200
        assert "title" in pr_resp.json()
        assert "body" in pr_resp.json()

        # 4. Save and get token
        put_tok = await client.put(
            "/api/git-autopilot/github-token",
            json={"token": "ghp_testtoken123456789"},
            headers=headers,
        )
        assert put_tok.status_code == 200
        assert put_tok.json()["ok"] is True

        get_tok = await client.get("/api/git-autopilot/github-token", headers=headers)
        assert get_tok.status_code == 200
        assert get_tok.json()["has_token"] is True

