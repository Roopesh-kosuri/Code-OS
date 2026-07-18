from pydantic import BaseModel


class WorkspaceOpenRequest(BaseModel):
    path: str


class WorkspaceDto(BaseModel):
    path: str
    name: str
    last_opened_at: str


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceDto]
    last_workspace: WorkspaceDto | None = None
