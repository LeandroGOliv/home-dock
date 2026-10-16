"""Guards for the layering rules: device specifics stay inside ``homedock.devices``."""

import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[1] / "src" / "homedock"
OUTSIDE_DEVICES = sorted(p for p in PACKAGE.rglob("*.py") if PACKAGE / "devices" not in p.parents)
# Tuya DPS codes and driver modules that only the device layer may know about.
FORBIDDEN = re.compile(
    r"switch_led|bright_value|temp_value|colour_data|scene_data|tinytuya|"
    r"devices\.(rgb_bulb|tuya)\b|\bdps\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", OUTSIDE_DEVICES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_dps_knowledge_outside_the_device_layer(path):
    matches = FORBIDDEN.findall(path.read_text(encoding="utf-8"))
    assert not matches, f"{path.name} references device internals: {matches}"
