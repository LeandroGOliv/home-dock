"""ControlService with fake devices, a manual executor and a fake clock (no real time)."""

import logging
import threading
from collections import deque
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from enum import StrEnum

import pytest

from homedock.core.control import THROTTLE_INTERVAL, CommandResult, ControlService
from homedock.core.groups import GroupBook
from homedock.core.scenes import Scene
from homedock.core.targets import Target
from homedock.devices import (
    Capability,
    Color,
    DeviceError,
    DeviceState,
    DeviceType,
    WorkMode,
)
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


class RaisingFake(FakeDevice):
    """Fake whose ``apply`` raises ``error`` while it is set."""

    error: Exception | None = None

    def apply(self, changes: DeviceState) -> DeviceState:
        if self.error is not None:
            raise self.error
        return super().apply(changes)


def test_unexpected_errors_fail_the_device_without_marking_it_offline(
    make_service, executor, caplog
):
    device = RaisingFake("bulb-1", "bulb-1", DeviceType.RGB_BULB, BULB)
    device.error = ValueError("bug")
    service = make_service(device)
    target = Target.device("bulb-1")
    with caplog.at_level(logging.ERROR):
        result = done(service.send(target, DeviceState(power=True)), executor)
    assert result == CommandResult(failed=("bulb-1",))
    assert service.is_online("bulb-1") is None
    assert "bug" in caplog.text

    device.error = None
    assert done(service.send(target, DeviceState(power=True)), executor).ok


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


def test_only_changes_of_the_same_capabilities_coalesce(make_service, executor):
    # A wider change may imply another bulb mode than the pending one, so both are sent.
    device = bulb()
    service = make_service(device)
    target = Target.device("bulb-1")
    service.send(target, DeviceState(color_temperature=40))
    service.send(target, DeviceState(color_temperature=50, color_hsv=Color(0, 100)))
    executor.run_all()
    assert device.applied == [
        DeviceState(color_temperature=40),
        DeviceState(color_temperature=50, color_hsv=Color(0, 100)),
    ]


def test_coalesced_commands_all_report_the_failure(make_service, executor):
    service = make_service(bulb(online=False))
    futures = [service.send(Target.device("bulb-1"), DeviceState(brightness=v)) for v in (1, 2)]
    executor.run_all()
    assert [f.result() for f in futures] == [CommandResult(failed=("bulb-1",))] * 2


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
    overlapped = []

    class GatedFake(FakeDevice):
        def apply(self, changes: DeviceState) -> DeviceState:
            active.append(changes)
            overlapped.append(len(active) > 1)
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
    assert overlapped == [False, False]


# --- scenes -------------------------------------------------------------------------------


def test_capture_reads_the_online_members_of_the_target(make_service, executor):
    lamp = bulb("bulb-1", state=DeviceState(power=True, brightness=60))
    outside = bulb("bulb-2", state=DeviceState(power=False))
    offline = bulb("bulb-3", state=DeviceState(power=True), online=False)
    silent = air_conditioner()  # reports nothing: nothing to restore
    groups = GroupBook()
    sala = groups.create("Sala", ["bulb-1", "bulb-3", "ac-1"])
    service = make_service(lamp, outside, offline, silent, groups=groups)

    future = service.capture(Target.group(sala.id))
    executor.run_all()

    assert future.result() == {"bulb-1": DeviceState(power=True, brightness=60)}
    assert service.state("bulb-2") is None  # outside the target: not read


def test_capture_keeps_only_the_capabilities_of_each_device(make_service, executor):
    class LeakyAc(FakeDevice):
        def read_state(self) -> DeviceState:
            return DeviceState(power=True, brightness=50)

    ac = LeakyAc("ac-1", "ac-1", OtherType.AC, frozenset({Capability.POWER}))
    service = make_service(ac)
    future = service.capture(Target.device("ac-1"))
    executor.run_all()
    assert future.result() == {"ac-1": DeviceState(power=True)}


def test_capture_includes_writes_still_queued(make_service, executor):
    service = make_service(bulb(state=DeviceState(power=True, brightness=20)))
    service.send(Target.device("bulb-1"), DeviceState(brightness=90))  # end of a drag
    future = service.capture(Target.device("bulb-1"))
    executor.run_all()
    assert future.result() == {"bulb-1": DeviceState(power=True, brightness=90)}


