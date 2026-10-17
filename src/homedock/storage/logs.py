"""Rotating log files under %APPDATA%\\HomeDock\\logs, with secrets and IPs masked."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from homedock.masking import RedactingFilter

LOG_FILE = "homedock.log"
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s"


def setup_logging(
    logs_dir: Path,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> RedactingFilter:
    """Send ``logger`` (the root logger by default) to a rotating file in ``logs_dir``.

    Returns the masking filter: add the secrets to hide (e.g. ``DeviceImport.secrets``).
    IPv4 addresses are always masked.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs_dir / LOG_FILE, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(FORMAT))
    redacting = RedactingFilter()
    handler.addFilter(redacting)
    target = logger or logging.getLogger()
    target.setLevel(level)
    target.addHandler(handler)
    return redacting
