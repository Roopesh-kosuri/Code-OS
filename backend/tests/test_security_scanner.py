"""
test_security_scanner.py — Test suite for Workspace Security Scanner and AI Auto-Fix.
"""

import json
import pytest
from pathlib import Path

from app.features.ai.security.scanner_service import (
    scan_workspace,
    parse_npm_audit,
    scan_file_for_secrets_and_xss,
)
from app.features.ai.security.fix_service import (
    generate_fix,
    apply_fix,
    verify_fix,
    GENERATED_FIXES,
)


@pytest.mark.asyncio
async def test_scan_detects_hardcoded_secret(tmp_path: Path):
    """Verify scanner flags hardcoded API keys and secrets."""
    secret_file = tmp_path / "config.py"
    secret_file.write_text(
        '# configuration file\nAPI_KEY = "AKIA1234567890ABCDEF"\nSECRET_TOKEN = "sk_live_9999888877776666"\n',
        encoding="utf-8"
    )

    result = scan_workspace(str(tmp_path))
    vulns = result["vulnerabilities"]

    assert len(vulns) >= 1
    found_types = [v["description"] for v in vulns]
    assert any("AWS Access Key" in d or "Hardcoded" in d for d in found_types)
    assert any(v["file"] == "config.py" for v in vulns)


@pytest.mark.asyncio
async def test_scan_detects_sql_injection(tmp_path: Path):
    """Verify scanner detects SQL injection via string concatenation or f-strings."""
    vulnerable_py = tmp_path / "db_queries.py"
    vulnerable_py.write_text(
        'def get_user(cursor, user_id):\n'
        '    cursor.execute(f"SELECT * FROM users WHERE id = \'{user_id}\'")\n'
        '    return cursor.fetchone()\n',
        encoding="utf-8"
    )

    result = scan_workspace(str(tmp_path))
    vulns = result["vulnerabilities"]

    assert len(vulns) >= 1
    sqli_vuln = next((v for v in vulns if "SQL" in v["description"] or v.get("cve_id") == "CWE-89"), None)
    assert sqli_vuln is not None
    assert sqli_vuln["severity"] == "Critical"
    assert "SELECT" in sqli_vuln["code_snippet"]


def test_npm_audit_parses_correctly():
    """Verify npm audit JSON parser extracts vulnerable packages, CVEs, and severities."""
    mock_audit_json = {
        "vulnerabilities": {
            "lodash": {
                "name": "lodash",
                "severity": "high",
                "range": "<4.17.21",
                "via": [
                    {
                        "title": "Prototype Pollution in lodash",
                        "url": "https://github.com/advisories/GHSA-p6mc-m468-83gw",
                        "range": "<4.17.21",
                        "cwe": ["CWE-1321"]
                    }
                ],
                "fixAvailable": {"version": "4.17.21"}
            }
        }
    }

    issues = parse_npm_audit(mock_audit_json)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["package"] == "lodash"
    assert issue["severity"] == "High"
    assert issue["safe_version"] == "4.17.21"
    assert "Prototype Pollution" in issue["description"]
    assert issue["cve"] == "CWE-1321"


@pytest.mark.asyncio
async def test_generate_fix_creates_parameterized_query(tmp_path: Path):
    """Verify fix_service transforms raw SQL query string interpolation into parameterized query."""
    vulnerable_py = tmp_path / "repo.py"
    vulnerable_py.write_text(
        'def find_account(cursor, account_id):\n'
        '    cursor.execute(f"SELECT * FROM accounts WHERE id = \'{account_id}\'")\n'
        '    return cursor.fetchone()\n',
        encoding="utf-8"
    )

    vuln = {
        "id": "vuln-sql-1",
        "file": "repo.py",
        "line": 2,
        "severity": "Critical",
        "cve_id": "CWE-89",
        "description": "SQL Injection: dynamic f-string formatting in SQL query",
        "code_snippet": 'cursor.execute(f"SELECT * FROM accounts WHERE id = \'{account_id}\'")'
    }

    fix = await generate_fix(vuln, str(tmp_path))
    assert fix["patch_diff"] is not None
    assert "patch_diff" in fix
    assert "%s" in fix["patch_diff"] or "?" in fix["patch_diff"] or "account_id" in fix["patch_diff"]
    assert "parameterized" in fix["explanation"].lower()


@pytest.mark.asyncio
async def test_apply_fix_updates_file_on_disk(tmp_path: Path):
    """Verify applying the patch modifies the target file content on disk."""
    target_file = tmp_path / "service.py"
    target_file.write_text(
        'def get_record(cursor, record_id):\n'
        '    cursor.execute(f"SELECT * FROM records WHERE id = \'{record_id}\'")\n'
        '    return cursor.fetchall()\n',
        encoding="utf-8"
    )

    vuln = {
        "id": "vuln-apply-1",
        "file": "service.py",
        "line": 2,
        "severity": "Critical",
        "description": "SQL Injection in query execution",
        "code_snippet": 'cursor.execute(f"SELECT * FROM records WHERE id = \'{record_id}\'")'
    }

    fix = await generate_fix(vuln, str(tmp_path))
    success = apply_fix(vuln["id"], fix["patch_diff"], str(tmp_path))
    assert success is True

    # Check content on disk
    updated_content = target_file.read_text(encoding="utf-8")
    assert "%s" in updated_content
    assert "f\"SELECT" not in updated_content


@pytest.mark.asyncio
async def test_verify_fix_confirms_vulnerability_resolved(tmp_path: Path):
    """Verify verify_fix re-scans the file and reports resolved status."""
    vulnerable_file = tmp_path / "auth.py"
    vulnerable_file.write_text(
        'def check_user(cursor, username):\n'
        '    cursor.execute(f"SELECT * FROM users WHERE name = \'{username}\'")\n'
        '    return cursor.fetchone()\n',
        encoding="utf-8"
    )

    vuln = {
        "id": "vuln-verify-1",
        "file": "auth.py",
        "line": 2,
        "severity": "Critical",
        "description": "SQL Injection",
        "code_snippet": 'cursor.execute(f"SELECT * FROM users WHERE name = \'{username}\'")'
    }

    fix = await generate_fix(vuln, str(tmp_path))
    apply_fix(vuln["id"], fix["patch_diff"], str(tmp_path))

    # Re-verify
    is_resolved = verify_fix(vuln["id"], str(tmp_path))
    assert is_resolved is True
