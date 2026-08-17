import asyncio
import sys
import httpx
sys.path.insert(0, r"D:\HTML\CODE OS\backend")
from app.features.settings.service import get_api_key

async def test_groq():
    key = await get_api_key("groq")
    for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]:
        for max_toks in [4096, 6000, 8192]:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": max_toks,
            }
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
                print(f"Model: {model}, max_tokens: {max_toks} -> Status: {r.status_code}")
                if r.status_code != 200:
                    print("Error:", r.text[:200])

if __name__ == "__main__":
    asyncio.run(test_groq())
