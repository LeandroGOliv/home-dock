"""ServiceBridge: control-service events and futures reach the Qt (UI) thread."""

import threading
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from homedock.core import ControlService, Target
from homedock.devices import Capability, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.ui.bridge import ServiceBridge


@pytest.fixture
def service():
    pool = ThreadPoolExecutor(max_workers=2)
    bulb = FakeDevice("bulb-1", "Abajur", DeviceType.RGB_BULB, frozenset({Capability.POWER}))
    service = ControlService([bulb], executor=pool)
    yield service
    service.shutdown()
    pool.shutdown(wait=True)


def test_device_events_are_delivered_on_the_ui_thread(qtbot, service):
    bridge = ServiceBridge(service)
    received = []
    bridge.state_changed.connect(
        lambda device_id, state: received.append((device_id, state, threading.current_thread()))
    )

    with qtbot.waitSignals([bridge.state_changed, bridge.online_changed]):
        service.send(Target.device("bulb-1"), DeviceState(power=True))

    [(device_id, state, thread)] = received
    assert (device_id, state.power) == ("bulb-1", True)
    assert thread is threading.main_thread()


def test_future_callbacks_run_on_the_ui_thread(qtbot, service):
    bridge = ServiceBridge(service)
    threads = []
    future = service.refresh(Target.device("bulb-1"))

    bridge.when_done(future, lambda done: threads.append((done, threading.current_thread())))

    qtbot.waitUntil(lambda: bool(threads))
    assert threads == [(future, threading.main_thread())]


def test_a_future_already_done_still_calls_back_later_on_the_ui_thread(qtbot, service):
    bridge = ServiceBridge(service)
    future: Future = Future()
    future.set_result(None)
    calls = []

    bridge.when_done(future, calls.append)

    assert calls == []  # never re-entrant: the callback is queued
    qtbot.waitUntil(lambda: calls == [future])


def test_detach_stops_forwarding_events(qtbot, service):
    bridge = ServiceBridge(service)
    received = []
    bridge.state_changed.connect(lambda *args: received.append(args))
    bridge.detach()

    service.send(Target.device("bulb-1"), DeviceState(power=True)).result(timeout=5)

    qtbot.wait(50)
    assert received == []
