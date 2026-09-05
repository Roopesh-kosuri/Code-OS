"""
test_path_containment_property.py
Phase 5.2: Property-based path containment testing using Hypothesis.
Verifies that ensure_within_workspace NEVER allows a path escape under ANY
adversarial input (traversals, UNC paths, drive variants, null bytes, homoglyphs).
"""
import os
from pathlib import Path
from fastapi import HTTPException
from hypothesis import given, strategies as st, settings, HealthCheck
import pytest

from app.core.paths import ensure_within_workspace, is_within_workspace, normalize_path


# 1. Arbitrary string fuzzing strategy
@settings(max_examples=300, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(path=st.text(min_size=1, max_size=200))
def test_path_never_escapes_workspace_fuzz(path, tmp_path):
    """For ANY arbitrary path string, ensure_within_workspace must either:
    - Return a path strictly inside workspace
    - Raise HTTPException (400 or 403), ValueError, or OSError
    It must NEVER return a path outside the workspace.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    ws_str = str(workspace.resolve())

    try:
        result = ensure_within_workspace(ws_str, path)
        res_str = str(result.resolve())
        # If no exception, result MUST be equal to or a subpath of workspace
        assert res_str.lower().startswith(ws_str.lower()), f"Path escape detected: {res_str} is not in {ws_str}"
        assert is_within_workspace(Path(ws_str), result) is True
    except (HTTPException, ValueError, OSError):
        pass


# 2. Structured Path Traversal Strategy
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    traversal=st.sampled_from([
        "../", "..\\", "../..", "..\\..", "..;/etc/passwd", "..;/windows/win.ini",
        "....//", "....\\", "..%2f..%2f", "/../", "\\..\\",
        "nested/../../../../secret", "a/b/c/../../../../../../windows/system32",
        "/etc/shadow", "C:\\Windows\\System32\\calc.exe", "D:\\sensitive\\file.key",
    ]),
    suffix=st.text(min_size=0, max_size=20)
)
def test_path_traversal_payloads_strictly_contained(traversal, suffix, tmp_path):
    workspace = tmp_path / "ws_traversal"
    workspace.mkdir(exist_ok=True)
    ws_str = str(workspace.resolve())
    payload = traversal + suffix

    try:
        result = ensure_within_workspace(ws_str, payload)
        res_str = str(result.resolve())
        assert res_str.lower().startswith(ws_str.lower()), f"Escape via traversal '{payload}': {res_str}"
    except (HTTPException, ValueError, OSError):
        pass


# 3. UNC Paths and Windows Remote Share Strategy
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    unc=st.sampled_from([
        "\\\\evil\\share\\payload.exe",
        "\\\\127.0.0.1\\c$\\windows",
        "\\\\?\\C:\\escaped\\file.txt",
        "\\\\.\\pipe\\docker_engine",
        "//attacker.com/nfs/leak",
    ])
)
def test_unc_paths_strictly_rejected(unc, tmp_path):
    workspace = tmp_path / "ws_unc"
    workspace.mkdir(exist_ok=True)
    ws_str = str(workspace.resolve())

    try:
        result = ensure_within_workspace(ws_str, unc)
        res_str = str(result.resolve())
        assert res_str.lower().startswith(ws_str.lower()), f"Escape via UNC '{unc}': {res_str}"
    except (HTTPException, ValueError, OSError):
        pass


# 4. Null byte and control characters injection strategy
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    malicious=st.sampled_from([
        "safe_file.txt\x00.exe",
        "file\x00/../../escaped",
        "data\r\n../windows",
        "test\tfile.txt",
        "~\\secrets",
        "~/keys.pem",
    ])
)
def test_null_bytes_and_tilde_rejected(malicious, tmp_path):
    workspace = tmp_path / "ws_control"
    workspace.mkdir(exist_ok=True)
    ws_str = str(workspace.resolve())

    try:
        result = ensure_within_workspace(ws_str, malicious)
        res_str = str(result.resolve())
        assert res_str.lower().startswith(ws_str.lower()), f"Escape via control payload '{malicious}': {res_str}"
    except (HTTPException, ValueError, OSError):
        pass


# 5. Unicode Homoglyphs Strategy
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    homoglyph=st.sampled_from([
        "\u0430dmin/secret.txt",
        "\u0440ath/traversal.key",
        "sys\u200Btem/payload",
        "test/\u202Ereversed",
    ])
)
def test_unicode_homoglyphs_contained(homoglyph, tmp_path):
    workspace = tmp_path / "ws_homoglyph"
    workspace.mkdir(exist_ok=True)
    ws_str = str(workspace.resolve())

    try:
        result = ensure_within_workspace(ws_str, homoglyph)
        res_str = str(result.resolve())
        assert res_str.lower().startswith(ws_str.lower()), f"Escape via homoglyph '{homoglyph}': {res_str}"
    except (HTTPException, ValueError, OSError):
        pass


# 6. Valid child paths must succeed
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(subpath=st.from_regex(r"^[a-zA-Z0-9_\-\.]{1,20}(/[a-zA-Z0-9_\-\.]{1,20}){0,4}$", fullmatch=True))
def test_valid_safe_relative_paths_resolve_correctly(subpath, tmp_path):
    workspace = tmp_path / "ws_safe"
    workspace.mkdir(exist_ok=True)
    ws_str = str(workspace.resolve())

    # Skip empty or '.' or '..' components
    parts = subpath.split("/")
    if any(p in ("..", ".") for p in parts):
        return

    result = ensure_within_workspace(ws_str, subpath)
    res_str = str(result.resolve())
    assert res_str.lower().startswith(ws_str.lower())
    assert is_within_workspace(Path(ws_str), result) is True
