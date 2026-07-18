from fastapi import APIRouter, Query

from backend.app.features.settings.schemas import ApiKeyRequest, ApiKeyStatus, SettingDto, SettingUpdateRequest, MemoryUpdateRequest
from backend.app.features.settings.service import list_api_key_status, list_settings, set_setting, store_api_key, clear_api_keys, clear_all_history
from backend.app.features.settings.memory_service import get_all_memory, save_memory_key, clear_memory

router = APIRouter()


@router.get("", response_model=list[SettingDto])
async def settings() -> list[SettingDto]:
    values = await list_settings()
    return [SettingDto(key=key, value=value) for key, value in values.items()]


@router.post("")
async def update_setting(payload: SettingUpdateRequest) -> dict[str, str]:
    await set_setting(payload.key, payload.value)
    return {"status": "saved"}


@router.get("/api-keys", response_model=list[ApiKeyStatus])
async def api_keys() -> list[ApiKeyStatus]:
    return [ApiKeyStatus(**item) for item in await list_api_key_status()]


@router.post("/api-keys")
async def save_api_key(payload: ApiKeyRequest) -> dict[str, str]:
    await store_api_key(payload.provider_id, payload.api_key)
    return {"status": "saved"}


@router.delete("/api-keys")
async def delete_api_keys_route() -> dict[str, str]:
    await clear_api_keys()
    return {"status": "cleared"}


@router.delete("/history")
async def delete_history_route() -> dict[str, str]:
    await clear_all_history()
    return {"status": "cleared"}


@router.get("/memory")
async def get_memory(workspace: str = Query(...)) -> dict[str, str]:
    return await get_all_memory(workspace)


@router.post("/memory")
async def update_memory(payload: MemoryUpdateRequest) -> dict[str, str]:
    await save_memory_key(payload.workspace, payload.key, payload.value)
    return {"status": "saved"}


@router.delete("/memory")
async def delete_memory(workspace: str = Query(...)) -> dict[str, str]:
    await clear_memory(workspace)
    return {"status": "cleared"}
