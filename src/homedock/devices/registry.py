"""Driver registry: picks the driver for each wizard entry; unknown devices are unsupported."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from homedock.devices.base import Device
from homedock.devices.rgb_bulb import RgbBulb
from homedock.devices.spec import DeviceSpec
from homedock.devices.tuya import LinkFactory, connect_tinytuya
from homedock.masking import mask

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Driver:
    name: str
    matches: Callable[[DeviceSpec], bool]
    create: Callable[[DeviceSpec, LinkFactory], Device]


class UnsupportedReason(StrEnum):
    INVALID_ENTRY = "invalid_entry"  # missing id or local key
    UNKNOWN_TYPE = "unknown_type"  # no driver matches the category / DPS signature


@dataclass(frozen=True)
class UnsupportedDevice:
    id: str = field(repr=False)
    name: str
    category: str
    reason: UnsupportedReason


@dataclass
class DeviceCatalog:
    devices: list[Device] = field(default_factory=list)
    unsupported: list[UnsupportedDevice] = field(default_factory=list)


class DriverRegistry:
    def __init__(self, drivers: Iterable[Driver] = ()) -> None:
        self._drivers = list(drivers)

    def register(self, driver: Driver) -> None:
        self._drivers.append(driver)

    def driver_for(self, spec: DeviceSpec) -> Driver | None:
        return next((d for d in self._drivers if d.matches(spec)), None)

    def load(
        self, entries: Iterable[object], connect: LinkFactory = connect_tinytuya
    ) -> DeviceCatalog:
        """Create a device per wizard entry. Never connects and never fails on bad entries."""
        catalog = DeviceCatalog()
        for entry in entries:
            info = entry if isinstance(entry, dict) else {}
            try:
                spec = DeviceSpec.from_wizard(entry)
            except ValueError:
                log.warning("skipping invalid device entry %s", mask(info.get("id")))
                catalog.unsupported.append(
                    UnsupportedDevice(
                        id=str(info.get("id") or ""),
                        name=str(info.get("name") or ""),
                        category=str(info.get("category") or ""),
                        reason=UnsupportedReason.INVALID_ENTRY,
                    )
                )
                continue
            driver = self.driver_for(spec)
            if driver is None:
                log.info("unsupported device %s (category %r)", mask(spec.id), spec.category)
                catalog.unsupported.append(
                    UnsupportedDevice(
                        spec.id, spec.name, spec.category, UnsupportedReason.UNKNOWN_TYPE
                    )
                )
                continue
            catalog.devices.append(driver.create(spec, connect))
        return catalog


RGB_BULB_DRIVER = Driver(name="rgb_bulb", matches=RgbBulb.matches, create=RgbBulb)


def default_registry() -> DriverRegistry:
    return DriverRegistry([RGB_BULB_DRIVER])
