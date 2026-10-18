"""Recovery of devices that stop answering: probes with backoff, then a rediscovery.

A device going offline (its last I/O failed: unplugged, out of Wi-Fi range, a new IP) is
probed — its state read through the control service — after ``PROBE_DELAY`` seconds, then
twice as long after each failure, up to ``MAX_PROBE_DELAY``, until it answers: the service
then marks it online and tells everyone, with no command from the user. After
``FAILURES_BEFORE_SCAN`` failures in a row the device may have a new IP: ``rediscover`` is
called (the app scans the LAN, writes the new IPs and replaces the service's devices), at
most once per ``SCAN_INTERVAL``; when it ends, every device still offline is probed at once.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Protocol

from homedock.core.control import CommandResult, ControlService
from homedock.core.targets import Target
from homedock.masking import mask

log = logging.getLogger(__name__)

PROBE_DELAY = 2.0  # seconds before the first probe of a device that stopped answering
MAX_PROBE_DELAY = 30.0  # an unplugged device is still found within this long once back
FAILURES_BEFORE_SCAN = 3  # failed I/Os in a row before the LAN is scanned for a new IP
SCAN_INTERVAL = 300.0  # seconds between automatic scans (a device may stay unplugged)


class Timer(Protocol):
    def cancel(self) -> None: ...


Schedule = Callable[[float, Callable[[], None]], Timer]


def start_timer(delay: float, callback: Callable[[], None]) -> Timer:
    """Call ``callback`` on a daemon thread after ``delay`` seconds (quitting never waits)."""
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


def probe_delay(failures: int) -> float:
    """Seconds before the next probe of a device that failed ``failures`` times in a row."""
    return min(PROBE_DELAY * 2 ** (failures - 1), MAX_PROBE_DELAY)


@dataclass(eq=False)
class _Watch:
    """An offline device being probed."""

    failures: int = 1
    timer: Timer | None = None
    probing: bool = False


class Recovery:
    """Brings the service's offline devices back on their own (see the module docstring).

    ``rediscover`` starts the rescan and returns its future; it must not block. Everything
    else runs on the service's workers and on timer threads.
    """

    def __init__(
        self,
        service: ControlService,
        rediscover: Callable[[], Future[object]],
        *,
        schedule: Schedule = start_timer,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service = service
        self._rediscover = rediscover
        self._schedule = schedule
        self._clock = clock
        self._lock = threading.Lock()
        self._watches: dict[str, _Watch] = {}
        self._scanning = False
        self._last_scan: float | None = None
        self._stopped = False

    def start(self) -> None:
        self._service.online_changed.connect(self._on_online_changed)

    def stop(self) -> None:
        """Stop probing; answers still on their way are ignored. Calling it again is harmless."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            watches, self._watches = list(self._watches.values()), {}
        with contextlib.suppress(ValueError):  # never started
            self._service.online_changed.disconnect(self._on_online_changed)
        for watch in watches:
            if watch.timer is not None:
                watch.timer.cancel()

    # --- probes -----------------------------------------------------------------------

    def _on_online_changed(self, device_id: str, online: bool) -> None:
        if online:
            self._forget(device_id)
            return
        with self._lock:
            if self._stopped or device_id in self._watches:
                return
            watch = self._watches[device_id] = _Watch()
            self._wait(device_id, watch)

    def _wait(self, device_id: str, watch: _Watch) -> None:
        """Probe ``device_id`` after the backoff of its failures (lock held)."""
        delay = probe_delay(watch.failures)
        log.debug("device %s offline: probing it in %.0f s", mask(device_id), delay)
        watch.timer = self._schedule(delay, lambda: self._probe(device_id, watch))

    def _probe(self, device_id: str, watch: _Watch) -> None:
        with self._lock:
            if self._watches.get(device_id) is not watch or watch.probing:
                return
            watch.timer, watch.probing = None, True
        read = self._service.refresh(Target.device(device_id))
        read.add_done_callback(lambda done: self._probed(device_id, watch, done))

    def _probed(self, device_id: str, watch: _Watch, read: Future[CommandResult]) -> None:
        result = read.result()  # a refresh never fails: devices fail inside its result
        scan = False
        with self._lock:
            watch.probing = False
            if self._watches.get(device_id) is not watch:  # back online, or stopped
                return
            if device_id not in result.failed:  # answered, or no longer a known device
                del self._watches[device_id]
                return
            watch.failures += 1
            if watch.failures >= FAILURES_BEFORE_SCAN and self._scanning:
                return  # probed when the running scan ends
            if watch.failures >= FAILURES_BEFORE_SCAN and self._scan_due():
                self._scanning, self._last_scan, scan = True, self._clock(), True
            else:
                self._wait(device_id, watch)
        if scan:
            self._scan()

    def _forget(self, device_id: str) -> None:
        with self._lock:
            watch = self._watches.pop(device_id, None)
        if watch is not None and watch.timer is not None:
            watch.timer.cancel()

    # --- rediscovery ------------------------------------------------------------------

    def _scan_due(self) -> bool:
        return self._last_scan is None or self._clock() - self._last_scan >= SCAN_INTERVAL

    def _scan(self) -> None:
        log.info("devices keep failing: scanning the network for new addresses")
        try:
            future = self._rediscover()
        except Exception:
            log.exception("cannot start the network scan")
            self._scanned()
            return
        future.add_done_callback(self._scanned)

    def _scanned(self, scan: Future[object] | None = None) -> None:
        """Probe at once every device still offline: the scan may have found its new IP."""
        if scan is not None and not scan.cancelled() and scan.exception() is not None:
            log.warning("the network scan failed: %s", type(scan.exception()).__name__)
        with self._lock:
            self._scanning = False
            if self._stopped:
                return
            due = [(i, w) for i, w in self._watches.items() if not w.probing]
            for _, watch in due:
                if watch.timer is not None:
                    watch.timer.cancel()
        for device_id, watch in due:
            self._probe(device_id, watch)
