"""ControlService with fake devices, a manual executor and a fake clock (no real time)."""

import logging
import threading
from collections import deque
from concurrent.futures import Executor, Future
from enum import StrEnum

import pytest

from homedock.core.control import THROTTLE_INTERVAL, CommandResult, ControlService
from homedock.core.groups import GroupBook
from homedock.core.targets import Target
from homedock.devices import Capability, Color, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice

BULB = frozenset(Capability)
ALL_BULBS = Target.all_of(DeviceType.RGB_BULB)


class OtherType(StrEnum):
    AC = "test_ac"


class ManualExecutor(Executor):
    """Queues tasks until ``run_all()``: lets a test decide when "worker" code runs."""

    def __init__(self) -> None:
        self.tasks: deque = deque()

    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        self.tasks.append((future, fn, args, kwargs))
        return future

    def run_all(self) -> None:
        while self.tasks:
            future, fn, args, kwargs = self.tasks.popleft()
            future.set_running_or_notify_cancel()
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)


class FakeClock:
    """Monotonic clock whose ``sleep`` advances time instantly and runs an optional hook."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []
        self.on_sleep = None

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds
        if self.on_sleep is not None:
            hook, self.on_sleep = self.on_sleep, None
            hook()


class LoggingFake(FakeDevice):
    """Fake that records every I/O call in order, in a log shared between devices."""

    def __init__(self, *args, log: list, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.log = log

    def read_state(self) -> DeviceState:
        self.log.append((self.id, "read"))
        return super().read_state()

    def apply(self, changes: DeviceState) -> DeviceState:
        self.log.append((self.id, "apply"))
        return super().apply(changes)


def bulb(device_id: str = "bulb-1", **kwargs) -> FakeDevice:
    return FakeDevice(device_id, device_id, DeviceType.RGB_BULB, BULB, **kwargs)


def air_conditioner(device_id: str = "ac-1") -> FakeDevice:
    return FakeDevice(device_id, device_id, OtherType.AC, frozenset({Capability.POWER}))


@pytest.fixture
def executor() -> ManualExecutor:
    return ManualExecutor()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_service(executor, clock):
    def make(*devices, groups=None):
        return ControlService(devices, groups, executor=executor, clock=clock, sleep=clock.sleep)

    return make


def done(future: Future, executor: ManualExecutor) -> CommandResult:
    executor.run_all()
    assert future.done()
    return future.result()


# --- commands -----------------------------------------------------------------------------


def test_send_applies_the_changes_on_a_worker_and_reports_success(make_service, executor):
    device = bulb()
    service = make_service(device)
    future = service.send(Target.device("bulb-1"), DeviceState(power=True))
    assert device.applied == []  # nothing runs on the calling thread
    assert done(future, executor) == CommandResult(succeeded=("bulb-1",))
    assert device.applied == [DeviceState(power=True)]


def test_send_updates_the_cache_and_emits_state_and_online_events(make_service, executor):
    service = make_service(bulb(state=DeviceState(power=False, brightness=40)))
    states, onlines = [], []
    service.state_changed.connect(lambda *args: states.append(args))
    service.online_changed.connect(lambda *args: onlines.append(args))
    assert service.state("bulb-1") is None
    assert service.is_online("bulb-1") is None

    done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)

    expected = DeviceState(power=True, brightness=40)
    assert service.state("bulb-1") == expected
    assert service.is_online("bulb-1") is True
    assert states == [("bulb-1", expected)]
    assert onlines == [("bulb-1", True)]


def test_events_fire_only_on_change(make_service, executor):
    service = make_service(bulb())
    states, onlines = [], []
    service.state_changed.connect(lambda *args: states.append(args))
    service.online_changed.connect(lambda *args: onlines.append(args))
    for _ in range(2):
        done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)
    assert len(states) == 1
    assert len(onlines) == 1


def test_group_command_reaches_every_member(make_service, executor):
    a, b = bulb("bulb-a"), bulb("bulb-b")
    service = make_service(a, b)
    result = done(service.send(ALL_BULBS, DeviceState(brightness=70)), executor)
    assert result == CommandResult(succeeded=("bulb-a", "bulb-b"))
    assert a.applied == b.applied == [DeviceState(brightness=70)]


def test_mixed_group_sends_each_device_only_what_it_supports(make_service, executor):
    lamp, ac = bulb(), air_conditioner()
    groups = GroupBook()
    sala = groups.create("Sala", [lamp.id, ac.id])
    service = make_service(lamp, ac, groups=groups)

    changes = DeviceState(power=True, brightness=30)
    result = done(service.send(Target.group(sala.id), changes), executor)
    assert result == CommandResult(succeeded=("bulb-1", "ac-1"))
    assert lamp.applied == [DeviceState(power=True, brightness=30)]
    assert ac.applied == [DeviceState(power=True)]

    result = done(service.send(Target.group(sala.id), DeviceState(brightness=80)), executor)
    assert result == CommandResult(succeeded=("bulb-1",), skipped=("ac-1",))
    assert ac.applied == [DeviceState(power=True)]


def test_empty_target_completes_immediately(make_service):
    service = make_service(bulb())
    future = service.send(Target.group("deleted"), DeviceState(power=True))
    assert future.done()
    assert future.result() == CommandResult()


def test_capabilities_of_a_target_is_the_union_of_its_members(make_service):
    groups = GroupBook()
    sala = groups.create("Sala", ["ac-1"])
    service = make_service(bulb(), air_conditioner(), groups=groups)
    assert service.capabilities(Target.group(sala.id)) == {Capability.POWER}
    groups.set_members(sala.id, ["ac-1", "bulb-1"])
    assert service.capabilities(Target.group(sala.id)) == BULB
    assert service.capabilities(Target.group("deleted")) == frozenset()


# --- failures -----------------------------------------------------------------------------


def test_offline_member_fails_alone_and_is_reported(make_service, executor):
    online, offline = bulb("bulb-a"), bulb("bulb-b", online=False)
    service = make_service(online, offline)
    onlines = []
    service.online_changed.connect(lambda *args: onlines.append(args))

    result = done(service.send(ALL_BULBS, DeviceState(power=True)), executor)

    assert result == CommandResult(succeeded=("bulb-a",), failed=("bulb-b",))
    assert not result.ok
    assert online.state.power is True
    assert service.is_online("bulb-b") is False
    assert ("bulb-b", False) in onlines


def test_a_device_coming_back_is_reported_online(make_service, executor):
    device = bulb(online=False)
    service = make_service(device)
    done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)
    device.online = True
    result = done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)
    assert result.ok
    assert service.is_online("bulb-1") is True


def test_unexpected_errors_fail_the_device_without_marking_it_offline(
    make_service, executor, caplog
):
    device = bulb()
    device.apply = lambda changes: (_ for _ in ()).throw(ValueError("bug"))
    service = make_service(device)
    with caplog.at_level(logging.ERROR):
        result = done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)
    assert result == CommandResult(failed=("bulb-1",))
    assert service.is_online("bulb-1") is None
    assert "bug" in caplog.text


def test_a_failing_listener_does_not_fail_the_command(make_service, executor):
    service = make_service(bulb())
    service.state_changed.connect(lambda *_: (_ for _ in ()).throw(RuntimeError("ui bug")))
    result = done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)
    assert result.ok


def test_logs_mask_device_ids(make_service, executor, caplog):
    device = FakeDevice("bf1234567890abcdef", "Sala", DeviceType.RGB_BULB, BULB, online=False)
    service = make_service(device)
    with caplog.at_level(logging.DEBUG):
        done(service.send(Target.device("bf1234567890abcdef"), DeviceState(power=True)), executor)
    assert caplog.text
    assert "bf1234567890abcdef" not in caplog.text


# --- coalescing and throttling ------------------------------------------------------------


def test_rapid_updates_coalesce_to_the_latest_value(make_service, executor):
    device = bulb()
    service = make_service(device)
    futures = [
        service.send(Target.device("bulb-1"), DeviceState(brightness=value))
        for value in (10, 20, 30)
    ]
    executor.run_all()
    assert device.applied == [DeviceState(brightness=30)]
    assert all(f.result().ok for f in futures)


def test_different_changes_are_not_merged_and_keep_their_order(make_service, executor):
    device = bulb()
    service = make_service(device)
    target = Target.device("bulb-1")
    service.send(target, DeviceState(brightness=10))
    service.send(target, DeviceState(color_hsv=Color(120, 100)))
    service.send(target, DeviceState(brightness=20))
    executor.run_all()
    assert device.applied == [
        DeviceState(brightness=10),
        DeviceState(color_hsv=Color(120, 100)),
        DeviceState(brightness=20),
    ]


def test_a_change_covering_the_pending_one_replaces_it(make_service, executor):
    device = bulb()
    service = make_service(device)
    target = Target.device("bulb-1")
    service.send(target, DeviceState(brightness=10))
    service.send(target, DeviceState(power=True, brightness=20))
    executor.run_all()
    assert device.applied == [DeviceState(power=True, brightness=20)]


def test_writes_to_a_device_are_throttled(make_service, executor, clock):
    service = make_service(bulb())
    target = Target.device("bulb-1")
    done(service.send(target, DeviceState(brightness=10)), executor)
    assert clock.sleeps == []  # the first write goes out immediately

    clock.now += THROTTLE_INTERVAL / 4
    done(service.send(target, DeviceState(brightness=20)), executor)
    assert clock.sleeps == [round(THROTTLE_INTERVAL * 3 / 4, 6)]

    clock.now += THROTTLE_INTERVAL
    done(service.send(target, DeviceState(brightness=30)), executor)
    assert len(clock.sleeps) == 1


def test_values_sent_during_the_throttle_wait_are_coalesced(make_service, executor, clock):
    device = bulb()
    service = make_service(device)
    target = Target.device("bulb-1")
    done(service.send(target, DeviceState(brightness=10)), executor)

    clock.on_sleep = lambda: service.send(target, DeviceState(brightness=90))
    done(service.send(target, DeviceState(brightness=50)), executor)

    assert device.applied == [DeviceState(brightness=10), DeviceState(brightness=90)]


def test_throttle_is_per_device(make_service, executor, clock):
    service = make_service(bulb("bulb-a"), bulb("bulb-b"))
    done(service.send(Target.device("bulb-a"), DeviceState(brightness=10)), executor)
    done(service.send(Target.device("bulb-b"), DeviceState(brightness=10)), executor)
    assert clock.sleeps == []


# --- reads --------------------------------------------------------------------------------


def test_refresh_reads_every_member_into_the_cache(make_service, executor):
    a = bulb("bulb-a", state=DeviceState(power=True))
    b = bulb("bulb-b", online=False)
    service = make_service(a, b)
    states = []
    service.state_changed.connect(lambda *args: states.append(args))

    result = done(service.refresh(ALL_BULBS), executor)

    assert result == CommandResult(succeeded=("bulb-a",), failed=("bulb-b",))
    assert service.state("bulb-a") == DeviceState(power=True)
    assert states == [("bulb-a", DeviceState(power=True))]
    assert service.is_online("bulb-b") is False


def test_reads_and_writes_to_a_device_keep_their_order(make_service, executor):
    log: list = []
    device = LoggingFake("bulb-1", "bulb-1", DeviceType.RGB_BULB, BULB, log=log)
    service = make_service(device)
    target = Target.device("bulb-1")
    service.send(target, DeviceState(brightness=10))
    service.refresh(target)
    service.refresh(target)  # coalesces with the pending read
    service.send(target, DeviceState(power=False))
    executor.run_all()
    assert log == [("bulb-1", "apply"), ("bulb-1", "read"), ("bulb-1", "apply")]


# --- real threads -------------------------------------------------------------------------


class BlockingFake(FakeDevice):
    """Fake whose ``apply`` waits for a barrier shared by every member of a group."""

    def __init__(self, *args, barrier: threading.Barrier, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.barrier = barrier
        self.thread: str | None = None

    def apply(self, changes: DeviceState) -> DeviceState:
        self.thread = threading.current_thread().name
        self.barrier.wait()  # breaks (timeout) unless every member runs at the same time
        return super().apply(changes)


def test_group_commands_run_in_parallel_off_the_calling_thread():
    barrier = threading.Barrier(3, timeout=5)
    devices = [
        BlockingFake(f"bulb-{n}", f"bulb-{n}", DeviceType.RGB_BULB, BULB, barrier=barrier)
        for n in range(3)
    ]
    service = ControlService(devices)
    try:
        result = service.send(ALL_BULBS, DeviceState(power=True)).result(timeout=10)
    finally:
        service.shutdown()
    assert result == CommandResult(succeeded=("bulb-0", "bulb-1", "bulb-2"))
    caller = threading.current_thread().name
    assert all(d.thread and d.thread != caller for d in devices)


def test_io_to_one_device_is_never_concurrent():
    entered = threading.Event()
    release = threading.Event()
    active = []

    class GatedFake(FakeDevice):
        def apply(self, changes: DeviceState) -> DeviceState:
            active.append(changes)
            assert len(active) == 1, "two calls to the same device at once"
            entered.set()
            release.wait(timeout=5)
            active.pop()
            return super().apply(changes)

    device = GatedFake("bulb-1", "bulb-1", DeviceType.RGB_BULB, BULB)
    service = ControlService([device], throttle=0)
    try:
        first = service.send(Target.device("bulb-1"), DeviceState(brightness=10))
        assert entered.wait(timeout=5)
        second = service.send(Target.device("bulb-1"), DeviceState(power=True))
        release.set()
        assert first.result(timeout=5).ok
        assert second.result(timeout=5).ok
    finally:
        release.set()
        service.shutdown()
    assert device.applied == [DeviceState(brightness=10), DeviceState(power=True)]
