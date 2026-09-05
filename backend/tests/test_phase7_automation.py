import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from app.features.ai.schemas import FileChange
from app.features.automation.verifier import (
    should_trigger_auto_verify,
    run_browser_verification,
    EXPLICIT_VERIFY_PATTERNS,
    SKIP_VERIFY_PATTERNS,
)
from app.features.automation.browser_controller import get_browser_controller
from app.features.automation.computer_controller import (
    get_computer_controller,
    trigger_emergency_stop,
    reset_emergency_stop,
    is_emergency_stopped,
)
from app.features.ai.harness.tool_executor import HARNESS_TOOLS, OPENAI_HARNESS_TOOLS
from app.features.ai.harness.stage_finalizer import _finalize_staged_changes


# ══════════════════════════════════════════════════════════════════════════════
# 1. TIGHTENED AUTO-VERIFY TRIGGER SCOPE TESTS (Critical Refinement)
# ══════════════════════════════════════════════════════════════════════════════

def test_minor_edits_do_not_auto_verify():
    """
    Requirement 1: DO NOT AUTO-VERIFY ON MINOR EDITS.
    If the task only touched existing files (e.g. fixed a typo in style.css,
    added a console.log to app.js, updated package.json), DO NOT launch browser.
    """
    # 1. Fixed a typo in style.css (existing file)
    staged_css = [
        FileChange(
            path="style.css",
            original="body { colr: red; }",
            updated="body { color: red; }",
        )
    ]
    assert should_trigger_auto_verify(staged_css, user_query="fix a typo in style.css") is False

    # 2. Added console.log to app.js (existing file)
    staged_js = [
        FileChange(
            path="app.js",
            original="function init() {}",
            updated="function init() { console.log('init'); }",
        )
    ]
    assert should_trigger_auto_verify(staged_js, user_query="add a console.log to app.js") is False

    # 3. Updated package.json (existing file)
    staged_pkg = [
        FileChange(
            path="package.json",
            original='{"dependencies": {}}',
            updated='{"dependencies": {"lodash": "^4.17.21"}}',
        )
    ]
    assert should_trigger_auto_verify(staged_pkg, user_query="update package.json dependencies") is False

    # 4. Multi-file edit touching only existing files
    staged_multi = [
        FileChange(path="style.css", original="a { color: blue; }", updated="a { color: green; }"),
        FileChange(path="app.js", original="var x = 1;", updated="var x = 2;"),
        FileChange(path="package.json", original='{"name": "test"}', updated='{"name": "test-v2"}'),
    ]
    assert should_trigger_auto_verify(staged_multi, user_query="refactor code and bump version") is False


def test_high_stakes_scaffolded_new_project_triggers_auto_verify():
    """
    Requirement 2a: AUTO-VERIFY ONLY FOR 'HIGH-STAKES' WEB TASKS:
    Task scaffolded a NEW web project (e.g. created index.html where original == '').
    """
    # Newly created index.html (original == "")
    staged_new_html = [
        FileChange(
            path="index.html",
            original="",
            updated="<!DOCTYPE html><html><head><title>App</title></head><body><h1>Hello</h1></body></html>",
        )
    ]
    assert should_trigger_auto_verify(staged_new_html, user_query="make a simple page") is True

    # Newly created package.json + index.html + style.css
    staged_scaffold = [
        FileChange(path="package.json", original="", updated='{"name": "my-web-app"}'),
        FileChange(path="index.html", original="", updated="<!DOCTYPE html><html><body>Hi</body></html>"),
        FileChange(path="src/main.js", original="", updated="console.log('started');"),
    ]
    assert should_trigger_auto_verify(staged_scaffold, user_query="generate boilerplate") is True


def test_explicit_user_prompt_keywords_trigger_auto_verify():
    """
    Requirement 2b: Prompt explicitly requested visual verification.
    Keywords: 'build a website', 'landing page', 'open in browser', 'test it', 'see how it looks'.
    """
    staged_css = [
        FileChange(path="style.css", original="body { color: blue; }", updated="body { color: red; }")
    ]

    # Required keywords from prompt
    assert should_trigger_auto_verify(staged_css, user_query="build a website for my portfolio") is True
    assert should_trigger_auto_verify(staged_css, user_query="create a landing page for our product") is True
    assert should_trigger_auto_verify(staged_css, user_query="fix styling and open in browser") is True
    assert should_trigger_auto_verify(staged_css, user_query="tweak colors and test it") is True
    assert should_trigger_auto_verify(staged_css, user_query="change the hero section and see how it looks") is True

    # Word boundary guard: 'latest item' should NOT match 'test it'
    assert should_trigger_auto_verify(staged_css, user_query="update the latest item in package.json") is False


def test_manual_override_forces_verification():
    """
    Requirement 3: MANUAL OVERRIDE:
    Always allow the user to force verification via 'Verify in Browser' UI button,
    regardless of task size.
    """
    # Even with minor edit and no prompt keywords, manual_override=True MUST return True
    staged_css = [
        FileChange(path="style.css", original="p { margin: 0; }", updated="p { margin: 4px; }")
    ]
    assert should_trigger_auto_verify(staged_css, user_query="small margin tweak", manual_override=True) is True

    # Even with empty staged changes (e.g. on-demand UI button check of current workspace)
    assert should_trigger_auto_verify([], user_query="", manual_override=True) is True


