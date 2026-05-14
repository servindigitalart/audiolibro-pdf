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

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.is_development else logging.WARNING
    )

    # Create app logger
    logger = logging.getLogger("sonoro")
    logger.setLevel(log_level)

    logger.info(
        f"Logging configured: level={settings.log_level}, format={settings.log_format}, env={settings.app_env}"
    )


_STDLIB_LOG_KWARGS = frozenset({"exc_info", "stack_info", "stacklevel"})


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
