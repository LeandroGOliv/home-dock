from typing import ClassVar

import pytest

from homedock.devices import DeviceError
from homedock.devices import tuya as tuya_module
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
