from __future__ import annotations

import json
import logging
from typing import Any
from .middleware import request_id_var


class StructuredFormatter(logging.Formatter):
    """JSON log formatter that includes timestamp, level, logger, message, and request_id."""
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(""),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def get_structured_formatter() -> StructuredFormatter:
    return StructuredFormatter(datefmt="%Y-%m-%dT%H:%M:%S")
