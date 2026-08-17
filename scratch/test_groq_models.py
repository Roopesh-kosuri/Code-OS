import asyncio
import sys
import httpx
sys.path.insert(0, r"D:\HTML\CODE OS\backend")
from app.features.settings.service import get_api_key

async def test_models():
    key = await get_api_key("groq")
    print(f"Groq Key found: {bool(key)}")
    if not key:
        return
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.groq.com/openai/v1/models", headers=headers)
        print("Status:", r.status_code)
        if r.status_code == 200:
            models = [m["id"] for m in r.json().get("data", [])]
            print("Groq models:", models)

if __name__ == "__main__":
    asyncio.run(test_models())
