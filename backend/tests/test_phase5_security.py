"""
test_phase5_security.py
Phase 5.1 tests verifying supply chain security, strict dependency pinning,
and absence of vulnerable/unpinned components.
"""
from pathlib import Path
import re
import pytest


def test_requirements_strictly_pinned():
    """Verify all production dependencies in backend/requirements.txt are strictly pinned with =="""
    req_file = Path(__file__).resolve().parent.parent / "requirements.txt"
    assert req_file.exists(), "requirements.txt must exist"

    lines = req_file.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Split markers like ; sys_platform == 'win32'
        pkg_part = line.split(";")[0].strip()
        assert "==" in pkg_part, f"Package specification '{line}' is not strictly pinned with '=='"
        assert not pkg_part.startswith(">="), f"Unbounded specifier '>=' found in '{line}'"


def test_no_critical_vulnerabilities_hardened_versions():
    """Verify critical dependencies meet security-hardened version baselines."""
    req_file = Path(__file__).resolve().parent.parent / "requirements.txt"
    content = req_file.read_text(encoding="utf-8")

    # Cryptography must be >= 50.0.0
    crypto_match = re.search(r"cryptography==(\d+)\.", content)
    assert crypto_match and int(crypto_match.group(1)) >= 50, "cryptography must be >= 50.0.0"

    # GitPython must be >= 3.1.50
    git_match = re.search(r"gitpython==3\.1\.(\d+)", content)
    assert git_match and int(git_match.group(1)) >= 50, "gitpython must be >= 3.1.50"

    # python-multipart must be >= 0.0.20
    multipart_match = re.search(r"python-multipart==0\.0\.(\d+)", content)
    assert multipart_match and int(multipart_match.group(1)) >= 20, "python-multipart must be >= 0.0.20"


def test_sbom_and_dependencies_docs_exist():
    """Verify SBOM.md and DEPENDENCIES.md exist in docs/."""
    root = Path(__file__).resolve().parent.parent.parent
    sbom = root / "docs" / "SBOM.md"
    deps = root / "docs" / "DEPENDENCIES.md"

    assert sbom.exists(), "docs/SBOM.md must exist"
    assert deps.exists(), "docs/DEPENDENCIES.md must exist"
    assert "fastapi" in sbom.read_text(encoding="utf-8").lower()
    assert "pip-audit" in deps.read_text(encoding="utf-8").lower()
