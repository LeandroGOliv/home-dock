"""Control service: runs device I/O on workers, fans group commands out in parallel and
keeps a state cache. Works with generic devices only.

Every device has a lane: a FIFO of jobs (writes and reads) drained by one worker task at
a time, so I/O to one device is serialised while different devices run in parallel. A job
queued behind a pending one of the same kind replaces it when it covers all its values
(latest value wins: slider/ring drags collapse into one write), and writes to a device are
spaced by ``throttle`` seconds.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import Executor, Future, InvalidStateError, ThreadPoolExecutor
from dataclasses import dataclass, field

from homedock.core.events import Event
from homedock.core.groups import GroupBook
from homedock.core.targets import Target, resolve
from homedock.devices import Capability, Device, DeviceError, DeviceState
from homedock.masking import mask

log = logging.getLogger(__name__)

THROTTLE_INTERVAL = 0.1  # seconds between the end of a write and the next write to a device
MIN_WORKERS = 8


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Device ids by outcome, in target order."""

    succeeded: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()  # unreachable (offline) or rejected the command
    skipped: tuple[str, ...] = ()  # supports none of the requested capabilities
    unknown: tuple[str, ...] = ()  # not a known device (e.g. removed since a scene was saved)

    @property
    def ok(self) -> bool:
        return not self.failed


@dataclass(eq=False)
class _Job:
    changes: DeviceState | None  # None = read the full state
    waiters: list[Future[DeviceState]] = field(default_factory=list)

    def absorbs(self, changes: DeviceState | None) -> bool:
        """Whether ``changes`` can replace this pending job (reads merge with reads)."""
        if self.changes is None or changes is None:
            return self.changes is None and changes is None
        return changes.capabilities >= self.changes.capabilities


@dataclass(eq=False)
class _Lane:
    device: Device
    jobs: deque[_Job] = field(default_factory=deque)
    busy: bool = False
    last_write: float | None = None


