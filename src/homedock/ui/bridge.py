"""Bridge from the control service (worker threads) to the Qt UI thread.

``ControlService`` events and futures complete on worker threads; widgets may only be
touched on the UI thread. The bridge lives on the UI thread and re-emits everything as Qt
signals, which Qt delivers there through its event loop.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal

from homedock.core import ControlService
from homedock.devices import DeviceState


class ServiceBridge(QObject):
    state_changed = Signal(str, object)  # device id, DeviceState
    online_changed = Signal(str, bool)  # device id, online
    _done = Signal(object, object)  # callback, future

    def __init__(self, service: ControlService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        # Queued even when emitted on the UI thread: a callback is never re-entrant.
        self._done.connect(self._call, Qt.ConnectionType.QueuedConnection)
        service.state_changed.connect(self._forward_state)
        service.online_changed.connect(self._forward_online)

    def when_done(self, future: Future[Any], callback: Callable[[Future[Any]], object]) -> None:
        """Call ``callback(future)`` on the UI thread once ``future`` completes."""
        future.add_done_callback(lambda done: self._done.emit(callback, done))

    def detach(self) -> None:
        """Stop forwarding the service events."""
        self._service.state_changed.disconnect(self._forward_state)
        self._service.online_changed.disconnect(self._forward_online)

    def _forward_state(self, device_id: str, state: DeviceState) -> None:
        self.state_changed.emit(device_id, state)

    def _forward_online(self, device_id: str, online: bool) -> None:
        self.online_changed.emit(device_id, online)

    @staticmethod
    def _call(callback: Callable[[Future[Any]], object], future: Future[Any]) -> None:
        callback(future)
