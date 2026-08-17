"""
verify_hello_html_chunking.py — Full simulation of chunked 1000+ line portfolio generation.
"""
import asyncio
import os
import re
from pathlib import Path
from app.features.ai.chat_harness import (
    run_chat_agent,
    ChatAgentRequest,
    approve_action,
)
from app.features.ai.schemas import FileChange

async def run_simulation():
    test_ws = Path("D:/HTML/CODE OS/test_simulation_ws")
    test_ws.mkdir(parents=True, exist_ok=True)
    target_file = test_ws / "hello.html"
    if target_file.exists():
        target_file.unlink()

    # Generate 4 chunks: ~280 lines each totaling > 1100 lines
    chunk1_lines = ["<!DOCTYPE html>", "<html lang='en'>", "<head>", "<meta charset='UTF-8'>", "<title>Grand Portfolio</title>", "<style>"]
    for i in range(270):
        chunk1_lines.append(f"  .hero-element-{i} {{ color: hsl({i * 3 % 360}, 80%, 60%); padding: 4px; }}")
    chunk1_lines.append("</style></head>")
    chunk1 = "\n".join(chunk1_lines) + "\n"

    chunk2_lines = ["<body>", "<header class='site-header'>", "<h1>John Doe - Senior Systems Architect</h1>", "</header>", "<main>"]
    for i in range(280):
        chunk2_lines.append(f"  <section id='project-{i}' class='project-card'><h3>Project {i}</h3><p>Enterprise scalable system design.</p></section>")
    chunk2 = "\n".join(chunk2_lines) + "\n"

    chunk3_lines = ["<section id='skills' class='skills-grid'>"]
    for i in range(280):
        chunk3_lines.append(f"  <div class='skill-item'>Skill {i}: Python, TypeScript, Distributed Consensus</div>")
    chunk3_lines.append("</section></main>")
    chunk3 = "\n".join(chunk3_lines) + "\n"

    chunk4_lines = ["<script>"]
    for i in range(270):
        chunk4_lines.append(f"  function handleInteraction{i}() {{ console.log('Interactive element {i} initialized'); }}")
    chunk4_lines.extend(["</script>", "<footer><p>&copy; 2026 Architect Portfolio</p></footer>", "</body>", "</html>"])
    chunk4 = "\n".join(chunk4_lines) + "\n"

    turn = 0
    from unittest.mock import MagicMock
    mock_provider = MagicMock()
    async def mock_stream(*args, **kwargs):
        nonlocal turn
        turn += 1
        if turn == 1:
            # Turn 1: Attempted monolithic output that cuts off
            yield "I will create hello.html with a full 1000+ line portfolio.\n[TOOL_CALL: edit_file]\n{\"path\": \"hello.html\", \"original\": \"\", \"updated\": \"" + chunk1[:150]
            yield "\n[TRUNCATED: length]\n"
        elif turn == 2:
            # Turn 2: Follows recovery prompt -> Part 1
            escaped1 = chunk1.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            yield f"Here is Part 1 with styles:\n[TOOL_CALL: edit_file]\n{{\"path\": \"hello.html\", \"original\": \"\", \"updated\": \"{escaped1}\"}}\n[/TOOL_CALL]\n"
        elif turn == 3:
            # Turn 3: Part 2
            escaped2 = chunk2.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            yield f"Here is Part 2 with projects:\n[TOOL_CALL: append_file]\n{{\"path\": \"hello.html\", \"content\": \"{escaped2}\"}}\n[/TOOL_CALL]\n"
        elif turn == 4:
            # Turn 4: Part 3
            escaped3 = chunk3.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            yield f"Here is Part 3 with skills:\n[TOOL_CALL: append_file]\n{{\"path\": \"hello.html\", \"content\": \"{escaped3}\"}}\n[/TOOL_CALL]\n"
        else:
            # Turn 5: Part 4 and done
            escaped4 = chunk4.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            yield f"Here is Part 4 with scripts and footer:\n[TOOL_CALL: append_file]\n{{\"path\": \"hello.html\", \"content\": \"{escaped4}\"}}\n[/TOOL_CALL]\nI have created hello.html with 1100+ lines across 4 verified chunks. [DONE]"

    mock_provider.stream_chat = mock_stream

    req = ChatAgentRequest(
        provider="openai-compatible",
        model="gpt-4o",
        workspace=str(test_ws),
        messages=[{"role": "user", "content": "create hello.html, 1000+ line portfolio"}],
    )

    from unittest.mock import patch, AsyncMock
    with patch("app.features.ai.chat_harness.provider_for", AsyncMock(return_value=mock_provider)):
        events = []
        async for event in run_chat_agent(req):
            events.append(event)
            if "approval_request" in event:
                match = re.search(r'"action_id":\s*"([^"]+)"', event)
                if match:
                    await approve_action(match.group(1))

    assert target_file.exists(), "hello.html was not written to disk!"
    content = target_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    print(f"SUCCESS: hello.html created on disk with {len(lines)} lines!")
    assert len(lines) >= 1000, f"Expected 1000+ lines, got {len(lines)}"
    assert "<!DOCTYPE html>" in content
    assert "</html>" in content
    print("Verification completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_simulation())
