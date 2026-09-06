import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_user_data_dir() -> Path:
    """Dynamically resolve user-writable data directory based on OS standards."""
    override = os.environ.get("CODE_OS_DATA_DIR") or os.environ.get("CODE_OS_HOME")
    if override:
        return Path(override)

    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "code_os"
        return Path.home() / "AppData" / "Roaming" / "code_os"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "code_os"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "code_os"
        return Path.home() / ".config" / "code_os"


class Settings(BaseSettings):
    app_name: str = "CODE OS"
    data_dir: Path = Field(default_factory=get_user_data_dir)
    database_name: str = "code-os.sqlite3"
    encryption_key_name: str = "secret.key"
    ollama_base_url: str = "http://127.0.0.1:11434"

    model_config = SettingsConfigDict(env_prefix="CODE_OS_")

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_name

    @property
    def encryption_key_path(self) -> Path:
        return self.data_dir / self.encryption_key_name


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
