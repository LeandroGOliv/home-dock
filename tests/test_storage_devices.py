import json
import shutil
from pathlib import Path

import pytest

from homedock.devices import DeviceType, DriverRegistry, UnsupportedReason
from homedock.storage.devices import ImportProblem, import_devices

EXAMPLE = Path(__file__).parents[1] / "devices.example.json"
# Fictitious entry of an unknown device type (e.g. a smart plug).
PLUG = {
    "id": "bf00000000000000plug",
    "key": "plugkey000000000",
    "ip": "192.0.2.20",
    "mac": "00:00:00:00:00:20",
    "name": "Tomada",
    "category": "cz",
}


def write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_example_file_imports_one_rgb_bulb(tmp_path):
    path = tmp_path / "devices.json"
    shutil.copy(EXAMPLE, path)

    result = import_devices(path)

    assert result.problem is None
    [device] = result.catalog.devices
    assert device.type is DeviceType.RGB_BULB
    assert device.name == "Lâmpada Exemplo"
    assert result.catalog.unsupported == []


def test_unknown_and_invalid_entries_are_reported_not_raised(tmp_path):
    path = write(tmp_path / "devices.json", [PLUG, {"name": "sem id"}, "garbage"])

    result = import_devices(path)

    assert result.problem is None
    assert result.catalog.devices == []
    assert [u.reason for u in result.catalog.unsupported] == [
        UnsupportedReason.UNKNOWN_TYPE,
        UnsupportedReason.INVALID_ENTRY,
        UnsupportedReason.INVALID_ENTRY,
    ]


def test_the_registry_can_be_injected(tmp_path):
    path = write(tmp_path / "devices.json", [PLUG])
    assert import_devices(path, DriverRegistry()).catalog.unsupported[0].name == "Tomada"


def test_secrets_lists_every_sensitive_value_of_the_file(tmp_path):
    path = write(tmp_path / "devices.json", [PLUG, {"key": "orphankey0000000"}])

    secrets = import_devices(path).secrets

    assert {
        "bf00000000000000plug",
        "plugkey000000000",
        "192.0.2.20",
        "00:00:00:00:00:20",
        "orphankey0000000",
    } <= secrets
    assert "Tomada" not in secrets
    assert "cz" not in secrets


def test_a_missing_file_is_reported(tmp_path):
    result = import_devices(tmp_path / "devices.json")
    assert result.problem is ImportProblem.MISSING
    assert result.catalog.devices == []
    assert result.secrets == frozenset()


@pytest.mark.parametrize("content", [b"", b"{not json", b"\xff\xfe"])
def test_an_unreadable_file_is_reported(tmp_path, content):
    path = tmp_path / "devices.json"
    path.write_bytes(content)
    assert import_devices(path).problem is ImportProblem.UNREADABLE


@pytest.mark.parametrize("data", [{"devices": []}, "text", 3])
def test_a_file_that_is_not_a_device_list_is_reported(tmp_path, data):
    assert import_devices(write(tmp_path / "devices.json", data)).problem is ImportProblem.INVALID


def test_importing_never_modifies_the_file(tmp_path):
    path = tmp_path / "devices.json"
    shutil.copy(EXAMPLE, path)
    before = path.read_bytes()
    import_devices(path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["devices.json"]
