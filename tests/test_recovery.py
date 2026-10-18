"""Recovery of unreachable devices with fake devices, timers and clock (no real time)."""

import threading
from concurrent.futures import Future

import pytest

from executors import ManualExecutor
from homedock.core.control import ControlService
from homedock.core.recovery import (
    FAILURES_BEFORE_SCAN,
    MAX_PROBE_DELAY,
    PROBE_DELAY,
    SCAN_INTERVAL,
    Recovery,
    probe_delay,
    start_timer,
)
from homedock.core.targets import Target
from homedock.devices import Capability, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice


class FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeTimers:
    """Collects the scheduled callbacks; ``fire()`` runs the ones still pending."""

    def __init__(self) -> None:
        self.started: list[FakeTimer] = []

    def __call__(self, delay: float, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.started.append(timer)
        return timer

    @property
    def pending(self) -> list[FakeTimer]:
        return [t for t in self.started if not t.cancelled]

    @property
    def delays(self) -> list[float]:
        return [t.delay for t in self.pending]

    def fire(self) -> None:
        due = self.pending
        for timer in due:
            timer.cancelled = True  # a timer fires once
        for timer in due:
            timer.callback()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Rediscovery:
    """Stands in for the app's rescan: records the calls; the test completes them."""

    def __init__(self) -> None:
        self.calls: list[Future] = []

    def __call__(self) -> Future:
        future: Future = Future()
        self.calls.append(future)
        return future


def bulb(device_id: str = "bulb-1", online: bool = True) -> FakeDevice:
    capabilities = frozenset(Capability)
    return FakeDevice(device_id, device_id, DeviceType.RGB_BULB, capabilities, online=online)


@pytest.fixture
def executor():
    return ManualExecutor()


@pytest.fixture
def timers():
    return FakeTimers()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def rediscover():
    return Rediscovery()


@pytest.fixture
def make(executor, timers, clock, rediscover):
    """A started recovery over ``devices``; returns (service, recovery)."""

    def make(*devices: FakeDevice) -> tuple[ControlService, Recovery]:
        service = ControlService(devices, executor=executor, throttle=0)
        recovery = Recovery(service, rediscover, schedule=timers, clock=clock)
        recovery.start()
        return service, recovery

    return make


def read(service: ControlService, executor: ManualExecutor, *device_ids: str) -> None:
    """A read of the devices, e.g. when the flyout opens (an unreachable one goes offline)."""
    for device_id in device_ids:
        service.refresh(Target.device(device_id))
    executor.run_all()


def probe(timers: FakeTimers, executor: ManualExecutor) -> None:
    """Let the pending probes run and answer."""
    timers.fire()
    executor.run_all()


def fail_until_scan(timers: FakeTimers, executor: ManualExecutor) -> None:
    """Probe an offline device until its failures ask for a rediscovery."""
    for _ in range(FAILURES_BEFORE_SCAN - 1):
        probe(timers, executor)


# --- backoff ---------------------------------------------------------------------------------


def test_the_probe_delay_doubles_with_each_failure_up_to_a_cap():
    delays = [probe_delay(n) for n in range(1, 10)]

    assert delays[:2] == [PROBE_DELAY, 2 * PROBE_DELAY]
    assert delays == sorted(delays)
    assert delays[-1] == MAX_PROBE_DELAY


def test_a_device_going_offline_is_probed_after_a_short_delay(make, executor, timers):
    service, _ = make(bulb(online=False))

    read(service, executor, "bulb-1")

    assert service.is_online("bulb-1") is False
    assert timers.delays == [PROBE_DELAY]


def test_each_failed_probe_waits_longer_before_the_next(make, executor, timers):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")

    probe(timers, executor)

    assert timers.delays == [probe_delay(2)]


def test_a_device_answering_again_comes_back_online_by_itself(make, executor, timers):
    device = bulb(online=False)
    service, _ = make(device)
    read(service, executor, "bulb-1")
    changes = []
    service.online_changed.connect(lambda i, online: changes.append((i, online)))

    device.online = True  # plugged in again
    probe(timers, executor)

    assert changes == [("bulb-1", True)]
    assert timers.pending == []


def test_a_command_reaching_the_device_stops_the_probes(make, executor, timers):
    device = bulb(online=False)
    service, _ = make(device)
    read(service, executor, "bulb-1")

    device.online = True
    service.send(Target.device("bulb-1"), DeviceState(power=True))
    executor.run_all()

    assert timers.pending == []


def test_only_the_offline_devices_are_probed(make, executor, timers):
    service, _ = make(bulb("bulb-1", online=False), bulb("bulb-2"))

    read(service, executor, "bulb-1", "bulb-2")

    assert len(timers.pending) == 1
    probe(timers, executor)
    assert service.is_online("bulb-2") is True
    assert len(timers.pending) == 1


def test_a_removed_device_is_no_longer_probed(make, executor, timers):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")

    service.replace_devices([])
    probe(timers, executor)

    assert timers.pending == []


# --- rediscovery -----------------------------------------------------------------------------


def test_repeated_failures_ask_for_a_rediscovery(make, executor, timers, rediscover):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")

    fail_until_scan(timers, executor)

    assert len(rediscover.calls) == 1
    assert timers.pending == []  # probed again once the rediscovery ends


def test_fewer_failures_do_not_rediscover(make, executor, timers, rediscover):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")

    for _ in range(FAILURES_BEFORE_SCAN - 2):
        probe(timers, executor)

    assert rediscover.calls == []


def test_a_device_found_at_a_new_address_comes_back_online(make, executor, timers, rediscover):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")
    fail_until_scan(timers, executor)

    service.replace_devices([bulb()])  # what the rescan does once it found the new IP
    rediscover.calls[0].set_result(None)
    executor.run_all()

    assert service.is_online("bulb-1") is True
    assert timers.pending == []


def test_the_devices_still_offline_after_a_rediscovery_are_probed_again(
    make, executor, timers, rediscover
):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")
    fail_until_scan(timers, executor)

    rediscover.calls[0].set_result(None)
    executor.run_all()

    assert service.is_online("bulb-1") is False
    assert timers.delays == [probe_delay(FAILURES_BEFORE_SCAN + 1)]


def test_a_failed_rediscovery_still_probes_again(make, executor, timers, rediscover):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")
    fail_until_scan(timers, executor)

    rediscover.calls[0].set_exception(OSError("scan failed"))
    executor.run_all()

    assert len(timers.pending) == 1


def test_a_rediscovery_that_cannot_start_still_probes_again(make, executor, timers):
    service = ControlService([bulb(online=False)], executor=executor, throttle=0)

    def broken():
        raise RuntimeError("cannot start")

    Recovery(service, broken, schedule=timers).start()
    read(service, executor, "bulb-1")
    fail_until_scan(timers, executor)
    executor.run_all()

    assert len(timers.pending) == 1


def test_one_rediscovery_serves_every_offline_device(make, executor, timers, rediscover):
    service, _ = make(bulb("bulb-1", online=False), bulb("bulb-2", online=False))
    read(service, executor, "bulb-1", "bulb-2")

    fail_until_scan(timers, executor)
    rediscover.calls[0].set_result(None)
    executor.run_all()

    assert len(rediscover.calls) == 1
    assert len(timers.pending) == 2


def test_rediscovery_runs_at_most_once_per_interval(make, executor, timers, clock, rediscover):
    service, _ = make(bulb(online=False))
    read(service, executor, "bulb-1")
    fail_until_scan(timers, executor)
    rediscover.calls[0].set_result(None)
    executor.run_all()

    for _ in range(5):
        clock.now += MAX_PROBE_DELAY
        probe(timers, executor)
    assert len(rediscover.calls) == 1

    clock.now += SCAN_INTERVAL
    probe(timers, executor)
    assert len(rediscover.calls) == 2


def test_a_device_failing_again_later_starts_from_the_short_delay(
    make, executor, timers, rediscover
):
    device = bulb(online=False)
    service, _ = make(device)
    read(service, executor, "bulb-1")
    probe(timers, executor)
    device.online = True
    probe(timers, executor)

    device.online = False
    read(service, executor, "bulb-1")

    assert timers.delays == [PROBE_DELAY]
    assert rediscover.calls == []


# --- stopping --------------------------------------------------------------------------------


def test_stop_cancels_the_probes_and_ignores_later_failures(make, executor, timers):
    service, recovery = make(bulb("bulb-1", online=False), bulb("bulb-2", online=False))
    read(service, executor, "bulb-1")

    recovery.stop()
    read(service, executor, "bulb-2")

    assert timers.pending == []


def test_a_probe_answering_after_stop_schedules_nothing(make, executor, timers):
    service, recovery = make(bulb(online=False))
    read(service, executor, "bulb-1")
    timers.fire()  # the probe is queued

    recovery.stop()
    executor.run_all()

    assert timers.pending == []


def test_a_rediscovery_ending_after_stop_probes_nothing(make, executor, timers, rediscover):
    service, recovery = make(bulb(online=False))
    read(service, executor, "bulb-1")
    fail_until_scan(timers, executor)

    recovery.stop()
    rediscover.calls[0].set_result(None)

    assert not executor.tasks
    assert timers.pending == []


def test_stopping_twice_or_before_starting_is_harmless(executor, timers):
    service = ControlService([bulb()], executor=executor, throttle=0)
    idle = Recovery(service, Rediscovery(), schedule=timers)
    idle.stop()
    started = Recovery(service, Rediscovery(), schedule=timers)
    started.start()

    started.stop()
    started.stop()


# --- default timers --------------------------------------------------------------------------


def test_start_timer_calls_back_on_a_daemon_thread():
    called = threading.Event()
    threads = []

    def callback():
        threads.append(threading.current_thread())
        called.set()

    start_timer(0.01, callback)

    assert called.wait(timeout=5)
    assert threads[0] is not threading.current_thread()
    assert threads[0].daemon


def test_a_cancelled_timer_never_calls_back():
    called = threading.Event()
    timer = start_timer(0.05, called.set)

    timer.cancel()

    assert not called.wait(timeout=0.2)