def test_apply_scene_sends_each_device_its_own_entry(make_service, executor):
    a, b, ac = bulb("bulb-a"), bulb("bulb-b"), air_conditioner()
    service = make_service(a, b, ac)
    scene = Scene(
        "scene-1",
        "Leitura",
        {
            "bulb-a": DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=80),
            "bulb-b": DeviceState(power=False),
            "ac-1": DeviceState(power=True, brightness=10),
        },
    )
    result = done(service.apply_scene(scene), executor)
    assert result == CommandResult(succeeded=("bulb-a", "bulb-b", "ac-1"))
    assert a.applied == [DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=80)]
    assert b.applied == [DeviceState(power=False)]
    assert ac.applied == [DeviceState(power=True)]


def test_apply_scene_skips_offline_and_unknown_devices_and_reports_them(make_service, executor):
    online, offline, ac = bulb("bulb-a"), bulb("bulb-b", online=False), air_conditioner()
    service = make_service(online, offline, ac)
    scene = Scene(
        "scene-1",
        "Festa",
        {
            "bulb-a": DeviceState(power=True, color_hsv=Color(300, 100)),
            "bulb-b": DeviceState(power=True),
            "removed": DeviceState(power=True),
            "ac-1": DeviceState(brightness=10),
        },
    )
    result = done(service.apply_scene(scene), executor)
    assert result == CommandResult(
        succeeded=("bulb-a",), failed=("bulb-b",), skipped=("ac-1",), unknown=("removed",)
    )
    assert online.state == DeviceState(power=True, color_hsv=Color(300, 100))


def test_a_captured_scene_restores_the_devices(make_service, executor):
    a = bulb("bulb-a", state=DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=30))
    b = bulb("bulb-b", state=DeviceState(power=True, color_hsv=Color(200, 50), brightness=90))
    service = make_service(a, b)
    captured = service.capture(ALL_BULBS)
    executor.run_all()
    scene = Scene("scene-1", "Noite", captured.result())

    done(service.send(ALL_BULBS, DeviceState(power=False, brightness=5)), executor)
    assert done(service.apply_scene(scene), executor).ok

    recaptured = service.capture(ALL_BULBS)
    executor.run_all()
    assert recaptured.result() == scene.devices
    assert a.state == DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=30)


def test_apply_scene_edge_cases(make_service, executor):
    service = make_service(bulb("bulb-a"), bulb("bulb-b", online=False))
    empty = service.apply_scene(Scene("s-1", "Vazia", {}))
    assert empty.done()
    assert empty.result() == CommandResult()

    blank_entry = Scene("s-2", "X", {"bulb-a": DeviceState()})
    assert done(service.apply_scene(blank_entry), executor) == CommandResult(skipped=("bulb-a",))

    all_offline = Scene("s-3", "Y", {"bulb-b": DeviceState(power=True)})
    result = done(service.apply_scene(all_offline), executor)
    assert result == CommandResult(failed=("bulb-b",))
    assert not result.ok


# --- lifecycle and robustness -------------------------------------------------------------


def test_shutdown_fails_queued_commands(make_service, executor):
    device = bulb()
    service = make_service(device)
    future = service.send(Target.device("bulb-1"), DeviceState(power=True))
    service.shutdown()
    assert future.done()
    assert future.result() == CommandResult(failed=("bulb-1",))
    executor.run_all()
    assert device.applied == []


def test_commands_after_shutdown_fail_immediately(make_service):
    service = make_service(bulb())
    service.shutdown()
    future = service.send(Target.device("bulb-1"), DeviceState(power=True))
    assert future.done()
    assert future.result() == CommandResult(failed=("bulb-1",))


def test_shutdown_leaves_an_injected_executor_running():
    injected = ThreadPoolExecutor(max_workers=1)
    try:
        ControlService([bulb()], executor=injected).shutdown()
        assert injected.submit(lambda: 42).result(timeout=5) == 42
    finally:
        injected.shutdown()


def test_a_refused_submit_fails_the_command_and_frees_the_lane(make_service, executor):
    original = executor.submit
    calls = []

    def flaky_submit(fn, /, *args, **kwargs):
        calls.append(fn)
        if len(calls) == 1:
            raise RuntimeError("cannot schedule new futures")
        return original(fn, *args, **kwargs)

    executor.submit = flaky_submit
    service = make_service(bulb())
    target = Target.device("bulb-1")
    refused = service.send(target, DeviceState(power=True))
    assert refused.result() == CommandResult(failed=("bulb-1",))
    assert done(service.send(target, DeviceState(power=True)), executor).ok


def test_the_lane_survives_an_error_in_the_drain_loop(make_service, executor, clock):
    service = make_service(bulb())
    target = Target.device("bulb-1")
    done(service.send(target, DeviceState(brightness=10)), executor)

    def broken_hook():
        raise RuntimeError("sleep failed")

    clock.on_sleep = broken_hook
    failed = done(service.send(target, DeviceState(brightness=20)), executor)
    assert failed == CommandResult(failed=("bulb-1",))
    clock.now += THROTTLE_INTERVAL
    assert done(service.send(target, DeviceState(brightness=30)), executor).ok


