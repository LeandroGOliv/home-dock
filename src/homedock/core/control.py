"""Control service: runs device I/O on workers, fans group commands out in parallel and
keeps a state cache. Works with generic devices only.

Every device has a lane: a FIFO of jobs (writes and reads) drained by one worker task at
a time, so I/O to one device is serialised and ordered while different devices run in
parallel. A write queued behind a pending write of the same capabilities replaces it
(latest value wins: slider/ring drags collapse into few writes); consecutive reads merge.
Writes to a device are spaced by ``throttle`` seconds. When a device is unreachable, the
jobs queued behind the failed one fail at once instead of each waiting for a timeout.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Executor, Future, InvalidStateError, ThreadPoolExecutor
from dataclasses import dataclass, field

from homedock.core.events import Event
from homedock.core.groups import GroupBook
from homedock.core.scenes import Scene
from homedock.core.targets import Target, resolve
from homedock.devices import Capability, Device, DeviceError, DeviceState
from homedock.masking import mask

log = logging.getLogger(__name__)

THROTTLE_INTERVAL = 0.1  # seconds between the end of a write and the next write to a device
MIN_WORKERS = 8


class ServiceClosedError(RuntimeError):
    """The control service was shut down."""


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
        """Whether ``changes`` can replace this pending job.

        Only for the same capabilities: a wider change may imply another device mode (e.g.
        a bulb's colour vs white), so it must not swallow the pending one.
        """
        if self.changes is None or changes is None:
            return self.changes is None and changes is None
        return changes.capabilities == self.changes.capabilities


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
        self._closed = False
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
        return self._dispatch((device, changes) for device in self.members(target))

    def refresh(self, target: Target) -> Future[CommandResult]:
        """Read the real state of every member into the cache, in parallel."""
        return self._read(self.members(target))

    def capture(self, target: Target) -> Future[dict[str, DeviceState]]:
        """The real state of the members, to save as a scene ("Salvar atual").

        The read is queued behind pending writes, so the end of a drag is included. Devices
        that do not answer are left out; each state keeps only the device's capabilities.
        """
        members = self.members(target)
        result: Future[dict[str, DeviceState]] = Future()

        def on_read(read: Future[CommandResult]) -> None:
            answered = set(read.result().succeeded)
            with contextlib.suppress(InvalidStateError):
                result.set_result(self._snapshot(d for d in members if d.id in answered))

        self._read(members).add_done_callback(on_read)
        return result

    def apply_scene(self, scene: Scene) -> Future[CommandResult]:
        """Apply every entry in parallel; offline and unknown devices are only reported."""
        by_id = {device.id: device for device in self._devices}
        unknown = tuple(i for i in scene.devices if i not in by_id)
        entries = ((by_id[i], s) for i, s in scene.devices.items() if i in by_id)
        return self._dispatch(entries, unknown)

    def shutdown(self) -> None:
        """Fail queued jobs, refuse new ones and stop the worker pool the service created
        (an injected executor is left running)."""
        with self._lock:
            self._closed = True
        for lane in self._lanes.values():
            self._drop_jobs(lane, ServiceClosedError("control service is shut down"), idle=True)
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # --- lanes ------------------------------------------------------------------------

    def _dispatch(
        self, entries: Iterable[tuple[Device, DeviceState]], unknown: tuple[str, ...] = ()
    ) -> Future[CommandResult]:
        pending: list[tuple[str, Future[DeviceState]]] = []
        skipped: list[str] = []
        for device, changes in entries:
            supported = changes.restricted_to(device.capabilities)
            if supported.capabilities:
                pending.append((device.id, self._enqueue(device.id, supported)))
            else:
                skipped.append(device.id)
        return _gather(pending, tuple(skipped), unknown)

    def _read(self, devices: Sequence[Device]) -> Future[CommandResult]:
        return _gather([(d.id, self._enqueue(d.id, None)) for d in devices])

    def _snapshot(self, devices: Iterable[Device]) -> dict[str, DeviceState]:
        snapshot: dict[str, DeviceState] = {}
        with self._lock:
            for device in devices:
                state = self._states.get(device.id)
                kept = state.restricted_to(device.capabilities) if state else DeviceState()
                if kept.capabilities:
                    snapshot[device.id] = kept
        return snapshot

    def _enqueue(self, device_id: str, changes: DeviceState | None) -> Future[DeviceState]:
        future: Future[DeviceState] = Future()
        with self._lock:
            closed = self._closed
            lane = self._lanes[device_id]
            if not closed:
                tail = lane.jobs[-1] if lane.jobs else None
                if tail is not None and tail.absorbs(changes):
                    tail.changes = changes
                    tail.waiters.append(future)
                else:
                    lane.jobs.append(_Job(changes, [future]))
            start = not closed and not lane.busy
            if start:
                lane.busy = True
        if closed:
            _settle(future, None, ServiceClosedError("control service is shut down"))
        elif start:
            try:
                self._executor.submit(self._drain, lane)
            except Exception as exc:  # e.g. the injected executor was shut down
                log.error("cannot schedule I/O for device %s: %s", mask(device_id), exc)
                self._drop_jobs(lane, exc, idle=True)
        return future

    def _drain(self, lane: _Lane) -> None:
        job: _Job | None = None
        try:
            while True:
                with self._lock:
                    if not lane.jobs:
                        lane.busy = False
                        return
                    head_is_write = lane.jobs[0].changes is not None
                wait = self._wait_before(lane) if head_is_write else 0.0
                if wait > 0:
                    self._sleep(wait)  # values arriving meanwhile coalesce into the head job
                with self._lock:
                    if not lane.jobs:  # dropped by shutdown meanwhile
                        continue
                    job = lane.jobs.popleft()
                self._run(lane, job)
                job = None
        except BaseException as exc:
            # Never leave the lane busy with unanswered jobs, whatever went wrong.
            log.exception("I/O lane of device %s failed", mask(lane.device.id))
            if job is not None:
                for waiter in job.waiters:
                    _settle(waiter, None, exc)
            self._drop_jobs(lane, exc, idle=True)
            raise

    def _wait_before(self, lane: _Lane) -> float:
        with self._lock:
            last_write = lane.last_write
        if last_write is None:
            return 0.0
        return last_write + self._throttle - self._clock()

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
                ended = self._clock()
                with self._lock:
                    lane.last_write = ended
        self._record(device.id, state, online)
        for waiter in job.waiters:
            _settle(waiter, state, error)
        if online is False:
            # Unreachable: the jobs queued meanwhile would each wait for a timeout too.
            self._drop_jobs(lane, error, idle=False)

    def _drop_jobs(self, lane: _Lane, error: BaseException, *, idle: bool) -> None:
        """Fail every queued job of ``lane``; ``idle`` also marks it as not draining."""
        with self._lock:
            jobs = list(lane.jobs)
            lane.jobs.clear()
            if idle:
                lane.busy = False
        for job in jobs:
            for waiter in job.waiters:
                _settle(waiter, None, error)

    def _record(self, device_id: str, state: DeviceState | None, online: bool | None) -> None:
        """Update the cache (a partial state is merged into the known one) and notify."""
        with self._lock:
            previous = self._states.get(device_id)
            if state is not None and previous is not None:
                state = previous.merged(state)
            state_changed = state is not None and state != previous
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
    pending: list[tuple[str, Future[DeviceState]]],
    skipped: tuple[str, ...] = (),
    unknown: tuple[str, ...] = (),
) -> Future[CommandResult]:
    """A future completed with the outcome of every device future."""
    result: Future[CommandResult] = Future()
    remaining = len(pending)
    lock = threading.Lock()

    def complete() -> None:
        succeeded = tuple(i for i, f in pending if not f.cancelled() and f.exception() is None)
        failed = tuple(i for i, _ in pending if i not in succeeded)
        with contextlib.suppress(InvalidStateError):
            result.set_result(CommandResult(succeeded, failed, skipped, unknown))

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
