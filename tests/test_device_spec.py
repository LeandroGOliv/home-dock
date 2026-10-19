import json
from pathlib import Path

import pytest

from homedock.devices.spec import DeviceSpec, is_lan_address

EXAMPLE = Path(__file__).parents[1] / "devices.example.json"


def example_entry() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))[0]


def test_from_wizard_reads_the_example_entry():
    spec = DeviceSpec.from_wizard(example_entry())
    assert spec.id == "00000000000000000000"
    assert spec.name == "Lâmpada Exemplo"
    assert spec.local_key == "0000000000000000"
    assert spec.ip == "192.0.2.10"
    assert spec.version == "3.4"
    assert spec.category == "dj"
    assert spec.dps_codes["20"] == "switch_led"
    assert spec.dps_codes["24"] == "colour_data_v2"


def test_from_wizard_tolerates_missing_optional_fields():
    spec = DeviceSpec.from_wizard({"id": "dev-1", "key": "key-1"})
    assert spec.ip == ""
    assert spec.version == ""
    assert spec.category == ""
    assert spec.dps_codes == {}
    assert spec.name == "de…-1"


@pytest.mark.parametrize(
    "entry", [{"key": "k"}, {"id": "d"}, {"id": "", "key": "k"}, "not a dict", None]
)
def test_from_wizard_rejects_entries_without_credentials(entry):
    with pytest.raises(ValueError):
        DeviceSpec.from_wizard(entry)


def test_repr_never_shows_key_id_or_ip():
    spec = DeviceSpec(
        id="bf1a2b3c4d5e6f7a8b9c", name="Sala", local_key="fake-local-key", ip="192.0.2.77"
    )
    text = repr(spec)
    assert "fake-local-key" not in text
    assert "bf1a2b3c4d5e6f7a8b9c" not in text
    assert "192.0.2.77" not in text
    assert "bf…9c" in text


@pytest.mark.parametrize(
    "mapping", [["20"], {"20": "switch_led"}, {"20": {"type": "Boolean"}}, None]
)
def test_from_wizard_ignores_malformed_mapping(mapping):
    spec = DeviceSpec.from_wizard({"id": "dev-1", "key": "key-1", "mapping": mapping})
    assert spec.dps_codes == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192.0.2.10", True),
        ("198.51.100.7", True),
        ("8.8.8.8", False),  # public
        ("127.0.0.1", False),
        ("0.0.0.0", False),  # tinytuya scans the network for this one
        ("255.255.255.255", False),
        ("224.0.0.251", False),
        ("169.254.0.9", False),
        ("Auto", False),  # tinytuya scans the network for this one
        ("192.0.2.10:6668", False),
        ("", False),
        (None, False),
    ],
)
def test_only_private_unicast_ipv4_is_a_lan_address(value, expected):
    assert is_lan_address(value) is expected
