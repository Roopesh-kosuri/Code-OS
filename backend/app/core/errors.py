from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from fastapi import Request
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    DISK_FULL = "DISK_FULL"
    DB_ERROR = "DB_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class AppError(Exception):
    """Standard application error with domain code and HTTP status code."""
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Global exception handler formatting AppError instances as standard JSON."""
    content = {
        "error": {
            "code": exc.code.value,
            "message": exc.message,
        },
        "detail": exc.message,
    }
    if exc.details:
        content["error"]["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=content)
