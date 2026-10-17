"""Generic device model: types, capabilities and state in device-independent units."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
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

    def to_dict(self) -> dict[str, Any]:
        """The values that are set, keyed by capability, as JSON-compatible types."""
        return {c.value: _encode(self.get(c)) for c in Capability if self.get(c) is not None}

    @classmethod
    def from_dict(cls, data: object) -> DeviceState:
        """Inverse of :meth:`to_dict`. Unknown keys are ignored; bad values raise ``ValueError``."""
        if not isinstance(data, Mapping):
            raise ValueError("device state must be a mapping")
        values = {c.value: _DECODERS[c](data[c.value]) for c in Capability if c.value in data}
        return cls(**values)


def _encode(value: object) -> object:
    if isinstance(value, Color):
        return {"hue": value.hue, "saturation": value.saturation}
    if isinstance(value, StrEnum):
        return value.value
    return value


def _decode_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"expected a boolean, got {value!r}")
    return value


def _decode_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"expected an integer, got {value!r}")
    return value


def _decode_color(value: object) -> Color:
    if not isinstance(value, Mapping) or not {"hue", "saturation"} <= value.keys():
        raise ValueError(f"expected a hue/saturation mapping, got {value!r}")
    return Color(_decode_int(value["hue"]), _decode_int(value["saturation"]))


_DECODERS: dict[Capability, Callable[[object], Any]] = {
    Capability.POWER: _decode_bool,
    Capability.WORK_MODE: WorkMode,
    Capability.BRIGHTNESS: _decode_int,
    Capability.COLOR_HSV: _decode_color,
    Capability.COLOR_TEMPERATURE: _decode_int,
}


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
