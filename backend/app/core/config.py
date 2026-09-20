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
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
        # Align with Electron app.getPath("userData") which resolves to "code-os"
        cand_hyphen = base / "code-os"
        cand_under = base / "code_os"
        if cand_hyphen.exists() or not cand_under.exists():
            return cand_hyphen
        return cand_under
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        return (base / "code-os") if (base / "code-os").exists() else (base / "code_os")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return (base / "code-os") if (base / "code-os").exists() else (base / "code_os")


class Settings(BaseSettings):
    app_name: str = "CODE OS"
    data_dir: Path = Field(default_factory=get_user_data_dir)
    database_name: str = "code-os.sqlite3"
    encryption_key_name: str = "secret.key"
    ollama_base_url: str = "http://127.0.0.1:11434"
    strict_sandbox: bool = False
    use_semantic_rag: bool = True
    # Payload governor fail mode: 'conservative' (default: ceil(utf8_bytes/2) safe overestimate) or 'closed' (strict fail-closed)
    governor_fail_mode: str = "conservative"

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
