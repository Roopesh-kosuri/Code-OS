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


class RunRequest(BaseModel):
    workspace: str
    file_path: str
    args: list[str] | None = None


class RunKillRequest(BaseModel):
    run_id: str


class ToolchainInfo(BaseModel):
    id: str
    name: str
    installed: bool
    version: str | None = None
    command_path: str | None = None
    compile_command_path: str | None = None
    install_hint: str = ""
    error_message: str | None = None


class ToolchainsResponse(BaseModel):
    toolchains: list[ToolchainInfo]

