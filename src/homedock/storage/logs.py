"""Rotating log files under %APPDATA%\\HomeDock\\logs, with secrets and IPs masked."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from homedock.masking import RedactingFilter

LOG_FILE = "homedock.log"
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s"


class _LogFileHandler(RotatingFileHandler):
    """Marks the handler installed by :func:`setup_logging`, so it is never added twice."""


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
    IPv4 addresses are always masked. Calling it again replaces the previous handler.
    """
    target = logger or logging.getLogger()
    for previous in [h for h in target.handlers if isinstance(h, _LogFileHandler)]:
        target.removeHandler(previous)
        previous.close()
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = _LogFileHandler(
        logs_dir / LOG_FILE, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(FORMAT))
    redacting = RedactingFilter()
    handler.addFilter(redacting)
    target.setLevel(level)
    target.addHandler(handler)
    return redacting


@contextmanager
def uncaught_exceptions_logged(logger: logging.Logger | None = None) -> Iterator[None]:
    """While active, log uncaught exceptions of threads and of Qt slots to ``logger``.

    Python prints them to stderr otherwise, past the masking filter, and the windowed exe
    has no console. The previous hooks come back on exit, before an exception leaving the
    ``with`` block would be reported: the caller logs that one itself.
    """
    target = logger or logging.getLogger("homedock")
    previous_hook, previous_thread_hook = sys.excepthook, threading.excepthook

    def log_exception(
        kind: type[BaseException], error: BaseException, traceback: TracebackType | None
    ) -> None:
        if issubclass(kind, KeyboardInterrupt):
            previous_hook(kind, error, traceback)
            return
        target.critical("uncaught exception", exc_info=(kind, error, traceback))

    def log_thread_exception(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:  # ignored by Python's own hook too
            return
        exc_info = (args.exc_type, args.exc_value, args.exc_traceback)
        target.critical("uncaught exception in a thread", exc_info=exc_info)

    sys.excepthook, threading.excepthook = log_exception, log_thread_exception
    try:
        yield
    finally:
        sys.excepthook, threading.excepthook = previous_hook, previous_thread_hook