def test_cancelling_a_result_does_not_break_later_commands(make_service, executor):
    service = make_service(bulb())
    target = Target.device("bulb-1")
    service.send(target, DeviceState(power=True)).cancel()
    executor.run_all()
    assert done(service.send(target, DeviceState(power=False)), executor).ok


def test_an_unreachable_device_fails_its_backlog_at_once(make_service, executor):
    log: list = []
    device = LoggingFake("bulb-1", "bulb-1", DeviceType.RGB_BULB, BULB, online=False, log=log)
    service = make_service(device)
    target = Target.device("bulb-1")
    futures = [
        service.send(target, DeviceState(brightness=10)),
        service.send(target, DeviceState(color_hsv=Color(10, 10))),
        service.refresh(target),
    ]
    executor.run_all()
    assert all(f.result() == CommandResult(failed=("bulb-1",)) for f in futures)
    assert log == [("bulb-1", "apply")]  # one timeout, not one per queued job


def test_reads_are_not_throttled(make_service, executor, clock):
    service = make_service(bulb())
    target = Target.device("bulb-1")
    done(service.send(target, DeviceState(power=True)), executor)
    done(service.refresh(target), executor)
    assert clock.sleeps == []


def test_a_failed_write_still_spaces_the_next_write(make_service, executor, clock):
    device = bulb(online=False)
    service = make_service(device)
    done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)
    device.online = True
    done(service.send(Target.device("bulb-1"), DeviceState(power=True)), executor)
    assert clock.sleeps == [THROTTLE_INTERVAL]


def test_the_throttle_counts_from_the_end_of_a_write(executor, clock):
    class SlowFake(FakeDevice):
        def apply(self, changes: DeviceState) -> DeviceState:
            clock.now += 2.0
            return super().apply(changes)

    device = SlowFake("bulb-1", "bulb-1", DeviceType.RGB_BULB, BULB)
    service = ControlService(
        [device], executor=executor, clock=clock, sleep=clock.sleep, throttle=0.5
    )
    done(service.send(Target.device("bulb-1"), DeviceState(brightness=1)), executor)
    done(service.send(Target.device("bulb-1"), DeviceState(brightness=2)), executor)
    assert clock.sleeps == [0.5]


def test_partial_states_merge_into_the_cache(make_service, executor):
    class PartialFake(FakeDevice):
        def apply(self, changes: DeviceState) -> DeviceState:
            super().apply(changes)
            return changes  # only what was written

    device = PartialFake("bulb-1", "bulb-1", DeviceType.RGB_BULB, BULB)
    device.state = DeviceState(power=True, brightness=40)
    service = make_service(device)
    done(service.refresh(Target.device("bulb-1")), executor)
    done(service.send(Target.device("bulb-1"), DeviceState(brightness=70)), executor)
    assert service.state("bulb-1") == DeviceState(power=True, brightness=70)


def test_a_slow_offline_member_does_not_delay_the_others():
    release = threading.Event()

    class HangingFake(FakeDevice):
        def apply(self, changes: DeviceState) -> DeviceState:
            release.wait(timeout=5)  # a socket timeout
            raise DeviceError("timeout")

    slow = HangingFake("bulb-slow", "bulb-slow", DeviceType.RGB_BULB, BULB)
    fast = bulb("bulb-fast")
    service = ControlService([slow, fast])
    fast_done = threading.Event()
    service.state_changed.connect(lambda device_id, _: fast_done.set())
    try:
        result = service.send(ALL_BULBS, DeviceState(power=True))
        assert fast_done.wait(timeout=5)
        assert not result.done()
        release.set()
        assert result.result(timeout=5) == CommandResult(
            succeeded=("bulb-fast",), failed=("bulb-slow",)
        )
    finally:
        release.set()
        service.shutdown()


def test_more_devices_than_the_minimum_pool_still_run_in_parallel():
    count = 10
    barrier = threading.Barrier(count, timeout=5)
    devices = [
        BlockingFake(f"bulb-{n}", f"bulb-{n}", DeviceType.RGB_BULB, BULB, barrier=barrier)
        for n in range(count)
    ]
    service = ControlService(devices)
    try:
        result = service.send(ALL_BULBS, DeviceState(power=True)).result(timeout=10)
    finally:
        service.shutdown()
    assert len(result.succeeded) == count
