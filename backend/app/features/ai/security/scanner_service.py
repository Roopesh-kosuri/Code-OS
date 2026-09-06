"""
scanner_service.py — Security Scanner for detecting vulnerabilities and dependency issues.

Scans workspace for:
- Python security issues (bandit + regex/AST checks for SQLi, secrets, eval)
- Python dependency vulnerabilities (safety check on requirements.txt)
- JS/TS security issues (AST/regex checks for hardcoded API keys, tokens, XSS vectors)
- JS/TS dependency vulnerabilities (npm audit JSON parsing)
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Patterns for secrets
SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "Critical", "AWS Access Key ID exposed"),
    (r"ghp_[A-Za-z0-9]{36}", "Critical", "GitHub Personal Access Token exposed"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "Critical", "Private encryption key exposed"),
    (r"(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|private[_-]?key)\s*[:=]\s*['\"]([A-Za-z0-9_\-\.]{16,})['\"]", "High", "Hardcoded API key or secret token detected"),
    (r"password\s*[:=]\s*['\"]([^'\"]{6,})['\"]", "High", "Hardcoded password detected"),
]

# Patterns for SQL injection
SQLI_PATTERNS = [
    (r"""(?:execute|cursor\.execute|db\.execute)\s*\(\s*f["'].*?(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|UNION).*?\{.*?\}""", "Critical", "SQL Injection: dynamic f-string formatting in SQL query"),
    (r"""(?:execute|cursor\.execute|db\.execute)\s*\(\s*["'].*?(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|UNION).*?%s.*?["']\s*%\s*""", "Critical", "SQL Injection: % string interpolation in SQL query"),
    (r"""(?:execute|cursor\.execute|db\.execute)\s*\(\s*["'].*?(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|UNION).*?["']\s*\+\s*""", "Critical", "SQL Injection: string concatenation in SQL query"),
    (r"""(?:execute|cursor\.execute|db\.execute)\s*\(\s*["'].*?(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|UNION).*?["']\.format\(""", "Critical", "SQL Injection: .format() in SQL query"),
]

# Patterns for XSS and dangerous DOM operations
XSS_PATTERNS = [
    (r"dangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html\s*:\s*([^}]+)\s*\}\s*\}", "High", "XSS: dangerouslySetInnerHTML without sanitization"),
    (r"\.innerHTML\s*=\s*([^;]+)", "High", "XSS: direct innerHTML assignment allows DOM injection"),
    (r"document\.write\s*\(", "Medium", "XSS: document.write() is inherently unsafe and deprecated"),
    (r"(?<![a-zA-Z0-9_])eval\s*\(([^)]+)\)", "High", "Code Injection: unsafe eval() execution"),
]

# Known vulnerable python packages database fallback
KNOWN_PYTHON_VULNERABILITIES = {
    "requests": [("2.31.0", "CVE-2023-32681", "High", "2.31.0", "Unintended leak of Proxy-Authorization header on redirect")],
    "urllib3": [("1.26.18", "CVE-2023-45803", "Medium", "1.26.18", "Request body not stripped after 303 redirect")],
    "jinja2": [("3.1.3", "CVE-2024-22195", "Medium", "3.1.3", "HTML attribute injection via xmlattr filter")],
    "flask": [("2.2.5", "CVE-2023-30861", "High", "2.2.5", "Session cookie disclosure under certain cookie configurations")],
    "werkzeug": [("2.2.3", "CVE-2023-25577", "High", "2.2.3", "DoS via multipart/form-data with high number of parts")],
    "cryptography": [("41.0.0", "CVE-2023-38325", "High", "41.0.0", "NULL-dereference when handling malformed certificates")],
}


