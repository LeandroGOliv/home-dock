import socket
from typing import ClassVar

import pytest

from homedock.devices import Color, DeviceError, DeviceState, WorkMode
from homedock.devices import tuya as tuya_module
from homedock.devices.rgb_bulb import RgbBulb
from homedock.devices.spec import DeviceSpec
from homedock.devices.tuya import TinyTuyaLink

SPEC = DeviceSpec(id="dev-1", name="Sala", local_key="key-1", ip="192.0.2.10", version="3.4")


class FakeTinyTuyaDevice:
    """Stands in for ``tinytuya.Device``; records how it was configured."""

    instances: ClassVar[list["FakeTinyTuyaDevice"]] = []
    responses: ClassVar[list[object]] = []

    def __init__(self, dev_id, address, local_key, version):
        self.args = (dev_id, address, local_key, version)
        self.persistent = None
        self.max_simultaneous_dps = 0
        self.closed = False
        self.sent = []
        self.socket = object()
        self.unread = []  # messages the device sent that nobody read yet
        FakeTinyTuyaDevice.instances.append(self)

    def set_socketTimeout(self, timeout):  # noqa: N802 (tinytuya API)
        self.timeout = timeout

    def set_socketRetryLimit(self, limit):  # noqa: N802 (tinytuya API)
        self.retry_limit = limit

    def set_socketPersistent(self, persistent):  # noqa: N802 (tinytuya API)
        self.persistent = persistent

    def status(self):
        return self._next()

    def set_multiple_values(self, values):
        self.sent.append(values)
        return self._next()

    def receive(self):
        """Read the next message the device sent, without asking anything."""
        message = self.unread.pop(0) if self.unread else None
        if isinstance(message, Exception):
            raise message
        return message

    def close(self):
        self.closed = True

    def _next(self):
        response = FakeTinyTuyaDevice.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def fake_tinytuya(monkeypatch):
    FakeTinyTuyaDevice.instances = []
    FakeTinyTuyaDevice.responses = []
    monkeypatch.setattr(tuya_module.tinytuya, "Device", FakeTinyTuyaDevice)
    monkeypatch.setattr(tuya_module, "_has_unread", lambda device: bool(device.unread))


def test_connects_lazily_with_a_persistent_socket():
    link = TinyTuyaLink(SPEC)
    assert FakeTinyTuyaDevice.instances == []

    FakeTinyTuyaDevice.responses = [{"dps": {"20": True}}]
    link.status()

    (device,) = FakeTinyTuyaDevice.instances
    assert device.args == ("dev-1", "192.0.2.10", "key-1", 3.4)
    assert device.persistent is True


def test_status_returns_dps_with_string_keys():
    FakeTinyTuyaDevice.responses = [{"dps": {20: True, "21": "white"}}]
    assert TinyTuyaLink(SPEC).status() == {"20": True, "21": "white"}


def test_response_without_dps_is_empty():
    FakeTinyTuyaDevice.responses = [None, {"other": 1}]
    link = TinyTuyaLink(SPEC)
    assert link.set_values({"20": True}) == {}
    assert link.status() == {}


def test_error_response_raises_and_drops_the_socket():
    FakeTinyTuyaDevice.responses = [{"Err": "905", "Error": "Device Unreachable"}]
    link = TinyTuyaLink(SPEC)
    with pytest.raises(DeviceError, match="905"):
        link.status()
    assert FakeTinyTuyaDevice.instances[0].closed

    FakeTinyTuyaDevice.responses = [{"dps": {"20": True}}]
    link.status()
    assert len(FakeTinyTuyaDevice.instances) == 2


def test_library_exception_becomes_device_error():
    FakeTinyTuyaDevice.responses = [OSError("socket closed")]
    with pytest.raises(DeviceError):
        TinyTuyaLink(SPEC).status()


def test_missing_ip_raises_without_connecting():
    link = TinyTuyaLink(DeviceSpec(id="dev-1", name="Sala", local_key="key-1"))
    with pytest.raises(DeviceError):
        link.status()
    assert FakeTinyTuyaDevice.instances == []


def test_error_messages_never_contain_the_key_or_ip():
    FakeTinyTuyaDevice.responses = [OSError("connect to 192.0.2.10 with key-1 failed")]
    with pytest.raises(DeviceError) as info:
        TinyTuyaLink(SPEC).status()
    assert "192.0.2.10" not in str(info.value)
    assert "key-1" not in str(info.value)


