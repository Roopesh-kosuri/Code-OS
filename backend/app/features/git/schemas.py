from pydantic import BaseModel


class CommitRequest(BaseModel):
    workspace: str
    message: str


class BranchSwitchRequest(BaseModel):
    workspace: str
    branch: str


class BranchCreateRequest(BaseModel):
    workspace: str
    branch: str
    checkout: bool = True


class GitStatusResponse(BaseModel):
    branch: str
    dirty: bool
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]
    branches: list[str] = []


class DiffResponse(BaseModel):
    diff: str


class CommitHistoryItem(BaseModel):
    sha: str
    message: str
    author: str
    committed_at: str
