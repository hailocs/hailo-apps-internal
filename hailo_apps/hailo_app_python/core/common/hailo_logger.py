# hailo_logger.py
from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime

# ---- module state (singleton-ish) ----
_CONFIGURED = False
_RUN_ID = (
    os.getenv("HAILO_RUN_ID")
    or datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
)

# Basic string->level map (kept small & obvious)
_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _coerce_level(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    if level is None:
        return logging.INFO
    return _LEVELS.get(str(level).upper(), logging.INFO)


def init_logging(
    *,
    level: str | int | None = None,
    log_file: str | None = None,
    force: bool = False,
) -> str:
    """Configure root logger exactly once (unless force=True).
    Returns the run_id (stable across the process).

    Priority for level:
      1) explicit param
      2) env HAILO_LOG_LEVEL
      3) INFO (default)

    You can also pass a file path to duplicate logs to a file.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return _RUN_ID

    # Resolve level from param or env
    env_level = os.getenv("HAILO_LOG_LEVEL")
    resolved_level = _coerce_level(level if level is not None else env_level)

    # Clear existing handlers to avoid duplicates (useful in notebooks/tests)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(resolved_level)

    fmt = "%(asctime)s | %(levelname)s | run=%(run_id)s | %(name)s | %(message)s"
    datefmt = "%H:%M:%S"

    # Console handler
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    ch.addFilter(_RunContextFilter(_RUN_ID))
    root.addHandler(ch)

    # Optional file handler
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        fh.addFilter(_RunContextFilter(_RUN_ID))
        root.addHandler(fh)

    # Be quiet about common noisy deps unless user asked for DEBUG
    logging.getLogger("urllib3").setLevel(max(resolved_level, logging.WARNING))
    logging.getLogger("PIL").setLevel(max(resolved_level, logging.WARNING))

    _CONFIGURED = True
    return _RUN_ID


class _RunContextFilter(logging.Filter):
    """Inject a stable run_id into every record."""

    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = self.run_id
        return True


def get_logger(name: str) -> logging.Logger:
    """Creates or retrieves a logger configured according to LOG_LEVEL from .env.
    Falls back to INFO if not specified or invalid.
    """
    # Read log level from .env, default to INFO
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    valid_levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = valid_levels.get(log_level_str, logging.INFO)

    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        logger.setLevel(log_level)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False

    return logger


def add_logging_cli_args(parser) -> None:
    """Convenience helper: add --log-level/--debug/--log-file flags to an argparse parser."""
    parser.add_argument(
        "--log-level",
        default=os.getenv("HAILO_LOG_LEVEL", "INFO"),
        choices=[k.lower() for k in _LEVELS.keys()],
        help="Logging level (default: %(default)s or $HAILO_LOG_LEVEL).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Shortcut for DEBUG log level (overrides --log-level).",
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("HAILO_LOG_FILE"),
        help="Optional log file path (also respects $HAILO_LOG_FILE).",
    )


def level_from_args(args) -> str:
    """Resolve level string from argparse args."""
    return (
        "DEBUG"
        if getattr(args, "debug", False)
        else str(getattr(args, "log_level", "INFO")).upper()
    )


# If someone forgets to init, default to INFO console so logs still show up.
if os.getenv("HAILO_LOG_AUTOCONFIG", "1") == "1":
    try:
        init_logging(level=os.getenv("HAILO_LOG_LEVEL"), log_file=os.getenv("HAILO_LOG_FILE"))
    except Exception:
        # Avoid crashing on import due to logging config issues
        pass
