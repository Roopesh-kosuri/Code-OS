from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any
from pathlib import Path
import json

from backend.app.core.plugins.plugin_manager import plugin_manager, PluginManifest

router = APIRouter()

class InstallRequest(BaseModel):
    plugin_id: str

@router.get("", response_model=List[Dict[str, Any]])
async def list_plugins():
    all_plugins = plugin_manager.scan_plugins()
    result = []
    for p in all_plugins:
        result.append({
            "id": p.id,
            "name": p.name,
            "version": p.version,
            "description": p.description,
            "author": p.author,
            "entry": p.entry,
            "permissions": p.permissions,
            "enabled": p.id in plugin_manager.loaded_plugins
        })
    return result

@router.post("/{plugin_id}/enable")
async def enable_plugin(plugin_id: str):
    success = await plugin_manager.enable_plugin(plugin_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id} not found or could not be enabled")
    return {"status": "ok", "message": f"Plugin {plugin_id} enabled"}

@router.post("/{plugin_id}/disable")
async def disable_plugin(plugin_id: str):
    success = await plugin_manager.disable_plugin(plugin_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id} not found or could not be disabled")
    return {"status": "ok", "message": f"Plugin {plugin_id} disabled"}

@router.post("/install")
async def install_plugin(req: InstallRequest):
    plugin_id = req.plugin_id
    if not plugin_id.isalnum() and "_" not in plugin_id and "-" not in plugin_id:
        raise HTTPException(status_code=400, detail="Invalid plugin ID format")
    
    # Create the directory under extensions
    plugin_dir = plugin_manager.extensions_dir / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    
    # Create mock files
    manifest = {
        "id": plugin_id,
        "name": f"Extension {plugin_id.replace('_', ' ').title()}",
        "version": "1.0.0",
        "description": f"Enables custom functionality for {plugin_id.replace('_', ' ')}.",
        "author": "Marketplace Developer",
        "entry": "index.py",
        "permissions": ["workspace_access"]
    }
    
    manifest_path = plugin_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        
    entry_path = plugin_dir / "index.py"
    with open(entry_path, "w", encoding="utf-8") as f:
        f.write(f'# {plugin_id} entry point\n\ndef initialize(api):\n    print("{plugin_id} plugin initialized")\n')
        
    # Reload/load active plugins to include this newly installed one
    await plugin_manager.load_active_plugins()
    
    return {"status": "ok", "message": f"Plugin {plugin_id} installed successfully"}
