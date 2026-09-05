"""
backend/tests/fuzz/test_json_extractor.py
Fuzz testing target for AI response JSON extractors.
Executes 10,000 random inputs including deeply nested JSON, malformed syntax,
truncated buffers, and prose-wrapped payloads.
"""
import json
import random
import string
import time
import pytest
from app.features.duo.service import _extract_json
from app.features.mcp.scanner import mcp_scanner


def generate_fuzz_json_input() -> str:
    choice = random.randint(1, 8)
    if choice == 1:
        # Arbitrary random strings
        return "".join(random.choices(string.printable + "\x00\r\n\t", k=random.randint(0, 3000)))
    elif choice == 2:
        # Deeply nested brackets
        depth = random.randint(10, 300)
        return ("{\"nested\": " * depth) + "1" + ("}" * depth)
    elif choice == 3:
        # Markdown fenced JSON with malformed body
        fence = random.choice(["```json", "```", "```JSON", "```javascript"])
        body = "".join(random.choices(string.printable, k=random.randint(10, 500)))
        return f"Here is the result:\n{fence}\n{body}\n```\nHope this helps!"
    elif choice == 4:
        # Truncated valid JSON
        valid = json.dumps({"status": "ok", "items": [1, 2, 3, {"name": "test"}], "message": "hello"})
        cut = random.randint(1, len(valid) - 1)
        return valid[:cut]
    elif choice == 5:
        # JSON with unescaped control chars and unicode
        return "{\"key\": \"value\x00with\r\nnewlines\", \"unicode\": \"\uD83D\uDE00\"}"
    elif choice == 6:
        # Array instead of object or primitive values
        return random.choice(["[1, 2, 3]", "\"just a string\"", "12345", "true", "null", "{}"])
    elif choice == 7:
        # Multiple top-level JSON objects
        return '{"obj1": 1} {"obj2": 2} {"obj3": 3}'
    else:
        # Massive string key/value
        return json.dumps({"huge": "X" * random.randint(1000, 10000)})


def test_fuzz_json_extractor_10000_inputs():
    """Fuzz JSON extractor with 10,000 iterations without crashing or hanging."""
    start_time = time.time()
    for i in range(10000):
        fuzz_input = generate_fuzz_json_input()
        try:
            # 1. Test duo JSON extractor (gracefully handles malformed via ValueError)
            try:
                result_duo = _extract_json(fuzz_input)
                assert isinstance(result_duo, dict)
            except ValueError:
                pass  # Graceful rejection of non-JSON text is expected

            # 2. Test MCP scanner JSON content parser
            try:
                parsed = json.loads(fuzz_input)
            except Exception:
                parsed = fuzz_input
            result_mcp = mcp_scanner.scan_json_content(parsed)
            assert isinstance(result_mcp, list)
        except Exception as e:
            pytest.fail(f"JSON extractor crashed unexpectedly on input iteration {i}: {e!r} with payload {fuzz_input[:100]!r}")

    elapsed = time.time() - start_time
    assert elapsed < 30.0, f"Fuzz test took too long: {elapsed:.2f}s"