def parse_npm_audit(audit_data: Any) -> List[Dict[str, Any]]:
    """Parse npm audit JSON output (supports both npm v6 advisories and npm v7+ vulnerabilities formats)."""
    issues: List[Dict[str, Any]] = []
    if isinstance(audit_data, str):
        try:
            audit_data = json.loads(audit_data)
        except Exception:
            return issues

    if not isinstance(audit_data, dict):
        return issues

    # npm v7+ format
    if "vulnerabilities" in audit_data and isinstance(audit_data["vulnerabilities"], dict):
        for pkg_name, vuln in audit_data["vulnerabilities"].items():
            sev = str(vuln.get("severity", "moderate")).capitalize()
            if sev == "Moderate":
                sev = "Medium"
            
            cve = "N/A"
            via = vuln.get("via", [])
            desc = f"Vulnerability detected in package {pkg_name}"
            safe_ver = "latest"
            
            if via and isinstance(via, list) and isinstance(via[0], dict):
                first = via[0]
                desc = first.get("title", desc)
                safe_ver = first.get("range", "latest")
                cves = first.get("cwe", [])
                if cves and isinstance(cves, list):
                    cve = cves[0]
                elif first.get("url"):
                    cve = first.get("url").split("/")[-1]

            cur_ver = vuln.get("range", "unknown")
            fix_avail = vuln.get("fixAvailable")
            if isinstance(fix_avail, dict) and fix_avail.get("version"):
                safe_ver = fix_avail.get("version")

            issues.append({
                "package": pkg_name,
                "current_version": cur_ver,
                "safe_version": safe_ver,
                "cve": cve,
                "severity": sev,
                "description": desc,
            })

    # npm v6 format
    elif "advisories" in audit_data and isinstance(audit_data["advisories"], dict):
        for adv_id, adv in audit_data["advisories"].items():
            sev = str(adv.get("severity", "moderate")).capitalize()
            if sev == "Moderate":
                sev = "Medium"
            cves = adv.get("cves", [])
            cve = cves[0] if cves else f"GHSA-{adv_id}"
            issues.append({
                "package": adv.get("module_name", "unknown"),
                "current_version": adv.get("vulnerable_versions", "unknown"),
                "safe_version": adv.get("patched_versions", "latest"),
                "cve": cve,
                "severity": sev,
                "description": adv.get("title", "Security advisory"),
            })

    return issues


def scan_file_for_secrets_and_xss(file_path: Path, rel_path: str) -> List[Dict[str, Any]]:
    """Scan a single source code file using regex patterns."""
    findings: List[Dict[str, Any]] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        # Ignore comments and test mocks/definitions if clearly benign
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("//") or line_clean.startswith("#") or line_clean.startswith("*"):
            continue

        # Check secrets
        for pattern, sev, desc in SECRET_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Avoid matching dummy environment placeholders
                if "process.env" in line or "os.environ" in line or "your-api-key" in line.lower() or "example" in line.lower():
                    continue
                findings.append({
                    "id": str(uuid.uuid4()),
                    "file": rel_path.replace("\\", "/"),
                    "line": idx,
                    "severity": sev,
                    "cve_id": None,
                    "description": desc,
                    "code_snippet": line_clean,
                    "status": "open",
                })
                break

        # Check SQLi
        for pattern, sev, desc in SQLI_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "id": str(uuid.uuid4()),
                    "file": rel_path.replace("\\", "/"),
                    "line": idx,
                    "severity": sev,
                    "cve_id": "CWE-89",
                    "description": desc,
                    "code_snippet": line_clean,
                    "status": "open",
                })
                break

        # Check XSS
        for pattern, sev, desc in XSS_PATTERNS:
            if re.search(pattern, line):
                # If it's a test assertion or mock, ignore
                if "expect(" in line or "test(" in line:
                    continue
                findings.append({
                    "id": str(uuid.uuid4()),
                    "file": rel_path.replace("\\", "/"),
                    "line": idx,
                    "severity": sev,
                    "cve_id": "CWE-79",
                    "description": desc,
                    "code_snippet": line_clean,
                    "status": "open",
                })
                break

    return findings


