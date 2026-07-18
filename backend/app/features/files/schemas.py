from pydantic import BaseModel


class FileNode(BaseModel):
    name: str
    path: str
    type: str
    children: list["FileNode"] = []


class TreeResponse(BaseModel):
    root: FileNode


class FileReadResponse(BaseModel):
    path: str
    content: str
    language: str


class CreateRequest(BaseModel):
    workspace: str
    path: str
    type: str


class DeleteRequest(BaseModel):
    workspace: str
    path: str


class RenameRequest(BaseModel):
    workspace: str
    path: str
    new_name: str


class MoveRequest(BaseModel):
    workspace: str
    source: str
    destination: str


class DuplicateRequest(BaseModel):
    workspace: str
    path: str
    destination: str | None = None


class WriteRequest(BaseModel):
    workspace: str
    path: str
    content: str
