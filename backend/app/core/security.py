import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
import keyring

from .config import get_settings

logger = logging.getLogger(__name__)

SERVICE_NAME = "code-os"
KEY_NAME = "fernet-master-key"

_fernet_instance: Optional[Fernet] = None


def _secure_file_permissions(file_path: Path) -> None:
    """Set 600 permissions on Unix systems."""
    if os.name != "nt":
        try:
            os.chmod(file_path, 0o600)
        except Exception as exc:
            logger.warning("Failed to set 600 permissions on %s: %s", file_path, exc)


def _load_or_create_key() -> bytes:
    """
    Retrieve Fernet master key from OS keyring, migrating from legacy file if needed,
    or generating a fresh key. Falls back to secure file with 600 permissions.
    """
    settings = get_settings()
    key_path = settings.encryption_key_path

    # 1. Try retrieving key from OS keyring
    try:
        stored_key = keyring.get_password(SERVICE_NAME, KEY_NAME)
        if stored_key:
            # If key file exists, ensure permissions are 600
            if key_path.exists():
                _secure_file_permissions(key_path)
            return stored_key.encode("utf-8")
    except Exception as exc:
        logger.warning("Keyring get_password failed: %s", exc)

    # 2. Migration path: check for legacy plaintext key file
    if key_path.exists():
        try:
            key_bytes = key_path.read_bytes().strip()
            _secure_file_permissions(key_path)
            # Migrate key to OS keyring
            try:
                keyring.set_password(SERVICE_NAME, KEY_NAME, key_bytes.decode("utf-8"))
            except Exception as exc:
                logger.warning("Keyring migration set_password failed: %s", exc)
            return key_bytes
        except Exception as exc:
            logger.warning("Failed reading key file %s: %s", key_path, exc)

    # 3. Generate new key
    new_key = Fernet.generate_key()
    new_key_str = new_key.decode("utf-8")

    try:
        keyring.set_password(SERVICE_NAME, KEY_NAME, new_key_str)
    except Exception as exc:
        logger.warning("Keyring set_password failed: %s", exc)

    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(new_key)
        _secure_file_permissions(key_path)
    except Exception as exc:
        logger.warning("Failed writing key file %s: %s", key_path, exc)

    return new_key


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        key = _load_or_create_key()
        _fernet_instance = Fernet(key)
    return _fernet_instance


def reset_fernet_cache() -> None:
    """Reset cached Fernet instance (used in tests)."""
    global _fernet_instance
    _fernet_instance = None


def encrypt_secret(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
