from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest

from app.features.ai.intelligence.task_classifier import (
    classify_task,
    HARD_KEYWORDS,
    EASY_KEYWORDS,
    MEDIUM_KEYWORDS,
)
from app.features.ai.smart_router.difficulty_classifier import (
    classify_task_difficulty,
    HARD_KEYWORDS as SC_HARD_KEYWORDS,
    EASY_KEYWORDS as SC_EASY_KEYWORDS,
    MEDIUM_KEYWORDS as SC_MEDIUM_KEYWORDS,
)
from app.features.ai.harness.plan_parser import _classify_rules, _classify_task_effort
from app.features.ai.team.team_schemas import TeamConfig, TeamRole


def test_keyword_single_source_of_truth():
    """Verify keywords in difficulty_classifier are references to task_classifier."""
    assert SC_HARD_KEYWORDS is HARD_KEYWORDS
    assert SC_EASY_KEYWORDS is EASY_KEYWORDS
    assert SC_MEDIUM_KEYWORDS is MEDIUM_KEYWORDS


def test_difficulty_classifier_delegation():
    """Verify legacy classify_task_difficulty delegates to classify_task."""
    with patch("app.features.ai.smart_router.difficulty_classifier.classify_task") as mock_classify:
        mock_classify.return_value = {
            "tier": "HARD",
            "confidence": 0.95,
            "score": 12.0,
            "reasons": ["architecture keyword match"],
            "method": "heuristic",
        }
        res = classify_task_difficulty("architect a distributed consensus engine", ["a.py", "b.py"])
        assert mock_classify.called
        assert res["difficulty"] == "HARD"
        assert res["confidence"] == 0.95
        assert res["score"] == 12.0
        assert res["reasons"] == ["architecture keyword match"]
        assert res["method"] == "heuristic"


def test_harness_plan_parser_delegation():
    """Verify plan_parser effort classifier delegates to classify_task."""
    with patch("app.features.ai.harness.plan_parser.classify_task") as mock_classify:
        mock_classify.return_value = {
            "tier": "HARD",
            "difficulty": "HARD",
            "confidence": 0.9,
            "score": 10.0,
            "reasons": ["complex system"],
            "method": "heuristic",
        }
        tier, label, reason = _classify_rules("redesign the auth system")
        assert mock_classify.called
        assert tier == 2
        assert label == "Deep think"
        assert "complex system" in reason


def test_harness_task_effort_wrapper():
    """Verify _classify_task_effort entrypoint with agent mode."""
    # Fast query in non-agent vs agent mode
    tier, label, _ = _classify_task_effort("hi", is_agent_mode=False)
    # Fast answers have tier 0 or 1 depending on query
    tier_agent, label_agent, _ = _classify_task_effort("hi", is_agent_mode=True)
    assert tier_agent >= 1
    assert label_agent == "Quick Task"


def test_team_schemas_smart_router_integration():
    """Verify TeamConfig.get_role_provider_config delegates to classify_task."""
    cfg = TeamConfig(smart_router_enabled=True)
    with patch("app.features.ai.intelligence.task_classifier.classify_task") as mock_classify:
        mock_classify.return_value = {
            "tier": "HARD",
            "difficulty": "HARD",
            "confidence": 0.95,
            "score": 15.0,
            "reasons": ["distributed"],
            "method": "heuristic",
        }
        res = cfg.get_role_provider_config(TeamRole.CODER, task_title="architect a distributed database")
        assert mock_classify.called
        assert "provider" in res
        assert "model" in res


def test_unified_classifier_end_to_end():
    """End-to-end classification check through the unified engine."""
    easy = classify_task("fix typo in README", file_list=["README.md"], use_llm=False)
    assert easy["tier"] == "EASY"
    assert easy["difficulty"] == "EASY"

    hard = classify_task(
        "refactor distributed consensus architecture and migrate authentication schemas across services",
        file_list=[f"src/service_{i}.py" for i in range(12)],
        use_llm=False,
    )
    assert hard["tier"] == "HARD"
    assert hard["difficulty"] == "HARD"
    assert hard["score"] > 5.0
