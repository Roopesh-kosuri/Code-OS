"""
backend/tests/fuzz/test_url_extractor.py
Fuzz testing target for URL extraction from user messages.
Executes 10,000 random inputs including weird schemes, unicode characters,
extremely long URLs, and malformed strings.
"""
import random
import string
import time
import pytest
from app.features.ai.url_fetcher import extract_user_urls


def generate_fuzz_url_input() -> str:
    choice = random.randint(1, 7)
    if choice == 1:
        # Random string with URL-like components
        return "".join(random.choices(string.printable + "\x00\n\t", k=random.randint(0, 2000)))
    elif choice == 2:
        # Malformed scheme and domain
        scheme = random.choice(["http://", "https://", "ftp://", "file://", "javascript:", "data:", "ws://", ""])
        host = "".join(random.choices(string.ascii_letters + string.digits + ".-_:", k=random.randint(1, 100)))
        path = "".join(random.choices(string.ascii_letters + string.digits + "/?&=%#@!", k=random.randint(0, 500)))
        return f"Check this out: {scheme}{host}/{path} and also {host}.com/test"
    elif choice == 3:
        # Extremely long URL
        return "https://example.com/" + ("a" * random.randint(1000, 10000))
    elif choice == 4:
        # Punctuation edge cases
        return "http://example.com/foo.,;!?()[]{}<> http://test.org:8080/path?q=1&b=2"
    elif choice == 5:
        # Unicode domain and paths
        return "https://\u4f60\u597d.com/\u4e16\u754c?name=\u0430dmin"
    elif choice == 6:
        # Multiple URLs packed together
        return " ".join([f"http://site{i}.com/{random.randint(1,100)}" for i in range(random.randint(5, 50))])
    else:
        # Null bytes and control characters
        return "https://evil.com/\x00/hidden\r\nAttack: true"


def test_fuzz_url_extractor_10000_inputs():
    """Fuzz URL extractor with 10,000 iterations without crashing or hanging."""
    start_time = time.time()
    for i in range(10000):
        fuzz_input = generate_fuzz_url_input()
        try:
            urls = extract_user_urls(fuzz_input)
            assert isinstance(urls, list)
            for u in urls:
                assert isinstance(u, str)
        except Exception as e:
            pytest.fail(f"URL extractor crashed on input iteration {i}: {e!r} with payload {fuzz_input[:100]!r}")

    elapsed = time.time() - start_time
    assert elapsed < 30.0, f"Fuzz test took too long: {elapsed:.2f}s"
