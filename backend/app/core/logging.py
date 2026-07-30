import contextvars
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from typing import Any, Dict

# ContextVar for tracing request_id across async context
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


class JSONLogFormatter(logging.Formatter):
    """Production JSON log formatter for structured log analysis."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        # Request ID tracing
        req_id = getattr(record, "request_id", None) or request_id_var.get(None)
        if req_id:
            log_data["request_id"] = req_id

        # Contextual extra fields if present
        for field in ("workspace", "provider", "model", "duration_ms", "error_type"):
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        # Exception traceback serialization
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def configure_logging(log_level: int = logging.INFO) -> None:
    """Initialize structured logging with console output and rotating JSON file output."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers to prevent duplicate logs
    root_logger.handlers.clear()

    # 1. Console Handler (human-readable format for development)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 2. File Handler (JSON-structured rotating file log for production debugging)
    log_dir = Path.home() / ".code-os" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "code-os.log"
        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(JSONLogFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
        root_logger.addHandler(file_handler)
    except Exception as exc:
        console_handler.handle(
            logging.LogRecord(
                "logging",
                logging.WARNING,
                __file__,
                55,
                f"Could not create file log handler at {log_dir}: {exc}",
                (),
                None,
            )
        )

    # 3. Quiet noisy third-party libraries
    noisy_loggers = ["httpx", "httpcore", "watchdog", "asyncio", "urllib3", "aiosqlite"]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
