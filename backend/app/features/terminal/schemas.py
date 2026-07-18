from pydantic import BaseModel


class TerminalCreateRequest(BaseModel):
    cwd: str
    shell: str | None = None


class TerminalCommandRequest(BaseModel):
    command: str
    background: bool = False


class TerminalRenameRequest(BaseModel):
    name: str


class TerminalSessionDto(BaseModel):
    id: str
    name: str
    cwd: str
    shell: str


class CommandResult(BaseModel):
    output: str
    exit_code: int | None
    background: bool
    cwd: str
