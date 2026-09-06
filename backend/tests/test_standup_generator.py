"""
test_standup_generator.py — Test suite for Daily Standup Generator.
"""

import json
import pytest
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.features.ai.standup.aggregator_service import gather_yesterday_activity
from app.features.ai.standup.standup_generator import generate_standup
from app.features.ai.standup.standup_routes import STANDUP_HISTORY, generate_standup_endpoint, GenerateStandupRequest


@pytest.mark.asyncio
async def test_aggregator_queries_jobs_and_git(tmp_path: Path):
    """Verify aggregator returns structured jobs, files, and git commits."""
    mock_pool = MagicMock()
    # Mock jobs rows
    mock_pool.read_query = MagicMock()
    mock_job_row = {
        "id": "job-101",
        "workflow": "feature-auth",
        "status": "completed",
        "user_request": "Implement JWT authentication",
        "started_at": time.time() - 3600,
        "completed_at": time.time() - 3000,
        "token_usage": 1500,
        "duration": 42.5,
        "files_modified": json.dumps(["src/auth.py", "tests/test_auth.py"]),
    }
    mock_cost_row = {
        "total_usd": 0.45,
        "total_toks": 3200,
    }

    async def mock_read_query(sql, params):
        if "agent_jobs" in sql:
            return [mock_job_row]
        if "cost_events" in sql:
            return [mock_cost_row]
        return []

    mock_pool.read_query.side_effect = mock_read_query

    async def mock_get_pool():
        return mock_pool

    with patch("app.features.ai.standup.aggregator_service.get_pool", side_effect=mock_get_pool):
        activity = await gather_yesterday_activity(str(tmp_path))

    assert len(activity["jobs_completed"]) == 1
    assert activity["jobs_completed"][0]["id"] == "job-101"
    assert "src/auth.py" in activity["files_modified"]
    assert activity["total_cost"] == "$0.45"
    assert "commits_made" in activity


@pytest.mark.asyncio
async def test_generator_produces_markdown_sections():
    """Verify generator produces standard Markdown headers and sections."""
    raw_data = {
        "jobs_completed": [{"user_request": "Refactor database query pooling"}],
        "files_modified": ["app/db/database.py"],
        "commits_made": [{"message": "refactor(db): pool size optimization"}],
        "tests_passed": 14,
        "total_cost": "$1.20",
    }

    report = await generate_standup(raw_data, format="markdown")

    assert "## What I did yesterday:" in report
    assert "## Metrics:" in report
    assert "## Blockers/Notes:" in report
    assert "## Plan for today:" in report
    assert "database.py" in report or "database query pooling" in report or "pool size" in report


@pytest.mark.asyncio
async def test_generator_produces_slack_format():
    """Verify generator produces Slack formatting with emojis and bold asterisks."""
    raw_data = {
        "jobs_completed": [{"user_request": "Fix CORS middleware bug"}],
        "files_modified": ["app/main.py"],
        "commits_made": [{"message": "fix(api): allow local dev origin"}],
        "tests_passed": 5,
        "total_cost": "$0.32",
    }

    report = await generate_standup(raw_data, format="slack")

    assert "🚀 *What I did yesterday:*" in report
    assert "📊 *Metrics:*" in report
    assert "⚠️ *Blockers/Notes:*" in report
    assert "🎯 *Plan for today:*" in report
    assert "• " in report


@pytest.mark.asyncio
async def test_includes_cost_and_metrics():
    """Verify metrics section accurately includes files, tests, and cost."""
    raw_data = {
        "jobs_completed": [],
        "files_modified": ["file1.py", "file2.py", "file3.py"],
        "commits_made": [],
        "tests_passed": 28,
        "total_cost": "$2.75",
    }

    report = await generate_standup(raw_data, format="markdown")

    assert "3 files modified" in report
    assert "28 tests passed" in report
    assert "$2.75" in report


@pytest.mark.asyncio
async def test_history_saves_generated_reports(tmp_path: Path):
    """Verify generated standup reports are stored in history and retrievable."""
    STANDUP_HISTORY.clear()

    req = GenerateStandupRequest(
        workspace=str(tmp_path),
        format="markdown"
    )

    async def mock_none():
        return None

    with patch("app.features.ai.standup.aggregator_service.get_pool", side_effect=mock_none):
        res = await generate_standup_endpoint(req)

    assert "report" in res
    assert res["format"] == "markdown"
    assert len(STANDUP_HISTORY) == 1
    assert STANDUP_HISTORY[0]["workspace"] == str(tmp_path)
    assert STANDUP_HISTORY[0]["report"] == res["report"]
