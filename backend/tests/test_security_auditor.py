import pytest
from pathlib import Path
from app.features.ai.agents.auditor import AuditorAgent

@pytest.mark.asyncio
async def test_static_scan_detects_vulnerabilities(tmp_path: Path):
    # Create test workspace with intentional vulnerabilities
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-proj-1234567890abcdef1234567890abcdef\n")

    vulnerable_py = tmp_path / "app.py"
    vulnerable_py.write_text("""
import os
import sqlite3

def get_user(user_id):
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    # SQL Injection
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    # Command Injection
    os.system(f"echo {user_id}")
    return cursor.fetchall()
""")

    auditor = AuditorAgent()
    findings = auditor._static_scan_workspace(tmp_path)

    assert len(findings) >= 2
    categories = {f["category"] for f in findings}
    assert "secrets" in categories or "injection" in categories

    severities = {f["severity"] for f in findings}
    assert "CRITICAL" in severities or "HIGH" in severities

@pytest.mark.asyncio
async def test_execute_audit_returns_valid_structure(tmp_path: Path):
    clean_file = tmp_path / "main.py"
    clean_file.write_text("""
def add(a: int, b: int) -> int:
    return a + b
""")

    auditor = AuditorAgent()
    report = await auditor.execute_audit(str(tmp_path))

    assert "score" in report
    assert 0 <= report["score"] <= 100
    assert "risk_level" in report
    assert "findings" in report
    assert "category_scores" in report
    assert report["risk_level"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "CLEAN")
