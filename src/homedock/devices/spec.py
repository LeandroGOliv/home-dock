"""Connection data of one Tuya device, as exported by the tinytuya wizard."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from homedock.masking import mask


def is_lan_address(value: object) -> bool:
    """Whether ``value`` is a private unicast IPv4 address, the only kind a device may have.

    Device IPs come from unauthenticated broadcasts and hand-edited files. Anything else
    (public, loopback, broadcast, ``Auto``…) would send the connection off the LAN or make
    tinytuya scan the network on its own.
    """
    try:
        address = ipaddress.IPv4Address(str(value))
    except ValueError:
        return False
    return address.is_private and not (
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_reserved
    )


@dataclass(frozen=True, repr=False)
class DeviceSpec:
    """Everything a driver needs to talk to a device. Holds secrets: never log it raw."""

    id: str
    name: str
    local_key: str
    ip: str = ""
    version: str = ""
    category: str = ""
    dps_codes: Mapping[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"DeviceSpec(id={mask(self.id)!r}, name={self.name!r}, ip={mask(self.ip)!r}, "
            f"version={self.version!r}, category={self.category!r})"
        )

    @classmethod
    def from_wizard(cls, entry: Any) -> DeviceSpec:
        """Build from one entry of the wizard's ``devices.json``. Raises ``ValueError``."""
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("key"):
            raise ValueError("device entry without id or local key")
        device_id = str(entry["id"])
        mapping = entry.get("mapping")
        codes = {
            str(dps): str(info["code"])
            for dps, info in (mapping.items() if isinstance(mapping, dict) else ())
            if isinstance(info, dict) and info.get("code")
        }
        return cls(
            id=device_id,
            name=str(entry.get("name") or mask(device_id)),
            local_key=str(entry["key"]),
            ip=str(entry.get("ip") or ""),
            version=str(entry.get("version") or ""),
            category=str(entry.get("category") or ""),
            dps_codes=codes,
        )
