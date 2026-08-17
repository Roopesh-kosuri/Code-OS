import pytest
from app.features.ai.workspace_manifest import (
    WorkspaceManifest,
    ManifestEntry,
    extract_exports,
    build_prior_steps_context,
)
from app.features.ai.output_validator import (
    validate_proposals,
    format_stub_findings,
)
from app.features.ai.spec_coverage import (
    extract_requirements,
    check_coverage,
    format_coverage_report,
)
from app.features.ai.schemas import FileChange


# ── Test 1: Workspace Manifest & Export Extraction ───────────────────────────

def test_extract_exports():
    python_code = """
def authenticate_user(username, password):
    return True

async def fetch_token():
    return "token"

class DatabaseManager:
    pass

def _private_func():
    pass
"""
    exports = extract_exports(python_code)
    assert "authenticate_user" in exports
    assert "fetch_token" in exports
    assert "DatabaseManager" in exports
    assert "_private_func" not in exports


def test_manifest_lifecycle():
    manifest = WorkspaceManifest()
    manifest.add_file(
        path="src/auth.py",
        purpose="Implement authentication",
        task_id="task_1",
        task_title="Auth Setup",
        agent_role="Coding Agent",
        code_content="def login(): return True",
        is_new_file=True,
    )
    
    entries = manifest.get_entries()
    assert "src/auth.py" in entries
    assert entries["src/auth.py"]["exports"] == ["login"]
    assert entries["src/auth.py"]["created_by_task_id"] == "task_1"
    
    # JSON serialization
    raw = manifest.to_json()
    reconstructed = WorkspaceManifest.from_json(raw)
    assert "src/auth.py" in reconstructed.get_entries()
    assert "src/auth.py" in reconstructed.summary_text()


def test_manifest_duplicate_detection():
    manifest = WorkspaceManifest()
    manifest.add_file(
        path="src/database_manager.py",
        purpose="Database connection and interaction manager",
        task_id="task_1",
        task_title="Database Manager",
        agent_role="Coding Agent",
        code_content="def connect(): pass\ndef query(): pass",
    )

    # Attempting to create a duplicate DB connection layer
    dups = manifest.check_duplicates(
        new_path="src/db_connection.py",
        new_purpose="Database connection manager",
        new_exports=["connect", "query"],
    )
    assert len(dups) > 0
    assert dups[0]["existing_path"] == "src/database_manager.py"


# ── Test 2: Output Validator Stub Detection ──────────────────────────────────

def test_stub_detection_pass_only():
    proposals = [
        FileChange(
            path="src/embeddings_generator.py",
            original="",
            updated="def generate_embeddings(text: str):\n    pass\n",
        )
    ]
    findings = validate_proposals(proposals)
    assert len(findings) == 1
    assert findings[0].stub_type == "pass_only"
    assert findings[0].function_name == "generate_embeddings"


def test_stub_detection_not_implemented():
    proposals = [
        FileChange(
            path="src/retriever.py",
            original="",
            updated="def retrieve_documents(query):\n    raise NotImplementedError('TODO')\n",
        )
    ]
    findings = validate_proposals(proposals)
    assert len(findings) == 1
    assert findings[0].stub_type == "not_implemented"


def test_stub_detection_todo_only():
    proposals = [
        FileChange(
            path="src/rag_pipeline.py",
            original="",
            updated="def execute_pipeline():\n    # TODO: implement RAG search\n    # FIXME: add vector search\n",
        )
    ]
    findings = validate_proposals(proposals)
    assert len(findings) == 1
    assert findings[0].stub_type == "todo_only"


def test_stub_detection_valid_code_passes():
    proposals = [
        FileChange(
            path="src/calculator.py",
            original="",
            updated="""
def add(a: int, b: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    return a + b

def multiply(a: int, b: int) -> int:
    result = a * b
    return result
""",
        )
    ]
    findings = validate_proposals(proposals)
    assert len(findings) == 0


# ── Test 3: Spec Coverage Extraction & Matching ──────────────────────────────

def test_spec_coverage_extraction():
    spec = 'Build a RAG pipeline with "embeddings generator", vector store, and CLI search'
    reqs = extract_requirements(spec)
    assert any("embeddings generator" in r.lower() for r in reqs)
    assert any("rag" in r.lower() or "pipeline" in r.lower() for r in reqs)
    assert any("vector" in r.lower() or "cli" in r.lower() for r in reqs)


def test_spec_coverage_checking():
    reqs = ["embeddings", "vector store", "cli"]
    manifest_entries = {
        "src/embeddings.py": {"purpose": "Embeddings generator", "exports": ["get_embeddings"]},
        "src/vector_store.py": {"purpose": "Vector store database", "exports": ["save_vector"]},
        "src/cli.py": {"purpose": "Command line interface", "exports": ["main"]},
    }
    completed_tasks = [
        {"title": "Build embeddings", "reasoning_summary": "Created vector embeddings"},
    ]
    cov = check_coverage(reqs, manifest_entries, completed_tasks)
    assert cov["coverage_ratio"] == 1.0
    assert len(cov["uncovered"]) == 0


# ── Test: extract_proposals_robust — Prose-Preceding-Block Strategy ──────────

def test_extract_proposals_bold_filename_before_code_block():
    from app.features.ai.service import extract_proposals_robust
    # Simulate the common LLM pattern: **filename.py** followed by a code block
    raw = '''Here's the implementation:

**rag_engine.py**
```python
import numpy as np

def embed_text(text):
    return np.random.rand(128)
```

**vector_store.py**
```python
import json

class VectorStore:
    def __init__(self):
        self.vectors = []
```
'''
    proposals = extract_proposals_robust(raw)
    assert len(proposals) >= 2
    paths = [p.path for p in proposals]
    assert "rag_engine.py" in paths
    assert "vector_store.py" in paths
    assert "import numpy" in proposals[0].updated or "import numpy" in proposals[1].updated


def test_extract_proposals_backtick_filename_before_code_block():
    from app.features.ai.service import extract_proposals_robust
    # Simulate: `filename.py`: followed by code block
    raw = '''Create the following files:

`retriever.py`:
```python
def retrieve(query, index):
    return index.search(query)
```
'''
    proposals = extract_proposals_robust(raw)
    assert len(proposals) >= 1
    assert proposals[0].path == "retriever.py"
    assert "def retrieve" in proposals[0].updated


def test_extract_proposals_empty_response_returns_empty():
    from app.features.ai.service import extract_proposals_robust
    assert extract_proposals_robust("") == []
    assert extract_proposals_robust("   ") == []
    assert extract_proposals_robust("I'm not sure how to help with that.") == []