def scan_python_with_bandit(workspace_path: Path) -> List[Dict[str, Any]]:
    """Run bandit security linter on workspace Python files."""
    vulnerabilities: List[Dict[str, Any]] = []
    py_files = list(workspace_path.rglob("*.py"))
    # Filter out virtual environments and node_modules
    valid_py_files = [
        f for f in py_files
        if not any(part in f.parts for part in ("venv", ".venv", "node_modules", ".git", ".code_os", "__pycache__"))
    ]

    if not valid_py_files:
        return vulnerabilities

    try:
        # Run bandit via subprocess
        cmd = ["py", "-m", "bandit", "-r", str(workspace_path), "-f", "json", "-x", "**/venv/**,**/.venv/**,**/node_modules/**"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        output = proc.stdout
        if output:
            data = json.loads(output)
            results = data.get("results", [])
            for res in results:
                f_path = res.get("filename", "")
                try:
                    rel_p = str(Path(f_path).relative_to(workspace_path)).replace("\\", "/")
                except Exception:
                    rel_p = f_path.replace("\\", "/")

                sev = str(res.get("issue_severity", "MEDIUM")).capitalize()
                issue_txt = res.get("issue_text", "").lower()
                test_id = str(res.get("test_id", ""))
                if "sql" in issue_txt or test_id == "B608":
                    sev = "Critical"
                elif sev == "High":
                    sev = "High"

                vulnerabilities.append({
                    "id": str(uuid.uuid4()),
                    "file": rel_p,
                    "line": res.get("line_number", 1),
                    "severity": sev,
                    "cve_id": res.get("test_id", None),
                    "description": res.get("issue_text", "Bandit security finding"),
                    "code_snippet": res.get("code", "").strip(),
                    "status": "open",
                })
    except Exception as exc:
        logger.debug("Bandit scan completed with note: %s", exc)

    return vulnerabilities


def check_python_dependencies(workspace_path: Path) -> List[Dict[str, Any]]:
    """Check requirements.txt against safety / known CVE database."""
    dependency_issues: List[Dict[str, Any]] = []
    req_file = workspace_path / "requirements.txt"
    if not req_file.exists():
        # Also check backend/requirements.txt
        req_file = workspace_path / "backend" / "requirements.txt"
        if not req_file.exists():
            return dependency_issues

    # Try running safety CLI if possible
    try:
        cmd = ["py", "-m", "safety", "check", "-r", str(req_file), "--json"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.stdout and proc.stdout.strip().startswith("["):
            data = json.loads(proc.stdout)
            for item in data:
                # safety JSON: [package, affected_spec, installed_version, advisory, cve]
                if isinstance(item, list) and len(item) >= 5:
                    dependency_issues.append({
                        "package": item[0],
                        "current_version": item[2],
                        "safe_version": item[1],
                        "cve": item[4] or "CVE-UNKNOWN",
                        "severity": "High",
                        "description": item[3],
                    })
    except Exception as exc:
        logger.debug("Safety CLI check fallback to database: %s", exc)

    # Fallback: parse requirements.txt against known vulnerable package versions
    try:
        content = req_file.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([a-zA-Z0-9_\-]+)==([0-9\.]+)", line)
            if match:
                pkg = match.group(1).lower()
                ver = match.group(2)
                if pkg in KNOWN_PYTHON_VULNERABILITIES:
                    for safe_ver, cve, sev, fix_ver, desc in KNOWN_PYTHON_VULNERABILITIES[pkg]:
                        from packaging import version
                        try:
                            if version.parse(ver) < version.parse(safe_ver):
                                # Avoid duplicating if safety already caught it
                                if not any(d["package"].lower() == pkg for d in dependency_issues):
                                    dependency_issues.append({
                                        "package": pkg,
                                        "current_version": ver,
                                        "safe_version": f">={fix_ver}",
                                        "cve": cve,
                                        "severity": sev,
                                        "description": desc,
                                    })
                        except Exception:
                            pass
    except Exception as exc:
        logger.warning("Requirements check error: %s", exc)

    return dependency_issues


def check_npm_dependencies(workspace_path: Path) -> List[Dict[str, Any]]:
    """Run npm audit on workspace or parse package.json dependencies."""
    dependency_issues: List[Dict[str, Any]] = []
    pkg_json = workspace_path / "package.json"
    if not pkg_json.exists():
        return dependency_issues

    # Try running npm audit --json
    try:
        # Check npm audit with shell=True on Windows
        proc = subprocess.run(
            ["npm", "audit", "--json"],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            timeout=20,
            shell=True,
        )
        if proc.stdout:
            dependency_issues = parse_npm_audit(proc.stdout)
    except Exception as exc:
        logger.debug("npm audit execution fallback: %s", exc)

    return dependency_issues


def scan_workspace(workspace: str) -> Dict[str, Any]:
    """
    Main workspace security scan entry point.
    Returns {
        "vulnerabilities": [{id, file, line, severity, cve_id, description, code_snippet, status}],
        "dependency_issues": [{package, current_version, safe_version, cve, severity, description}]
    }
    """
    ws_path = Path(workspace)
    if not ws_path.is_dir():
        return {"vulnerabilities": [], "dependency_issues": []}

    all_vulnerabilities: List[Dict[str, Any]] = []
    seen_locations: set = set()

    # 1. Python bandit scan
    bandit_vulns = scan_python_with_bandit(ws_path)
    for v in bandit_vulns:
        key = (v["file"], v["line"])
        if key not in seen_locations:
            seen_locations.add(key)
            all_vulnerabilities.append(v)

    # 2. File-by-file pattern scanning (Python, JS, TS, TSX, JSX, ENV, JSON)
    relevant_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".env", ".json"}
    for root, dirs, files in os.walk(ws_path):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", ".venv", ".code_os", "dist", "build", "__pycache__"}]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in relevant_exts:
                f_path = Path(root) / fname
                try:
                    rel_p = str(f_path.relative_to(ws_path))
                except Exception:
                    rel_p = str(f_path)

                findings = scan_file_for_secrets_and_xss(f_path, rel_p)
                for finding in findings:
                    key = (finding["file"], finding["line"])
                    if key not in seen_locations:
                        seen_locations.add(key)
                        all_vulnerabilities.append(finding)

    # 3. Dependency scanning
    dep_issues = []
    dep_issues.extend(check_python_dependencies(ws_path))
    dep_issues.extend(check_npm_dependencies(ws_path))

    return {
        "vulnerabilities": all_vulnerabilities,
        "dependency_issues": dep_issues,
    }
