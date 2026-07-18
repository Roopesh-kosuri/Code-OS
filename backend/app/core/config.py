from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CODE OS"
    data_dir: Path = Path.home() / ".code-os"
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
