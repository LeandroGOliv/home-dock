"""Minimal thread-safe observer, so the core stays free of Qt.

Listeners run on the emitting thread (a worker for device events); the UI marshals them to
its own thread (e.g. through a Qt signal).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class Event[*Args]:
    def __init__(self) -> None:
        self._listeners: list[Callable[[*Args], object]] = []
        self._lock = threading.Lock()

    def connect(self, listener: Callable[[*Args], object]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def disconnect(self, listener: Callable[[*Args], object]) -> None:
        with self._lock:
            self._listeners.remove(listener)

    def emit(self, *args: *Args) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(*args)
            except Exception:
                log.exception("event listener failed")