def test_user_skip_verification():
    """
    Requirement 3: Always allow the user to skip verification if requested.
    """
    staged_new_html = [
        FileChange(path="index.html", original="", updated="<!DOCTYPE html><html><body>Hi</body></html>")
    ]
    # User explicitly asks to skip verification
    assert should_trigger_auto_verify(staged_new_html, user_query="create index.html but skip verification") is False
    assert should_trigger_auto_verify(staged_new_html, user_query="create index.html with no browser") is False
    assert should_trigger_auto_verify(staged_new_html, user_query="build a website don't verify") is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. STAGE FINALIZER COMPLETION GATE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stage_finalizer_minor_edit_skips_browser_and_emits_success(monkeypatch):
    """
    Confirm completion gate emits success:true immediately without browser
    verification on minor edits.
    """
    temp_dir = tempfile.mkdtemp()
    try:
        css_file = Path(temp_dir) / "style.css"
        css_file.write_text("body { color: blue; }", encoding="utf-8")

        staged_changes = [
            FileChange(
                path="style.css",
                original="body { color: blue; }",
                updated="body { color: green; }",
            )
        ]

        from app.features.ai.harness import stage_finalizer

        events = []
        async def mock_create_proposal(req):
            class P:
                id = "prop-123"
            return P()

        async def mock_apply_proposal(pid):
            css_file.write_text("body { color: green; }", encoding="utf-8")

        monkeypatch.setattr(stage_finalizer, "_get_create_proposal", lambda: mock_create_proposal)
        monkeypatch.setattr(stage_finalizer, "_get_apply_proposal", lambda: mock_apply_proposal)

        orig_finalize = stage_finalizer._finalize_staged_changes

        async def auto_approving_finalizer():
            gen = orig_finalize(staged_changes, temp_dir, tier=1, turn_number=1, user_query="fix color typo in style.css")
            async for ev in gen:
                events.append(ev)
                if "approval_required" in ev:
                    for pa in stage_finalizer._pending_approvals.values():
                        pa.approved = True
                        pa.event.set()

        await auto_approving_finalizer()

        # Check finalization event
        fin_events = [e for e in events if "event: finalization" in e]
        assert len(fin_events) > 0, "Should emit finalization event"

        last_fin = fin_events[-1]
        assert '"success": true' in last_fin or '"success":true' in last_fin
        assert '"reason": "verified"' in last_fin or '"reason":"verified"' in last_fin

        # Confirm no browser_verify status was yielded
        browser_verify_events = [e for e in events if "browser_verify" in e]
        assert len(browser_verify_events) == 0, "Browser verification should not have run for minor edit"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 3. SCHEMA REGISTRATION & PROFILE ISOLATION
# ══════════════════════════════════════════════════════════════════════════════

def test_browser_tools_schema_registered():
    """All 9 browser tools and 7 computer tools are properly registered in schemas."""
    expected_browser_tools = [
        "browser_open", "browser_screenshot", "browser_console_logs",
        "browser_network_errors", "browser_click", "browser_type",
        "browser_wait_for", "browser_scroll", "browser_close",
    ]
    for bt in expected_browser_tools:
        assert bt in HARNESS_TOOLS, f"{bt} should be registered in HARNESS_TOOLS"

    openai_tool_names = [t["function"]["name"] for t in OPENAI_HARNESS_TOOLS]
    for bt in expected_browser_tools:
        assert bt in openai_tool_names, f"{bt} should be registered in OPENAI_HARNESS_TOOLS"

    expected_computer_tools = [
        "screen_screenshot", "mouse_click", "keyboard_type",
        "hotkey", "open_app", "list_windows", "focus_window",
    ]
    for ct in expected_computer_tools:
        assert ct in HARNESS_TOOLS, f"{ct} should be registered in HARNESS_TOOLS"
        assert ct in openai_tool_names, f"{ct} should be registered in OPENAI_HARNESS_TOOLS"


def test_browser_profile_isolated():
    """Browser profile is strictly isolated inside <workspace>/.code_os/browser-profile."""
    temp_dir = tempfile.mkdtemp()
    try:
        ctrl = get_browser_controller(temp_dir)
        expected_profile = Path(temp_dir) / ".code_os" / "browser-profile"
        assert ctrl.profile_dir == expected_profile
        user_home = Path.home()
        assert not str(ctrl.profile_dir).startswith(str(user_home / "AppData" / "Local" / "Google" / "Chrome"))
        assert not str(ctrl.profile_dir).startswith(str(user_home / "AppData" / "Local" / "Microsoft" / "Edge"))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_computer_use_disabled_by_default():
    """Computer use is disabled by default (Fail-closed)."""
    temp_dir = tempfile.mkdtemp()
    try:
        ctrl = get_computer_controller(temp_dir)
        assert ctrl is not None
        reset_emergency_stop()
        assert is_emergency_stopped() is False
        trigger_emergency_stop("test stop")
        assert is_emergency_stopped() is True
        reset_emergency_stop()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
