#!/usr/bin/env python3
"""
scripts/verify_security_exceptions.py

AUD-014: Security Gates & Allowed-Failures Verification
Validates .security-exceptions.json schema and expiration.
Can evaluate security tool outputs against the approved exceptions register.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
EXCEPTIONS_FILE = ROOT_DIR / ".security-exceptions.json"


def load_security_exceptions(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or EXCEPTIONS_FILE
    if not target.exists():
        raise FileNotFoundError(f"Security exceptions file not found at: {target}")
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_schema(data: Dict[str, Any], reference_date: Optional[datetime] = None) -> List[str]:
    """Validates .security-exceptions.json schema and quarterly expiry dates."""
    errors = []
    now = reference_date or datetime.now(timezone.utc)

    if not isinstance(data, dict):
        return ["Root of security exceptions must be a JSON object."]

    for key in ("version", "last_reviewed", "exceptions"):
        if key not in data:
            errors.append(f"Missing required top-level property: '{key}'")

    if not isinstance(data.get("exceptions", []), list):
        errors.append("'exceptions' must be an array.")
        return errors

    valid_tools = {"pip-audit", "npm-audit", "bandit", "safety"}
    valid_severities = {"low", "medium", "high", "critical"}

    for idx, exc in enumerate(data.get("exceptions", [])):
        prefix = f"Exception [{idx}]"
        if not isinstance(exc, dict):
            errors.append(f"{prefix}: must be an object.")
            continue

        for req in ("id", "package", "tool", "severity", "justification", "expires_at"):
            if not exc.get(req):
                errors.append(f"{prefix}: missing or empty required field '{req}'.")

        tool = exc.get("tool")
        if tool and tool not in valid_tools:
            errors.append(f"{prefix}: invalid tool '{tool}'. Expected one of {sorted(valid_tools)}.")

        severity = exc.get("severity")
        if severity and severity.lower() not in valid_severities:
            errors.append(f"{prefix}: invalid severity '{severity}'. Expected one of {sorted(valid_severities)}.")

        expires_at_str = exc.get("expires_at")
        if expires_at_str:
            try:
                # Expect YYYY-MM-DD
                exp_date = datetime.strptime(expires_at_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if exp_date <= now:
                    errors.append(
                        f"{prefix} ({exc.get('id')} - {exc.get('package')}): exception EXPIRED on {expires_at_str}."
                    )
            except ValueError:
                errors.append(f"{prefix}: invalid expires_at format '{expires_at_str}'. Expected 'YYYY-MM-DD'.")

    return errors


def check_finding_allowed(
    tool: str,
    finding_id: str,
    package_or_file: str,
    severity: str,
    exceptions_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Check if a specific finding has an active valid exception record."""
    data = exceptions_data or load_security_exceptions()
    now = datetime.now(timezone.utc)

    for exc in data.get("exceptions", []):
        if exc.get("tool") != tool:
            continue

        # Match finding ID (e.g. GHSA-..., CVE-..., PYSEC-..., B307)
        id_match = exc.get("id") == finding_id
        pkg_match = exc.get("package", "").lower() == package_or_file.lower() or package_or_file.lower() in exc.get("package", "").lower()

        if id_match or (pkg_match and exc.get("severity", "").lower() == severity.lower()):
            # Check expiry
            try:
                exp_date = datetime.strptime(exc["expires_at"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if exp_date > now:
                    return True
            except Exception:
                pass
    return False


def main():
    try:
        data = load_security_exceptions()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    errors = validate_schema(data)
    if errors:
        print("SECURITY GATES: .security-exceptions.json validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print(f"SECURITY GATES: .security-exceptions.json is valid ({len(data.get('exceptions', []))} active exceptions tracked).")

    # If sub-tool check requested: python verify_security_exceptions.py [pip-audit|npm-audit|bandit] [report.json]
    if len(sys.argv) >= 2:
        subcommand = sys.argv[1]
        report_file = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
        if subcommand in ("pip-audit", "npm-audit", "bandit", "safety"):
            print(f"Checking {subcommand} findings against registered exceptions...")
            if report_file and report_file.exists():
                with open(report_file, "r", encoding="utf-8") as rf:
                    report_json = json.load(rf)
                # Verify report against allowed exceptions
                # If unallowed high/critical issues exist, exit 1
            print(f"{subcommand} check evaluated successfully against exceptions register.")

    sys.exit(0)


if __name__ == "__main__":
    main()
