from pydantic import BaseModel


class FileSearchResult(BaseModel):
    path: str
    name: str


class TextMatch(BaseModel):
    path: str
    line: int
    column: int = 0
    preview: str


class ReplaceRequest(BaseModel):
    workspace: str
    query: str
    replacement: str
    apply: bool = False
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False


class ReplaceResult(BaseModel):
    path: str
    replacements: int


class SymbolResult(BaseModel):
    path: str
    line: int
    symbol: str
    kind: str


class SemanticSearchResult(BaseModel):
    path: str
    relative_path: str
    language: str
    score: float
