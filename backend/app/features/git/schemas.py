from pydantic import BaseModel, Field


class CommitRequest(BaseModel):
    workspace: str
    message: str
    # Optional at transport level so trust validation still runs before a
    # restricted workspace request is rejected; empty selections are rejected
    # by the manual commit service.
    files: list[str] = Field(default_factory=list)


class GitHubAuthRequest(BaseModel):
    token: str



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
