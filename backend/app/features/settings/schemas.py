from pydantic import BaseModel


class SettingDto(BaseModel):
    key: str
    value: str


class SettingUpdateRequest(BaseModel):
    key: str
    value: str


class ApiKeyRequest(BaseModel):
    provider_id: str
    api_key: str


class ApiKeyStatus(BaseModel):
    provider_id: str
    configured: bool


class MemoryUpdateRequest(BaseModel):
    workspace: str
    key: str
    value: str