def test_defaults_to_protocol_3_4():
    FakeTinyTuyaDevice.responses = [{"dps": {}}]
    TinyTuyaLink(DeviceSpec(id="dev-1", name="Sala", local_key="key-1", ip="192.0.2.10")).status()
    assert FakeTinyTuyaDevice.instances[0].args[3] == 3.4


@pytest.mark.parametrize("version", ["v3.4", "3.2", "9"])
def test_unsupported_version_raises_without_connecting(version):
    spec = DeviceSpec(id="dev-1", name="Sala", local_key="key-1", ip="192.0.2.10", version=version)
    with pytest.raises(DeviceError):
        TinyTuyaLink(spec).status()
    assert FakeTinyTuyaDevice.instances == []


def test_set_values_sends_one_multi_dps_command():
    FakeTinyTuyaDevice.responses = [{"dps": {"21": "colour"}}]
    TinyTuyaLink(SPEC).set_values({"21": "colour", "24": "000003e803e8"})
    assert FakeTinyTuyaDevice.instances[0].sent == [{"21": "colour", "24": "000003e803e8"}]


def test_one_dps_at_a_time_fallback_does_not_stick():
    # tinytuya switches to one DPS per command (1 s apart) for good after a single error.
    FakeTinyTuyaDevice.responses = [{"dps": {}}]
    link = TinyTuyaLink(SPEC)
    link.set_values({"20": True, "21": "white"})
    (device,) = FakeTinyTuyaDevice.instances
    device.max_simultaneous_dps = 1
    FakeTinyTuyaDevice.responses = [{"dps": {}}]
    link.set_values({"20": True, "21": "white"})
    assert device.max_simultaneous_dps == 0


def test_exception_drops_the_socket_and_reconnects():
    FakeTinyTuyaDevice.responses = [OSError("reset"), {"dps": {"20": True}}]
    link = TinyTuyaLink(SPEC)
    with pytest.raises(DeviceError):
        link.status()
    assert link.status() == {"20": True}
    assert len(FakeTinyTuyaDevice.instances) == 2
    assert FakeTinyTuyaDevice.instances[0].closed


def test_idle_socket_is_reopened():
    now = [0.0]
    link = TinyTuyaLink(SPEC, idle_timeout=20.0, clock=lambda: now[0])
    FakeTinyTuyaDevice.responses = [{"dps": {}}, {"dps": {}}, {"dps": {}}]
    link.status()
    now[0] += 19
    link.status()
    assert len(FakeTinyTuyaDevice.instances) == 1
    now[0] += 21
    link.status()
    assert len(FakeTinyTuyaDevice.instances) == 2
    assert FakeTinyTuyaDevice.instances[0].closed


# --- messages the device sent unasked -----------------------------------------------------------


def connected_link() -> tuple[TinyTuyaLink, FakeTinyTuyaDevice]:
    FakeTinyTuyaDevice.responses = [{"dps": {}}]
    link = TinyTuyaLink(SPEC)
    link.status()
    return link, FakeTinyTuyaDevice.instances[-1]


def test_unread_pushes_are_read_first_and_returned_under_the_answer():
    link, device = connected_link()
    device.unread = [{"dps": {"23": 200}}, {"dps": {"22": 100}}]
    FakeTinyTuyaDevice.responses = [{"dps": {"20": True, "22": 800}}]

    assert link.status() == {"23": 200, "22": 800, "20": True}
    assert device.unread == []


def test_an_old_full_status_never_wins_over_the_answer():
    link, device = connected_link()
    device.unread = [{"dps": {"21": "colour", "22": 500}}]
    FakeTinyTuyaDevice.responses = [{"dps": {"21": "white", "22": 800}}]

    assert link.status() == {"21": "white", "22": 800}


def test_unread_messages_are_read_before_a_write_too():
    link, device = connected_link()
    device.unread = [{"dps": {"23": 200}}]
    FakeTinyTuyaDevice.responses = [{"dps": {"21": "colour"}}]

    assert link.set_values({"21": "colour"}) == {"23": 200, "21": "colour"}
    assert device.unread == []


def test_nothing_unread_reads_nothing_more():
    link, device = connected_link()
    device.receive = None  # would fail if called
    FakeTinyTuyaDevice.responses = [{"dps": {"20": False}}]

    assert link.status() == {"20": False}


def test_a_dead_socket_found_while_reading_unread_messages_is_reopened():
    for dead in ({"Err": "901", "Error": "Network Error"}, ConnectionResetError("reset")):
        FakeTinyTuyaDevice.instances = []
        link, device = connected_link()
        device.unread = [dead]
        FakeTinyTuyaDevice.responses = [{"dps": {"20": True}}]

        assert link.set_values({"20": True}) == {"20": True}
        assert device.closed
        old, new = FakeTinyTuyaDevice.instances
        assert old.sent == [] and new.sent == [{"20": True}]  # the new socket got the write


