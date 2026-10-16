"""Generic device model: types, capabilities and state in device-independent units."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class DeviceType(StrEnum):
    RGB_BULB = "rgb_bulb"


class Capability(StrEnum):
    """What a device can do. Each value is also the name of a :class:`DeviceState` field."""

    POWER = "power"
    WORK_MODE = "work_mode"
    BRIGHTNESS = "brightness"
    COLOR_HSV = "color_hsv"
    COLOR_TEMPERATURE = "color_temperature"


class WorkMode(StrEnum):
    WHITE = "white"
    COLOR = "color"


class DeviceError(RuntimeError):
    """A device could not be reached or rejected a command."""


def _check_range(name: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name} must be within {low}..{high}, got {value}")


@dataclass(frozen=True, slots=True)
class Color:
    """Hue (0-360°) and saturation (0-100 %); the colour's brightness is ``brightness``."""

    hue: int
    saturation: int

    def __post_init__(self) -> None:
        _check_range("hue", self.hue, 0, 360)
        _check_range("saturation", self.saturation, 0, 100)


@dataclass(frozen=True, slots=True)
class DeviceState:
    """A full or partial device state; ``None`` means "unknown" or "unchanged".

    Units: brightness 0-100 %, colour temperature 0-100 % (0 = warmest, 100 = coldest).
    """

    power: bool | None = None
    work_mode: WorkMode | None = None
    brightness: int | None = None
    color_hsv: Color | None = None
    color_temperature: int | None = None

    def __post_init__(self) -> None:
        if self.brightness is not None:
            _check_range("brightness", self.brightness, 0, 100)
        if self.color_temperature is not None:
            _check_range("color_temperature", self.color_temperature, 0, 100)

    @property
    def capabilities(self) -> frozenset[Capability]:
        """The capabilities whose value is set."""
        return frozenset(c for c in Capability if self.get(c) is not None)

    def get(self, capability: Capability) -> Any:
        return getattr(self, capability.value)

    def restricted_to(self, capabilities: Iterable[Capability]) -> DeviceState:
        """A copy keeping only the given capabilities."""
        keep = {c.value for c in capabilities}
        return replace(self, **{f.name: None for f in fields(self) if f.name not in keep})

    def merged(self, changes: DeviceState) -> DeviceState:
        """A copy with every value set in ``changes`` applied on top."""
        updates = {c.value: changes.get(c) for c in changes.capabilities}
        return replace(self, **updates)


@runtime_checkable
class Device(Protocol):
    """A controllable device. I/O methods block: callers run them off the UI thread."""

    id: str
    name: str
    type: DeviceType
    capabilities: frozenset[Capability]
    online: bool

    def read_state(self) -> DeviceState:
        """Read the current state from the device. Raises :class:`DeviceError`."""
        ...

    def apply(self, changes: DeviceState) -> DeviceState:
        """Send ``changes`` and return the resulting state. Raises :class:`DeviceError`.

        Capabilities the device does not support are skipped silently.
        """
        ...
