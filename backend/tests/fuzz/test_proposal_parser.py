"""
backend/tests/fuzz/test_proposal_parser.py
Fuzz testing target for LLM code diff proposal parsers.
Executes 10,000 random inputs including random bytes, unclosed fences,
oversized diffs, malformed headers, and control characters.
"""
import random
import string
import time
import pytest
from app.features.ai.service import extract_proposals_robust, parse_proposals_from_llm


def generate_fuzz_proposal_input() -> str:
    """Generate diverse and adversarial proposal text inputs."""
    choice = random.randint(1, 8)
    if choice == 1:
        # Random bytes/characters
        length = random.randint(0, 5000)
        return "".join(random.choices(string.printable + string.whitespace + "\x00\r\n\t", k=length))
    elif choice == 2:
        # Malformed proposal header
        p_tag = random.choice(["[PROPOSAL", "[PROPOSAL:", "[FILE", "###", "```python:", "```"])
        path = "".join(random.choices(string.ascii_letters + string.digits + "/._- \x00", k=random.randint(0, 100)))
        body = "".join(random.choices(string.printable, k=random.randint(0, 1000)))
        return f"{p_tag} {path}\n<<<< ORIGINAL\n{body}\n====\n{body}\n>>>>"
    elif choice == 3:
        # Partial / broken diff markers
        return (
            "[PROPOSAL: app/main.py]\n"
            + random.choice(["<<<< ORIGINAL", "====", ">>>>", "<<<<", "======", ">>>>>>", ""])
            + "\n"
            + "".join(random.choices(string.ascii_letters, k=500))
        )
    elif choice == 4:
        # Deeply repeating markers
        return "[PROPOSAL: test.py]\n" + ("<<<< ORIGINAL\n====\n>>>>\n" * random.randint(1, 100))
    elif choice == 5:
        # Unicode homoglyphs and multibyte characters
        chars = ["\u0430", "\u0440", "\u200B", "\u202E", "\U0001F600", "\uFFFF", "\u0000"]
        return "".join(random.choices(chars + list(string.ascii_letters), k=random.randint(1, 1000)))
    elif choice == 6:
        # Oversized single-line or multi-line payload
        return "A" * random.randint(5000, 20000)
    elif choice == 7:
        # Nested markdown code fences
        return "```markdown\n```python\ndef foo():\n```\n```"
    else:
        # Random empty or whitespace
        return " " * random.randint(0, 100)


def test_fuzz_proposal_parser_10000_inputs():
    """Fuzz proposal parser with 10,000 iterations without crashing or hanging."""
    start_time = time.time()
    for i in range(10000):
        fuzz_input = generate_fuzz_proposal_input()
        try:
            # 1. Test robust extractor
            proposals = extract_proposals_robust(fuzz_input, planned_files=["test.py", "app.py"])
            assert isinstance(proposals, list)

            # 2. Test LLM proposal parser returning (proposals, explanation)
            parsed_result = parse_proposals_from_llm(fuzz_input)
            assert isinstance(parsed_result, tuple)
            props, explanation = parsed_result
            assert isinstance(props, list)
            assert isinstance(explanation, str)
        except Exception as e:
            pytest.fail(f"Proposal parser crashed on input iteration {i}: {e!r} with payload {fuzz_input[:100]!r}")

    elapsed = time.time() - start_time
    assert elapsed < 30.0, f"Fuzz test took too long: {elapsed:.2f}s"
