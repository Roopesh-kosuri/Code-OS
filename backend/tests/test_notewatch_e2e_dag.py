import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.features.ai.agents.coder import CoderAgent
from app.features.ai.dag_engine import DAGEngine
from app.features.ai.job_service import create_job, create_task, get_job


@pytest.mark.asyncio
async def test_coder_agent_notewatch_prompt_no_unbound_local(tmp_path):
    ws_dir = str(tmp_path / "stresstest_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    
    agent = CoderAgent()
    
    # Verify that executing CoderAgent with an empty LLM response (or error) returns failure with structured_data and NO UnboundLocalError
    with patch("app.features.ai.agents.coder.provider_for") as mock_p:
        mock_instance = mock_p.return_value
        async def mock_stream(*args, **kwargs):
            if False:
                yield ""
        mock_instance.stream_chat = mock_stream
        
        output = await agent.execute(
            job_id="test_notewatch_job",
            task_id="test_notewatch_task",
            title="Implement changes for notewatch CLI tool",
            context="Build a Python CLI tool called notewatch with watch, query, stats subcommands",
            workspace=ws_dir
        )
        
        assert output is not None
        assert output.status == "failure"
        assert output.structured_data is not None
        assert output.structured_data.get("agent_type") == "coder"
        assert "failed to generate" in output.reasoning_summary.lower() or "empty response" in output.reasoning_summary.lower() or "could not determine target files" in output.reasoning_summary.lower() or "parser could not extract" in output.reasoning_summary.lower()


@pytest.mark.asyncio
async def test_coder_agent_notewatch_prompt_with_valid_proposals(tmp_path):
    ws_dir = str(tmp_path / "stresstest_ws")
    Path(ws_dir).mkdir(parents=True, exist_ok=True)
    
    agent = CoderAgent()
    
    mock_llm_response = """
Here is the implementation:

[FILE: notewatch.py]
<<<< ORIGINAL
====
import sys
import json

def watch(folder):
    pass

def query(phrase):
    pass

def stats():
    pass
>>>>
"""
    
    with patch("app.features.ai.agents.coder.provider_for") as mock_p:
        mock_instance = mock_p.return_value
        async def mock_stream(*args, **kwargs):
            yield mock_llm_response
        mock_instance.stream_chat = mock_stream
        
        output = await agent.execute(
            job_id="test_notewatch_job_success",
            task_id="test_notewatch_task_success",
            title="Implement changes for notewatch CLI tool",
            context="Build notewatch CLI tool",
            workspace=ws_dir
        )
        
        assert output is not None
        assert output.status == "success"
        assert len(output.proposals) == 1
        assert output.proposals[0]["path"] == "notewatch.py"
        assert output.structured_data is not None
        assert output.structured_data.get("files_modified") == 1


@pytest.mark.asyncio
async def test_planner_agent_fallback_decomposition():
    from app.features.ai.agents.planner import PlannerAgent
    
    planner = PlannerAgent()
    prompt = """Build a Python CLI tool called "notewatch" that watches a local folder for new .txt files.

Requirements:
- Three subcommands: watch (start watching folder), query <phrase> (search index), and stats (print corpus size)
- Persistent TF-IDF index
- Include unit tests
"""
    # Force fallback by passing unparseable output
    fallback_tasks = planner._fallback_plan(prompt)
    
    assert len(fallback_tasks) >= 5
    titles = [t["title"] for t in fallback_tasks]
    # Verify subcommands were extracted as modular subtasks
    assert any("watch" in t.lower() for t in titles)
    assert any("query" in t.lower() for t in titles)
    assert any("stats" in t.lower() for t in titles)
    assert any(t["agent_role"] == "Review Agent" for t in fallback_tasks)
    assert any(t["agent_role"] == "Testing Agent" for t in fallback_tasks)
    assert any(t["agent_role"] == "Documentation Agent" for t in fallback_tasks)


@pytest.mark.asyncio
async def test_groq_model_normalization_resilience():
    from app.features.ai.service import provider_for
    from app.features.ai.schemas import ChatRequest
    
    # Request with "llama3" (an ollama name) to Groq should normalize to llama-3.3-70b-versatile
    req = ChatRequest(provider="groq", model="llama3", messages=[])
    provider = await provider_for(req)
    assert provider is not None
    assert req.model == "llama-3.3-70b-versatile"

