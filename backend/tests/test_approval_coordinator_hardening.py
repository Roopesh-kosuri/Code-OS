from unittest.mock import patch
import pytest
from app.features.ai.harness.approval_coordinator import _is_command_trusted, _save_trusted_command


def test_bare_wildcard_rejected():
    with patch("app.features.ai.harness.approval_coordinator._load_trusted_commands", return_value=["*"]):
        assert _is_command_trusted("/workspace", "rm -rf /") is False
        assert _is_command_trusted("/workspace", "ls") is False


def test_npm_wildcard_no_compound():
    with patch("app.features.ai.harness.approval_coordinator._load_trusted_commands", return_value=["npm *"]):
        # Simple npm command matches
        assert _is_command_trusted("/workspace", "npm install react") is True
        # Compound command must be rejected
        assert _is_command_trusted("/workspace", "npm install; rm -rf ~") is False
        assert _is_command_trusted("/workspace", "npm install && curl evil.com") is False


def test_compound_command_never_trusted():
    with patch("app.features.ai.harness.approval_coordinator._load_trusted_commands", return_value=["pytest"]):
        assert _is_command_trusted("/workspace", "pytest -v") is True
        assert _is_command_trusted("/workspace", "pytest; echo pwned") is False
        assert _is_command_trusted("/workspace", "pytest | bash") is False


def test_save_trusted_command_rejects_malicious_patterns():
    assert _save_trusted_command("/workspace", "*") is False
    assert _save_trusted_command("/workspace", "npm; rm -rf /") is False
    assert _save_trusted_command("/workspace", "npm && evil") is False