class ControlService:
    """Commands and state for a fixed set of devices.

    Methods never block: they return futures completed on a worker. ``state_changed`` and
    ``online_changed`` fire on worker threads, only when the cached value changes.
    """

    def __init__(
        self,
        devices: Iterable[Device],
        groups: GroupBook | None = None,
        *,
        executor: Executor | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        throttle: float = THROTTLE_INTERVAL,
    ) -> None:
        self._devices = list(devices)
        self.groups = groups if groups is not None else GroupBook()
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max(MIN_WORKERS, len(self._devices)), thread_name_prefix="homedock-io"
        )
        self._clock = clock
        self._sleep = sleep
        self._throttle = throttle
        self._lock = threading.Lock()
        self._lanes = {device.id: _Lane(device) for device in self._devices}
        self._states: dict[str, DeviceState] = {}
        self._online: dict[str, bool] = {}
        self.state_changed: Event[str, DeviceState] = Event()
        self.online_changed: Event[str, bool] = Event()

    # --- queries ----------------------------------------------------------------------

    @property
    def devices(self) -> list[Device]:
        return list(self._devices)

    def members(self, target: Target) -> list[Device]:
        return resolve(target, self._devices, self.groups)

    def capabilities(self, target: Target) -> frozenset[Capability]:
        """Every capability supported by at least one member of ``target``."""
        return frozenset().union(*(d.capabilities for d in self.members(target)))

    def state(self, device_id: str) -> DeviceState | None:
        """Last known state, or ``None`` before the first successful read/write."""
        with self._lock:
            return self._states.get(device_id)

    def is_online(self, device_id: str) -> bool | None:
        """Outcome of the last I/O, or ``None`` before any."""
        with self._lock:
            return self._online.get(device_id)

    # --- commands ---------------------------------------------------------------------

    def send(self, target: Target, changes: DeviceState) -> Future[CommandResult]:
        """Apply ``changes`` to every member in parallel, each getting only what it supports."""
        pending: list[tuple[str, Future[DeviceState]]] = []
        skipped: list[str] = []
        for device in self.members(target):
            supported = changes.restricted_to(device.capabilities)
            if supported.capabilities:
                pending.append((device.id, self._enqueue(device.id, supported)))
            else:
                skipped.append(device.id)
        return _gather(pending, skipped=tuple(skipped))

    def refresh(self, target: Target) -> Future[CommandResult]:
        """Read the real state of every member into the cache, in parallel."""
        pending = [(d.id, self._enqueue(d.id, None)) for d in self.members(target)]
        return _gather(pending)

    def shutdown(self) -> None:
        """Stop the worker pool the service created (an injected executor is left alone)."""
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # --- lanes ------------------------------------------------------------------------

    def _enqueue(self, device_id: str, changes: DeviceState | None) -> Future[DeviceState]:
        future: Future[DeviceState] = Future()
        with self._lock:
            lane = self._lanes[device_id]
            tail = lane.jobs[-1] if lane.jobs else None
            if tail is not None and tail.absorbs(changes):
                tail.changes = changes
                tail.waiters.append(future)
            else:
                lane.jobs.append(_Job(changes, [future]))
            start = not lane.busy
            lane.busy = True
        if start:
            self._executor.submit(self._drain, lane)
        return future

    def _drain(self, lane: _Lane) -> None:
        while True:
            with self._lock:
                if not lane.jobs:
                    lane.busy = False
                    return
                wait = self._wait_before(lane) if lane.jobs[0].changes is not None else 0.0
            if wait > 0:
                self._sleep(wait)  # values arriving meanwhile coalesce into the head job
            with self._lock:
                job = lane.jobs.popleft()
            self._run(lane, job)

    def _wait_before(self, lane: _Lane) -> float:
        if lane.last_write is None:
            return 0.0
        return lane.last_write + self._throttle - self._clock()

    def _run(self, lane: _Lane, job: _Job) -> None:
        device = lane.device
        state: DeviceState | None = None
        error: BaseException | None = None
        online: bool | None = None
        try:
            state = device.read_state() if job.changes is None else device.apply(job.changes)
            online = True
        except DeviceError as exc:
            log.warning("device %s failed: %s", mask(device.id), exc)
            error, online = exc, False
        except Exception as exc:
            log.exception("unexpected error on device %s", mask(device.id))
            error = exc
        finally:
            if job.changes is not None:
                with self._lock:
                    lane.last_write = self._clock()
        self._record(device.id, state, online)
        for waiter in job.waiters:
            _settle(waiter, state, error)

    def _record(self, device_id: str, state: DeviceState | None, online: bool | None) -> None:
        with self._lock:
            state_changed = state is not None and self._states.get(device_id) != state
            online_changed = online is not None and self._online.get(device_id) != online
            if state is not None:
                self._states[device_id] = state
            if online is not None:
                self._online[device_id] = online
        if online_changed:
            self.online_changed.emit(device_id, online)
        if state_changed:
            self.state_changed.emit(device_id, state)


def _settle(
    future: Future[DeviceState], state: DeviceState | None, error: BaseException | None
) -> None:
    with contextlib.suppress(InvalidStateError):  # cancelled by the caller
        if error is None:
            future.set_result(state)
        else:
            future.set_exception(error)


def _gather(
    pending: list[tuple[str, Future[DeviceState]]], skipped: tuple[str, ...] = ()
) -> Future[CommandResult]:
    """A future completed with the outcome of every device future."""
    result: Future[CommandResult] = Future()
    remaining = len(pending)
    lock = threading.Lock()

    def complete() -> None:
        succeeded = tuple(i for i, f in pending if not f.cancelled() and f.exception() is None)
        failed = tuple(i for i, _ in pending if i not in succeeded)
        with contextlib.suppress(InvalidStateError):
            result.set_result(CommandResult(succeeded, failed, skipped))

    def on_done(_future: Future[DeviceState]) -> None:
        nonlocal remaining
        with lock:
            remaining -= 1
            last = remaining == 0
        if last:
            complete()

    if not pending:
        complete()
    for _, future in pending:
        future.add_done_callback(on_done)
    return result
