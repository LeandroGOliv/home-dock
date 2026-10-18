import json
import shutil
from pathlib import Path

import pytest

from homedock.devices import DeviceType, DriverRegistry, FoundDevice, UnsupportedReason
from homedock.storage.devices import ImportProblem, IpUpdate, import_devices, update_ips

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


def test_short_values_are_not_treated_as_secrets(tmp_path):
    # Masking "1" or "abc" would garble unrelated log text.
    path = write(tmp_path / "devices.json", [{**PLUG, "sn": "abc", "uuid": "12345"}])
    secrets = import_devices(path).secrets
    assert "abc" not in secrets
    assert "12345" not in secrets
    assert "plugkey000000000" in secrets


# --- IPs found by a LAN scan ----------------------------------------------------------------

BULB_ID = "00000000000000000000"  # the example entry


def example_file(tmp_path: Path, **changes) -> Path:
    entries = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    entries[0].update(changes)
    return write(tmp_path / "devices.json", entries)


def entries_of(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_an_empty_ip_is_filled_from_the_scan(tmp_path):
    path = example_file(tmp_path, ip="")
    result = update_ips(path, [FoundDevice(BULB_ID, "192.0.2.30", "3.4")])
    assert result == IpUpdate(updated=1, not_imported=0)
    assert entries_of(path)[0]["ip"] == "192.0.2.30"


def test_a_changed_ip_is_replaced_and_the_rest_of_the_entry_kept(tmp_path):
    path = example_file(tmp_path, ip="192.0.2.5")
    before = entries_of(path)[0]
    update_ips(path, [FoundDevice(BULB_ID, "192.0.2.31", "3.4")])
    assert entries_of(path)[0] == {**before, "ip": "192.0.2.31"}


def test_a_missing_protocol_version_is_filled_but_a_known_one_kept(tmp_path):
    path = example_file(tmp_path, version="")
    update_ips(path, [FoundDevice(BULB_ID, "192.0.2.30", "3.4")])
    assert entries_of(path)[0]["version"] == "3.4"
    path = example_file(tmp_path, version="3.3")
    update_ips(path, [FoundDevice(BULB_ID, "192.0.2.30", "3.4")])
    assert entries_of(path)[0]["version"] == "3.3"


def test_an_unchanged_file_is_not_rewritten(tmp_path):
    path = example_file(tmp_path, ip="192.0.2.30")
    before = path.read_bytes()
    result = update_ips(path, [FoundDevice(BULB_ID, "192.0.2.30", "3.4")])
    assert result == IpUpdate(updated=0, not_imported=0)
    assert path.read_bytes() == before


def test_devices_on_the_lan_missing_from_the_file_are_counted(tmp_path):
    path = example_file(tmp_path, ip="192.0.2.30")
    found = [FoundDevice(BULB_ID, "192.0.2.30"), FoundDevice("bf00000000000000new1", "192.0.2.40")]
    assert update_ips(path, found) == IpUpdate(updated=0, not_imported=1)


def test_without_a_file_every_device_found_is_missing_from_it(tmp_path):
    path = tmp_path / "devices.json"
    assert update_ips(path, [FoundDevice(BULB_ID, "192.0.2.30")]) == IpUpdate(0, 1)
    assert not path.exists()


@pytest.mark.parametrize("content", ["{oops", '{"not": "a list"}'])
def test_an_unreadable_file_is_left_alone(tmp_path, content):
    path = tmp_path / "devices.json"
    path.write_text(content, encoding="utf-8")
    assert update_ips(path, [FoundDevice(BULB_ID, "192.0.2.30")]) == IpUpdate()
    assert path.read_text(encoding="utf-8") == content


def test_a_file_with_a_bom_is_updated(tmp_path):
    path = tmp_path / "devices.json"
    entries = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    path.write_text(json.dumps(entries), encoding="utf-8-sig")
    assert update_ips(path, [FoundDevice(BULB_ID, "192.0.2.30")]).updated == 1
    assert entries_of(path)[0]["ip"] == "192.0.2.30"
