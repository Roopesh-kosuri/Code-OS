from pydantic import BaseModel


class IndexStatusDto(BaseModel):
    workspace: str
    status: str
    message: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    total_files: int = 0
    indexed_files: int = 0
    changed_files: int = 0
    project_type: str = "unknown"
    language_summary: dict[str, int] = {}
    frameworks: list[str] = []
    entry_points: list[str] = []


class SymbolDto(BaseModel):
    path: str
    name: str
    kind: str
    language: str
    line: int
    column: int = 1
    signature: str = ""
    parent: str | None = None


class IndexedFileDto(BaseModel):
    path: str
    relative_path: str
    language: str
    size: int
    symbol_count: int
    imports: list[str]


class DependencyDto(BaseModel):
    name: str
    version: str | None = None
    source: str


class IndexSummaryDto(BaseModel):
    status: IndexStatusDto | None
    files: list[IndexedFileDto]
    symbols: list[SymbolDto]
    dependencies: list[DependencyDto]
