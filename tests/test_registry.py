import json
from pathlib import Path

from homedock.devices import DeviceType
from homedock.devices.fake import FakeDevice
from homedock.devices.registry import (
    Driver,
    DriverRegistry,
    UnsupportedReason,
    default_registry,
)
from homedock.devices.rgb_bulb import RgbBulb

EXAMPLE = Path(__file__).parents[1] / "devices.example.json"


def example_bulb() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))[0]


def no_network(_spec):
    raise AssertionError("loading must not connect to devices")


def test_default_registry_loads_the_example_bulb_as_rgb_bulb():
    catalog = default_registry().load([example_bulb()], connect=no_network)
    (device,) = catalog.devices
    assert isinstance(device, RgbBulb)
    assert device.type is DeviceType.RGB_BULB
    assert device.name == "Lâmpada Exemplo"
    assert catalog.unsupported == []


def test_unknown_device_is_listed_as_unsupported():
    plug = {"id": "plug-0001", "key": "key-0001", "name": "Tomada", "category": "cz"}
    catalog = default_registry().load([plug, example_bulb()], connect=no_network)
    assert len(catalog.devices) == 1
    (unsupported,) = catalog.unsupported
    assert (unsupported.name, unsupported.category) == ("Tomada", "cz")
    assert unsupported.reason is UnsupportedReason.UNKNOWN_TYPE


def test_invalid_entries_do_not_break_loading():
    entries = ["garbage", None, {"name": "sem credenciais"}, example_bulb()]
    catalog = default_registry().load(entries, connect=no_network)
    assert len(catalog.devices) == 1
    assert [u.reason for u in catalog.unsupported] == [UnsupportedReason.INVALID_ENTRY] * 3
    assert catalog.unsupported[2].name == "sem credenciais"


def test_first_matching_driver_wins():
    def fake_driver(name):
        return Driver(
            name=name,
            matches=lambda spec: spec.category == "xx",
            create=lambda spec, _connect: FakeDevice(
                id=spec.id, name=name, type=DeviceType.RGB_BULB, capabilities=frozenset()
            ),
        )

    registry = DriverRegistry([fake_driver("first")])
    registry.register(fake_driver("second"))
    entry = {"id": "dev-1", "key": "key-1", "category": "xx"}
    (device,) = registry.load([entry], connect=no_network).devices
    assert device.name == "first"


def test_unsupported_repr_masks_the_id():
    entry = {"id": "bf1a2b3c4d5e6f7a8b9c", "key": "key-1", "category": "cz"}
    (unsupported,) = default_registry().load([entry], connect=no_network).unsupported
    assert "bf1a2b3c4d5e6f7a8b9c" not in repr(unsupported)


def test_load_logs_only_masked_ids(caplog):
    entries = [
        {"id": "bf1a2b3c4d5e6f7a8b9c", "key": "key-1", "category": "cz"},
        {"id": "cf1a2b3c4d5e6f7a8b9d"},
    ]
    with caplog.at_level("DEBUG", logger="homedock"):
        default_registry().load(entries, connect=no_network)
    assert caplog.records
    assert "bf1a2b3c4d5e6f7a8b9c" not in caplog.text
    assert "cf1a2b3c4d5e6f7a8b9d" not in caplog.text
