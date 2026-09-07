"""
Server-side security policy for test execution and container sandboxing.
Guarantees that commands are validated independently of model-supplied flags.
"""
from __future__ import annotations

import re
import shlex
from typing import Tuple

# Disallowed shell operators that enable chaining, redirection, or command substitution
FORBIDDEN_OPERATORS = [
    ";", "&&", "||", "|", "&", "`", "$(", "${", ">", "<", "\n", "\r",
]

# High-risk commands that must never be run via run_test
DANGEROUS_COMMAND_PATTERNS = [
    r"\bcurl\b",
    r"\bwget\b",
    r"\brm\s+(-[rfRF]+\s+)?(/|~|[a-zA-Z]:\\)",
    r"\brm\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bnc\b",
    r"\bnetcat\b",
    r"\bncat\b",
    r"\bpowershell\b",
    r"\bpwsh\b",
    r"\bcmd(?:\.exe)?\b",
    r"\bbash\b",
    r"\bsh\b",
    r"\bzsh\b",
    r"python(?:\d+(?:\.\d+)?)?\s+-c",
    r"py(?:\.exe)?\s+-c",
    r"node(?:\.exe)?\s+-e",
    r"\beval\b",
    r"\bexec\b",
]

# Legitimate test runner command prefixes allowed without manual user approval
ALLOWED_TEST_RUNNERS = [
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "py -m pytest",
    "python -m unittest",
    "python3 -m unittest",
    "py -m unittest",
    "npm test",
    "npm run test",
    "npx vitest",
    "vitest",
    "npx jest",
    "jest",
    "go test",
    "cargo test",
    "mvn test",
    "gradle test",
    "dotnet test",
    "ctest",
]


def validate_test_command(cmd: str) -> Tuple[bool, str, str]:
    """
    Validate a test command.
    Returns (allowed, status, reason):
      allowed=True, status="safe", reason="" -> legitimate test runner, safe to execute
      allowed=False, status="blocked", reason="..." -> malicious or dangerous, hard block
      allowed=False, status="needs_approval", reason="..." -> custom/unknown runner, requires approval
    """
    if not cmd or not cmd.strip():
        return False, "blocked", "Empty test command"

    cmd_clean = cmd.strip()

    # 1. Reject any shell operator
    for op in FORBIDDEN_OPERATORS:
        if op in cmd_clean:
            return False, "blocked", f"Shell operator '{op}' is not permitted in test execution."

    # 2. Reject dangerous commands / execution chains
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, cmd_clean, re.IGNORECASE):
            return False, "blocked", f"Command contains blocked execution pattern: '{pattern}'"

    # 3. Check for known test runner invocations
    cmd_lower = cmd_clean.lower()
    for runner in ALLOWED_TEST_RUNNERS:
        if cmd_lower == runner or cmd_lower.startswith(runner + " "):
            return True, "safe", ""

    # 4. Unknown runner: not blocked outright, but requires approval
    return False, "needs_approval", f"Unrecognized test runner invocation: '{cmd_clean}' requires user approval."


DANGEROUS_PATTERNS = [
    r"curl\s+.*\|\s*(?:bash|sh|powershell|pwsh)",
    r"wget\s+.*\|\s*(?:bash|sh)",
    r"eval\s+\$\(",
    r"\bnc\s+-e",
    r"rm\s+-rf\s+/(?:\s|$)",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
]


def is_dangerous_command(cmd: str) -> bool:
    """Check if command matches overtly dangerous shell execution patterns."""
    if not cmd:
        return False
    cmd_clean = cmd.strip().lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd_clean):
            return True
    return False


def should_require_sandbox(
    workspace: str,
    cmd: str,
    is_trusted: bool = False,
    is_safe: bool = False,
    is_command_trusted: bool = False,
) -> bool:
    """
    Determine if a command MUST be executed inside a container sandbox.
    Server-side policy that cannot be overridden by model flags.
    """
    if not cmd:
        return False

    if is_dangerous_command(cmd):
        return True

    # If workspace is not trusted, all mutating or non-allowlisted commands must be sandboxed
    if not is_trusted:
        if not is_safe and not is_command_trusted:
            return True

    # If the command is in the safe allowlist or explicitly trusted by the user, allow host execution
    if is_safe or is_command_trusted:
        return False

    return True
