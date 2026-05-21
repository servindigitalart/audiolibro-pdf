"""
Sonoro Logging Configuration
============================
Structured logging setup for development and production.
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict

from app.core.config import settings


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging in production.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data["extra"] = record.extra_data

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """
    Colored formatter for better readability in development.
    """

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging() -> None:
    """
    Configure application logging based on environment.
    """
    # Get log level from settings
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Choose formatter based on environment
    if settings.log_format == "json" and settings.is_production:
        formatter = JSONFormatter()
    else:
        formatter = ColoredFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # Suppress chatty third-party loggers. sqlalchemy.engine would flood Railway
    # logs with a SELECT per poll tick if APP_ENV were ever set incorrectly.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    # Create app logger
    logger = logging.getLogger("sonoro")
    logger.setLevel(log_level)

    logger.info(
        f"Logging configured: level={settings.log_level}, format={settings.log_format}, env={settings.app_env}"
    )


# Python's LogRecord reserves these attribute names.
# Passing any of them inside extra={} raises KeyError at runtime.
# Use safe_extra() below when building extra= dicts for stdlib logger calls.
_RESERVED_LOG_KEYS = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
    "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "thread", "threadName",
})

_STDLIB_LOG_KWARGS = frozenset({"exc_info", "stack_info", "stacklevel"})


def safe_extra(d: dict) -> dict:
    """
    Sanitize an extra= dict for stdlib logger calls.
    Any key that collides with a reserved LogRecord attribute is prefixed with
    'log_' to prevent KeyError: "Attempt to overwrite '...' in LogRecord".
    """
    return {(f"log_{k}" if k in _RESERVED_LOG_KEYS else k): v for k, v in d.items()}


class BoundLogger:
    """
    Thin wrapper that lets callers pass structured fields as keyword arguments,
    matching the structlog calling convention without requiring structlog.

    Example:
        logger.warning("rate_limit_exceeded", user_id=uid, tier=tier)
        logger.error("something broke", exc_info=True)
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _split(self, kwargs: dict) -> tuple[str, dict]:
        """Split kwargs into (rendered structured fields string, stdlib log kwargs)."""
        stdlib_kw = {k: v for k, v in kwargs.items() if k in _STDLIB_LOG_KWARGS}
        struct_kw = {k: v for k, v in kwargs.items() if k not in _STDLIB_LOG_KWARGS}
        rendered = " ".join(f"{k}={v!r}" for k, v in struct_kw.items())
        return rendered, stdlib_kw

    def _emit(self, level: int, msg: str, kwargs: dict) -> None:
        if not self._logger.isEnabledFor(level):
            return
        extra, stdlib_kw = self._split(kwargs)
        full_msg = f"{msg} {extra}" if extra else msg
        self._logger.log(level, full_msg, **stdlib_kw)

    def debug(self, msg: str, **kwargs) -> None:
        self._emit(logging.DEBUG, msg, kwargs)

    def info(self, msg: str, **kwargs) -> None:
        self._emit(logging.INFO, msg, kwargs)

    def warning(self, msg: str, **kwargs) -> None:
        self._emit(logging.WARNING, msg, kwargs)

    def error(self, msg: str, **kwargs) -> None:
        self._emit(logging.ERROR, msg, kwargs)

    def critical(self, msg: str, **kwargs) -> None:
        self._emit(logging.CRITICAL, msg, kwargs)


def get_logger(name: str) -> BoundLogger:
    """
    Get a structured-field-aware logger for a module.

    Args:
        name: Logger name (usually __name__)

    Returns:
        BoundLogger wrapping a stdlib Logger
    """
    return BoundLogger(logging.getLogger(f"sonoro.{name}"))
