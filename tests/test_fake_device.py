import pytest

from homedock.devices import Capability, Color, Device, DeviceError, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice

BULB_CAPABILITIES = frozenset(Capability)


def make_fake(**kwargs) -> FakeDevice:
    return FakeDevice(
        id="fake-1",
        name="Fake",
        type=DeviceType.RGB_BULB,
        capabilities=kwargs.pop("capabilities", BULB_CAPABILITIES),
        **kwargs,
    )


def test_fake_device_satisfies_the_device_protocol():
    assert isinstance(make_fake(), Device)


def test_apply_merges_changes_into_the_state():
    fake = make_fake(state=DeviceState(power=False, brightness=50))
    result = fake.apply(DeviceState(power=True, color_hsv=Color(200, 80)))
    expected = DeviceState(power=True, brightness=50, color_hsv=Color(200, 80))
    assert result == expected
    assert fake.read_state() == expected


def test_apply_records_only_supported_changes():
    fake = make_fake(capabilities=frozenset({Capability.POWER}))
    fake.apply(DeviceState(power=True, brightness=10))
    assert fake.applied == [DeviceState(power=True)]
    assert fake.read_state() == DeviceState(power=True)


def test_offline_fake_raises_device_error():
    fake = make_fake(online=False)
    with pytest.raises(DeviceError):
        fake.read_state()
    with pytest.raises(DeviceError):
        fake.apply(DeviceState(power=True))


def test_close_is_recorded_and_the_fake_stays_usable():
    fake = make_fake(state=DeviceState(power=True))
    fake.close()
    assert fake.closed
    assert fake.read_state() == DeviceState(power=True)
