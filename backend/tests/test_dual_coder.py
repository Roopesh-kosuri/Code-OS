import pytest
from pathlib import Path
from app.features.ai.dual_coder_service import (
    DualCoderRequest,
    DualCoderModelConfig,
    execute_dual_coder,
    DUAL_CODER_SESSIONS
)

@pytest.mark.asyncio
async def test_execute_dual_coder_runs_both_models(tmp_path: Path):
    test_file = tmp_path / "utils.py"
    test_file.write_text("def multiply(a, b):\n    return a * b\n")

    req = DualCoderRequest(
        workspace=str(tmp_path),
        task_description="Add type hints and docstring to multiply function",
        model_a=DualCoderModelConfig(provider="ollama", model="llama3"),
        model_b=DualCoderModelConfig(provider="ollama", model="llama3"),
        target_file="utils.py"
    )

    res = await execute_dual_coder(req)

    assert res["status"] == "completed"
    assert "attempt_a" in res
    assert "attempt_b" in res
    assert res["attempt_a"]["attempt"] == "A"
    assert res["attempt_b"]["attempt"] == "B"
    assert res["id"] in DUAL_CODER_SESSIONS
