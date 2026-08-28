"""
Professional logging setup using Rich for beautiful console output
and rotating file handlers for persistent log storage.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

# Module-level console — shared by log handlers
_console = Console(stderr=True, highlight=True)


def setup_logging(
    log_level: str = "DEBUG",
    log_file: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """
    Configure root logger with:
    - Rich console handler (coloured, structured output)
    - Rotating file handler (persistent, searchable logs)

    Call once at application startup.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.DEBUG)

    # ── Rich console handler ────────────────────────────────────────────
    rich_handler = RichHandler(
        console=_console,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
        show_path=False,
        log_time_format="[%H:%M:%S]",
    )
    rich_handler.setLevel(numeric_level)

    handlers: list[logging.Handler] = [rich_handler]

    # ── Rotating file handler ───────────────────────────────────────────
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

    logging.basicConfig(
        level=numeric_level,
        handlers=handlers,
        format="%(message)s",
        datefmt="[%H:%M:%S]",
        force=True,  # override any existing config
    )

    # Silence noisy third-party loggers
    for noisy in ("httpx2", "urllib3", "PIL", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Retrieve a named logger.

    Usage:
        log = get_logger(__name__)
        log.info("Starting...")
    """
    return logging.getLogger(name)
