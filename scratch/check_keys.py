import asyncio
import sys
sys.path.insert(0, r"D:\HTML\CODE OS\backend")
from app.features.settings.service import list_settings, get_api_key
from app.db.database import get_db

async def check():
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM api_keys")
    print("API KEYS in DB:")
    for r in rows:
        print(dict(r))
    settings = await list_settings()
    print("SETTINGS:", settings)

if __name__ == "__main__":
    asyncio.run(check())
