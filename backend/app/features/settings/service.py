from backend.app.core.security import decrypt_secret, encrypt_secret
from backend.app.db.database import get_connection


async def list_settings() -> dict[str, str]:
    db = await get_connection()
    try:
        rows = await db.execute_fetchall("SELECT key, value FROM settings")
    finally:
        await db.close()
    return {row["key"]: row["value"] for row in rows}


async def set_setting(key: str, value: str) -> None:
    db = await get_connection()
    try:
        await db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def store_api_key(provider_id: str, api_key: str) -> None:
    db = await get_connection()
    try:
        await db.execute(
            """
            INSERT INTO api_keys(provider_id, encrypted_key, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider_id) DO UPDATE SET encrypted_key = excluded.encrypted_key, updated_at = CURRENT_TIMESTAMP
            """,
            (provider_id, encrypt_secret(api_key)),
        )
        await db.commit()
    finally:
        await db.close()


async def get_api_key(provider_id: str) -> str | None:
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT encrypted_key FROM api_keys WHERE provider_id = ?", (provider_id,))
        row = await cursor.fetchone()
    finally:
        await db.close()
    return decrypt_secret(row["encrypted_key"]) if row else None


async def list_api_key_status() -> list[dict[str, object]]:
    db = await get_connection()
    try:
        rows = await db.execute_fetchall("SELECT provider_id FROM api_keys")
    finally:
        await db.close()
    return [{"provider_id": row["provider_id"], "configured": True} for row in rows]


async def clear_api_keys() -> None:
    db = await get_connection()
    try:
        await db.execute("DELETE FROM api_keys")
        await db.commit()
    finally:
        await db.close()


async def clear_all_history() -> None:
    db = await get_connection()
    try:
        await db.execute("DELETE FROM chat_threads")
        await db.execute("DELETE FROM duo_sessions")
        await db.execute("DELETE FROM agent_jobs")
        await db.commit()
    finally:
        await db.close()

