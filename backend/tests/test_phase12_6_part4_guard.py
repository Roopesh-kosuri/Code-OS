import pytest
from pathlib import Path
from app.features.ai.harness.content_integrity import validate_language_syntax


# ============================================================================
# Z0 — COMMENT-ONLY .ts FALSE-POSITIVE CHECK
# ============================================================================

def test_comment_only_ts_file_not_flagged_as_prose():
    """A .ts file consisting only of line comments must be ALLOWED, both with empty original and matching original."""
    content = "// this is the file for the config\n// the settings will be added here\n"
    
    # original = ""
    ok_empty, err_empty = validate_language_syntax("config.ts", content, original_content="")
    assert ok_empty is True, f"Failed with empty original: {err_empty}"
    assert err_empty == ""

    # original = same content
    ok_same, err_same = validate_language_syntax("config.ts", content, original_content=content)
    assert ok_same is True, f"Failed with matching original: {err_same}"
    assert err_same == ""


def test_block_comment_only_js_file_not_flagged_as_prose():
    """A .js file consisting only of a block comment must be ALLOWED."""
    content = "/* This file is the entry point.\n   It will export the app. */\n"
    ok, err = validate_language_syntax("index.js", content, original_content="")
    assert ok is True, f"Failed on block comment: {err}"
    assert err == ""


def test_json_like_ts_with_only_brackets_not_flagged():
    """A .ts file consisting of a bracketed array/list structure must be ALLOWED."""
    content = '[\n  "a",\n  "b"\n]\n'
    ok, err = validate_language_syntax("list.ts", content, original_content="")
    assert ok is True, f"Failed on bracketed array: {err}"
    assert err == ""


def test_conversational_prose_still_rejected_after_fix():
    """Raw conversational prose without code syntax or comments into a .ts file must be REJECTED."""
    content = "Here is the code you requested to handle authentication.\n"
    ok, err = validate_language_syntax("auth.ts", content, original_content="")
    assert ok is False
    assert "conversational prose" in err


def test_prose_with_comment_marker_prefix_still_rejected():
    """A comment on line 1 must not launder conversational prose on line 2."""
    content = "// Here is the code you requested\nSure, I can help with that.\n"
    ok, err = validate_language_syntax("auth.ts", content, original_content="")
    assert ok is False
    assert "conversational prose" in err
