"""Guards for the layering rules: device specifics stay inside ``homedock.devices``."""

import ast
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


DEVICE_LAYER = sorted((PACKAGE / "devices").rglob("*.py"))
HIGHER_LAYERS = re.compile(r"^\s*(from|import)\s+homedock\.(core|storage|ui)\b", re.MULTILINE)


@pytest.mark.parametrize("path", OUTSIDE_DEVICES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_numeric_dps_keys_outside_the_device_layer(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    numeric = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"\d{1,3}", node.value)
    ]
    assert not numeric, f"{path.name} has DPS-like string keys: {numeric}"


@pytest.mark.parametrize("path", DEVICE_LAYER, ids=lambda p: p.name)
def test_device_layer_never_imports_higher_layers(path):
    assert not HIGHER_LAYERS.search(path.read_text(encoding="utf-8"))


CORE = sorted((PACKAGE / "core").rglob("*.py"))
# The core works with generic devices only: no concrete driver, no higher layer, no Qt.
CORE_FORBIDDEN = re.compile(
    r"\bRgbBulb\b|^\s*(from|import)\s+(homedock\.(storage|ui)|PySide6)\b",
    re.MULTILINE,
)


@pytest.mark.parametrize("path", CORE, ids=lambda p: p.name)
def test_core_is_device_agnostic_and_never_imports_higher_layers(path):
    matches = CORE_FORBIDDEN.findall(path.read_text(encoding="utf-8"))
    assert not matches, f"{path.name} breaks the core layering: {matches}"


@pytest.mark.parametrize(
    "line",
    [
        "from homedock.devices.rgb_bulb import RgbBulb",
        "import homedock.ui",
        "from PySide6 import X",
    ],
)
def test_the_core_guard_catches_violations(line):
    assert CORE_FORBIDDEN.search(line)
