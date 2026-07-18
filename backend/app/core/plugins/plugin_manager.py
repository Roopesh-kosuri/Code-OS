import json
import logging
from pathlib import Path
from pydantic import BaseModel
from typing import Dict, List, Optional
from backend.app.features.settings.service import list_settings, set_setting as save_setting

logger = logging.getLogger(__name__)

class PluginManifest(BaseModel):
    id: str
    name: str
    version: str
    description: str
    author: str
    entry: str
    permissions: List[str] = []

class PluginManager:
    def __init__(self, extensions_dir: Optional[Path] = None) -> None:
        if extensions_dir is None:
            self.extensions_dir = Path.home() / ".codeos" / "extensions"
        else:
            self.extensions_dir = extensions_dir
        self.extensions_dir.mkdir(parents=True, exist_ok=True)
        self.loaded_plugins: Dict[str, PluginManifest] = {}
        self.load_times: Dict[str, float] = {}

    def scan_plugins(self) -> List[PluginManifest]:
        plugins = []
        for path in self.extensions_dir.iterdir():
            if path.is_dir():
                manifest_path = path / "manifest.json"
                if manifest_path.is_file():
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            manifest = PluginManifest(**data)
                            plugins.append(manifest)
                    except Exception as exc:
                        logger.error("plugin_manager.scan failed to parse %s: %s", manifest_path, exc)
        return plugins

    async def load_active_plugins(self) -> None:
        self.loaded_plugins.clear()
        settings = await list_settings()
        all_plugins = self.scan_plugins()
        
        for p in all_plugins:
            # By default plugins are enabled unless explicitly disabled
            status_key = f"plugin_status_{p.id}"
            is_enabled = settings.get(status_key, "enabled") == "enabled"
            
            if is_enabled:
                self.loaded_plugins[p.id] = p
                logger.info("plugin_manager.load loaded plugin id=%s name=%s (version %s)", p.id, p.name, p.version)
                # Execute plugin initialization lifecycle stub
                self._initialize_plugin(p)

    async def enable_plugin(self, plugin_id: str) -> bool:
        all_plugins = self.scan_plugins()
        target = next((p for p in all_plugins if p.id == plugin_id), None)
        if not target:
            return False
            
        await save_setting(f"plugin_status_{plugin_id}", "enabled")
        self.loaded_plugins[plugin_id] = target
        self._initialize_plugin(target)
        logger.info("plugin_manager.enable plugin_id=%s enabled successfully", plugin_id)
        return True

    async def disable_plugin(self, plugin_id: str) -> bool:
        if plugin_id in self.loaded_plugins:
            target = self.loaded_plugins.pop(plugin_id)
            await save_setting(f"plugin_status_{plugin_id}", "disabled")
            self._unload_plugin(target)
            logger.info("plugin_manager.disable plugin_id=%s disabled successfully", plugin_id)
            return True
        return False

    def _initialize_plugin(self, manifest: PluginManifest) -> None:
        import time
        start_time = time.perf_counter()
        # Dynamic execution or sandboxed VM invocation goes here.
        # Currently, we print registration metrics to logs.
        logger.info("plugin.lifecycle [init] plugin_id=%s entry_point=%s", manifest.id, manifest.entry)
        
        # Simulate minor load time if needed, otherwise record actual
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        self.load_times[manifest.id] = round(max(duration_ms, 0.12), 2)

    def _unload_plugin(self, manifest: PluginManifest) -> None:
        logger.info("plugin.lifecycle [unload] plugin_id=%s", manifest.id)

plugin_manager = PluginManager()
