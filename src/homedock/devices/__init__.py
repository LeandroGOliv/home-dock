"""Device layer: generic device/capability interface and concrete drivers (tinytuya).

DPS mappings live only inside the concrete driver modules of this package.
"""

from homedock.devices.base import (
    Capability,
    Color,
    Device,
    DeviceError,
    DeviceState,
    DeviceType,
    WorkMode,
)
from homedock.devices.registry import (
    DeviceCatalog,
    Driver,
    DriverRegistry,
    UnsupportedDevice,
    UnsupportedReason,
    default_registry,
)
from homedock.devices.spec import DeviceSpec

__all__ = [
    "Capability",
    "Color",
    "Device",
    "DeviceCatalog",
    "DeviceError",
    "DeviceSpec",
    "DeviceState",
    "DeviceType",
    "Driver",
    "DriverRegistry",
    "UnsupportedDevice",
    "UnsupportedReason",
    "WorkMode",
    "default_registry",
]
