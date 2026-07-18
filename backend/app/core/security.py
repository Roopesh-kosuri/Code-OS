from cryptography.fernet import Fernet

from backend.app.core.config import get_settings


def _load_key() -> bytes:
    settings = get_settings()
    key_path = settings.encryption_key_path
    if key_path.exists():
        return key_path.read_bytes()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    return key


def encrypt_secret(value: str) -> str:
    return Fernet(_load_key()).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return Fernet(_load_key()).decrypt(value.encode("utf-8")).decode("utf-8")