def test_at_most_max_unread_messages_are_read_before_a_call():
    link, device = connected_link()
    device.unread = [{"dps": {"22": n}} for n in range(tuya_module.MAX_UNREAD + 5)]
    FakeTinyTuyaDevice.responses = [{"dps": {}}]

    assert link.status() == {"22": tuya_module.MAX_UNREAD - 1}
    assert len(device.unread) == 5


def test_the_normal_timeout_is_back_after_reading_unread_messages():
    link, device = connected_link()
    for unread in ([{"dps": {"20": True}}], [OSError("reset")]):
        device.unread = list(unread)
        device.timeout = None
        FakeTinyTuyaDevice.responses = [{"dps": {}}]
        link.status()
        assert device.timeout == 5.0


def test_has_unread_sees_data_waiting_on_the_socket(monkeypatch):
    monkeypatch.undo()  # the real check, on a local socket pair (no network)
    ours, theirs = socket.socketpair()
    try:
        device = type("Device", (), {"socket": ours})()
        assert not tuya_module._has_unread(device)
        theirs.sendall(b"push")
        assert tuya_module._has_unread(device)
        device.socket = None
        assert not tuya_module._has_unread(device)
    finally:
        ours.close()
        theirs.close()
    assert not tuya_module._has_unread(type("Device", (), {"socket": ours})())  # closed


def test_tinytuya_devices_have_the_socket_and_receive_we_rely_on(monkeypatch):
    monkeypatch.undo()
    device = tuya_module.tinytuya.Device("dev-1", "192.0.2.10", "0123456789abcdef", version=3.4)
    assert hasattr(device, "socket")
    assert callable(device.receive)


class QueuedBulb(FakeTinyTuyaDevice):
    """Behaves like the real PSBAM bulb on a persistent socket.

    A status query is answered by one full status; a write by an empty ack and then one
    push per DPS that changed. tinytuya reads one non-empty message per call, so the other
    pushes wait on the socket and the next call would read them as its own answer.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Blue: switching to red changes DPS 21 and 24, so a write leaves a push behind.
        self.dps = {"20": True, "21": "white", "22": 850, "23": 610, "24": "00f003e803e8"}

    def status(self):
        self.unread.append({"dps": dict(self.dps)})
        return self.unread.pop(0)

    def set_multiple_values(self, values):
        self.sent.append(values)
        changed = {k: v for k, v in values.items() if self.dps.get(k) != v}
        self.dps.update(values)
        self.unread.extend({"dps": {k: v}} for k, v in changed.items())
        return self.unread.pop(0) if self.unread else None

    def change_elsewhere(self, dp, value):
        """E.g. the Tuya app or a wall switch: the bulb pushes the change."""
        self.dps[dp] = value
        self.unread.append({"dps": {dp: value}})


BULB_SPEC = DeviceSpec(
    id="dev-1",
    name="Sala",
    local_key="key-1",
    ip="192.0.2.10",
    version="3.4",
    category="dj",
    dps_codes={
        "20": "switch_led",
        "21": "work_mode",
        "22": "bright_value_v2",
        "23": "temp_value_v2",
        "24": "colour_data_v2",
    },
)
WHITE = DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=80, color_temperature=20)
RED = DeviceState(power=True, work_mode=WorkMode.COLOR, brightness=50, color_hsv=Color(0, 100))


@pytest.fixture
def queued_bulb(monkeypatch) -> RgbBulb:
    monkeypatch.setattr(tuya_module.tinytuya, "Device", QueuedBulb)
    return RgbBulb(BULB_SPEC, connect=TinyTuyaLink)


def test_the_bulb_state_is_right_after_writes_that_leave_pushes_behind(queued_bulb):
    for changes in (WHITE, RED, WHITE, RED, WHITE):
        queued_bulb.apply(changes)
        state = queued_bulb.read_state()
        assert state.restricted_to(changes.capabilities) == changes
        assert queued_bulb.read_state() == state  # and again
        assert FakeTinyTuyaDevice.instances[-1].unread == []  # nothing old left behind


def test_a_change_made_elsewhere_is_seen_after_writes_left_messages_behind(queued_bulb):
    queued_bulb.apply(WHITE)
    queued_bulb.read_state()
    queued_bulb.apply(RED)
    queued_bulb.read_state()

    FakeTinyTuyaDevice.instances[-1].change_elsewhere("20", False)

    assert queued_bulb.read_state().power is False
