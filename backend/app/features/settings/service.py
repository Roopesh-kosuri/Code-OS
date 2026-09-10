from ...core.security import decrypt_secret, encrypt_secret
from ...db.database import get_db


async def list_settings() -> dict[str, str]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT key, value FROM settings")
    return {row["key"]: row["value"] for row in rows}


async def get_setting(key: str) -> str | None:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


async def store_api_key(provider_id: str, api_key: str) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO api_keys(provider_id, encrypted_key, updated_at)
        VALUES(?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(provider_id) DO UPDATE SET encrypted_key = excluded.encrypted_key, updated_at = CURRENT_TIMESTAMP
        """,
        (provider_id, encrypt_secret(api_key)),
    )
    if provider_id in ("nvidia-nim", "nvidia"):
        alt_id = "nvidia" if provider_id == "nvidia-nim" else "nvidia-nim"
        await db.execute(
            """
            INSERT INTO api_keys(provider_id, encrypted_key, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider_id) DO UPDATE SET encrypted_key = excluded.encrypted_key, updated_at = CURRENT_TIMESTAMP
            """,
            (alt_id, encrypt_secret(api_key)),
        )
    await db.commit()


async def get_api_key(provider_id: str) -> str | None:
    db = await get_db()
    aliases = [provider_id]
    if provider_id in ("nvidia-nim", "nvidia"):
        aliases = ["nvidia-nim", "nvidia"]
    for alias in aliases:
        cursor = await db.execute("SELECT encrypted_key FROM api_keys WHERE provider_id = ?", (alias,))
        row = await cursor.fetchone()
        if row and row["encrypted_key"]:
            return decrypt_secret(row["encrypted_key"])
    return None


async def list_api_key_status() -> list[dict[str, object]]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT provider_id FROM api_keys")
    return [{"provider_id": row["provider_id"], "configured": True} for row in rows]


async def clear_api_keys() -> None:
    db = await get_db()
    await db.execute("DELETE FROM api_keys")
    await db.commit()


async def clear_all_history() -> None:
    db = await get_db()
    await db.execute("DELETE FROM chat_threads")
    await db.execute("DELETE FROM duo_sessions")
    await db.execute("DELETE FROM agent_jobs")
    await db.commit()
