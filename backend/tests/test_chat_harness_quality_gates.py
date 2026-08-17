import pytest
import asyncio
import re
from unittest.mock import AsyncMock, patch, MagicMock

from app.features.ai.artifact_auditor import (
    audit_generated_artifact,
    _count_non_empty_non_comment_lines,
    ArtifactAuditReport,
)
from app.features.ai.chat_harness import (
    _should_audit_staged_changes,
    _CHAT_AGENT_SYSTEM_PROMPT,
    run_chat_agent,
    ChatAgentRequest,
)
from app.features.ai.schemas import FileChange


def test_system_prompt_contains_quality_standards():
    """Verify that system prompt permanently includes all 10 generation quality standards."""
    prompt = _CHAT_AGENT_SYSTEM_PROMPT
    assert "Permanent Generation Quality Standards" in prompt
    assert "No Padding / Filler" in prompt
    assert "Professional Iconography" in prompt
    assert "background-attachment: fixed" in prompt
    assert "Progressive Enhancement" in prompt
    assert "Working Interactivity" in prompt
    assert "Full Responsiveness" in prompt
    assert "prefers-reduced-motion" in prompt
    assert "Identity Consistency" in prompt
    assert "Post-Generation Structural Self-Audit" in prompt


def test_auditor_clean_html_artifact():
    """Verify that a compliant, well-formed HTML portfolio artifact passes the audit cleanly."""
    valid_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jane Doe — Senior Software Engineer</title>
    <style>
        :root { --primary: #2563eb; }
        body { margin: 0; font-family: system-ui, sans-serif; }
        .hero { min-height: 80vh; display: flex; align-items: center; justify-content: center; }
        html.js .reveal { opacity: 0; transform: translateY(20px); transition: all 0.6s ease; }
        html.js .reveal.visible { opacity: 1; transform: translateY(0); }
        @media (max-width: 768px) {
            .nav-menu { display: none; }
        }
        @media (prefers-reduced-motion: reduce) {
            * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
        }
    </style>
</head>
<body>
    <header>
        <nav>
            <a href="#about">About</a>
            <a href="#projects">Projects</a>
            <a href="#contact">Contact</a>
            <button id="theme-toggle" aria-label="Toggle dark mode">
                <svg viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="12" r="5"/></svg>
            </button>
        </nav>
    </header>
    <main>
        <section id="about" class="hero">
            <h1>Jane Doe</h1>
            <p>Building high performance systems.</p>
        </section>
        <section id="projects" class="reveal">
            <h2>Featured Projects</h2>
        </section>
        <section id="contact">
            <h2>Get In Touch</h2>
            <form id="contact-form">
                <input type="email" placeholder="Your email" required>
                <button type="submit">Send</button>
            </form>
        </section>
    </main>
    <footer>
        <p>© 2026 Jane Doe. All rights reserved.</p>
    </footer>
    <script>
        document.documentElement.classList.add('js');
        document.getElementById('theme-toggle').addEventListener('click', () => {
            document.body.classList.toggle('dark');
        });
        document.getElementById('contact-form').addEventListener('submit', (e) => {
            e.preventDefault();
            alert('Sent!');
        });
    </script>
</body>
</html>
"""
    report = audit_generated_artifact(valid_html, "portfolio.html")
    assert report.is_clean is True
    assert report.has_errors is False
    assert report.non_empty_non_comment_lines > 30
    assert any("HTML document structure" in p for p in report.passed_checks)
    assert any("DOM selectors" in p for p in report.passed_checks)


def test_auditor_detects_unclosed_tags_and_duplicate_doctypes():
    """Verify detection of unclosed tags and duplicated header/doctype chunk seams."""
    broken_html = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<div>
    <section id="main">
        <p>Unclosed section and div
</body>
</html>
"""
    report = audit_generated_artifact(broken_html, "broken.html")
    assert report.has_errors is True
    error_messages = [f.message for f in report.findings if f.severity == "error"]
    assert any("Unclosed tag" in msg for msg in error_messages)


def test_auditor_detects_broken_anchor_wiring():
    """Verify that href="#target" targeting a non-existent element ID is flagged as an error."""
    html_with_broken_anchor = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portfolio</title>
</head>
<body>
    <a href="#missing-section">Go to Missing</a>
    <section id="other-section"><h1>Hello</h1></section>
</body>
</html>
"""
    report = audit_generated_artifact(html_with_broken_anchor, "page.html")
    assert report.has_errors is True
    assert any("missing-section" in f.message for f in report.findings if f.severity == "error")


def test_auditor_detects_fixed_parallax_antipattern():
    """Verify that background-attachment: fixed is flagged as an error."""
    html_with_fixed_bg = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portfolio</title>
    <style>
        .hero { background-attachment: fixed; background-image: url('bg.jpg'); }
    </style>
</head>
<body><section id="s"><h1>Title</h1></section></body>
</html>
"""
    report = audit_generated_artifact(html_with_fixed_bg, "index.html")
    assert report.has_errors is True
    assert any("background-attachment: fixed" in f.message for f in report.findings)


def test_honest_line_count_calculation():
    """Verify honest line counting accurately strips blank lines, HTML comments, and CSS/JS comments."""
    sample = """
    <!-- This is an HTML header comment -->
    <!DOCTYPE html>
    
    /* Multiline CSS comment
       spanning multiple lines
    */
    
    <style>
        body { color: black; } // inline comment
    </style>
    
    <!-- Single line comment -->
    
    <div>Real content</div>
    """
    lines = sample.splitlines()
    honest_count = _count_non_empty_non_comment_lines(lines, "index.html")
    # Non-comment, non-empty lines: <!DOCTYPE html>, <style>, body { color: black; } // inline comment, </style>, <div>Real content</div>
    assert honest_count == 5


def test_should_audit_staged_changes_selection():
    """Verify that quality audit runs ONLY on creation/generation tasks and skips simple edits."""
    # Creation task (new file)
    c_new = FileChange(path="index.html", original="", updated="<!DOCTYPE html>...")
    assert _should_audit_staged_changes([c_new], "fix minor bug") is True

    # User query contains generation intent
    c_edit = FileChange(path="index.html", original="old", updated="new")
    assert _should_audit_staged_changes([c_edit], "create 1000+ line portfolio in index.html") is True

    # Simple targeted edit (not creation)
    assert _should_audit_staged_changes([c_edit], "fix spelling typo in header") is False


@pytest.mark.asyncio
async def test_quality_gate_repair_loop(tmp_path):
    """Verify that when structural errors exist, the harness initiates a repair turn before final approval."""
    workspace = str(tmp_path)

    turn_count = 0
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            # Turn 1: Emits HTML with broken anchor and unclosed tag, then attempts [DONE]
            broken = (
                "<!DOCTYPE html>\\n<html>\\n<head><title>Portfolio</title></head>\\n"
                "<body>\\n<a href=\\\"#projects\\\">Projects</a>\\n<div><h1>Hello</h1>\\n"
            )
            yield f"[TOOL_CALL: edit_file]\\n{{\"path\": \"index.html\", \"original\": \"\", \"updated\": \"{broken}\"}}\\n[/TOOL_CALL]\\n[DONE]"
        else:
            # Turn 2: Agent receives audit report feedback and fixes the errors with edit_file
            fixed = (
                "<!DOCTYPE html>\\n<html lang=\\\"en\\\">\\n<head>\\n"
                "<meta name=\\\"viewport\\\" content=\\\"width=device-width, initial-scale=1.0\\\">\\n"
                "<title>Portfolio</title>\\n</head>\\n"
                "<body>\\n<a href=\\\"#projects\\\">Projects</a>\\n"
                "<section id=\\\"projects\\\"><h1>Hello</h1></section>\\n"
                "</body>\\n</html>\\n"
            )
            yield f"I fixed the unclosed tag and added id='projects':\\n[TOOL_CALL: edit_file]\\n{{\"path\": \"index.html\", \"original\": \"\", \"updated\": \"{fixed}\"}}\\n[/TOOL_CALL]\\n[DONE]"

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="gpt-4o",
        workspace=workspace,
        messages=[{"role": "user", "content": "create a portfolio in index.html"}],
    )

    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)), \
         patch("app.features.ai.chat_harness.create_proposal", AsyncMock(return_value=MagicMock(id="prop-audit-1"))), \
         patch("app.features.ai.service.apply_proposal", AsyncMock()):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)
            # Auto-approve if approval requested during test
            if "approval_request" in event:
                match = re.search(r'"action_id":\s*"([^"]+)"', event)
                if match:
                    from app.features.ai.chat_harness import approve_action
                    await approve_action(match.group(1))

        # Check that post-generation structural audit was run and issues were reported
        status_messages = [e for e in events if "event: status" in e]
        assert any("structural audit" in s.lower() for s in status_messages)
        
        # Verify that turn 2 repaired the file and finalized successfully
        assert turn_count == 2
        done_events = [e for e in events if "event: done" in e]
        assert any('"success": true' in d or '"success":true' in d for d in done_events)
