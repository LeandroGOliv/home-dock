"""Discovery of Tuya devices on the LAN, from the UDP broadcasts they send (tinytuya scanner).

The scan never connects to a device (they accept one TCP client at a time, and the control
service may hold that connection): it listens for their broadcasts, and tinytuya sends its
own discovery request now and then. The IPs come from unauthenticated broadcasts, so only
private LAN addresses are kept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tinytuya import scanner as tinytuya_scanner

from homedock.devices.base import DeviceError
from homedock.devices.spec import is_lan_address

SCAN_TIME = 18.0  # seconds; Tuya devices broadcast every few seconds
# Given no devices, tinytuya loads a devices.json from the working directory: hand it a
# placeholder instead (only used to look up names and keys, which the scan does not need).
_NO_DEVICES = [{"id": "", "key": "", "name": "", "mac": ""}]

Scanner = Callable[..., Any]


@dataclass(frozen=True)
class FoundDevice:
    """A device that answered a scan. ``id`` and ``ip`` are sensitive: kept out of the repr."""

    id: str = field(repr=False)
    ip: str = field(repr=False)
    version: str = ""


def scan_lan(scan_time: float = SCAN_TIME, scanner: Scanner | None = None) -> list[FoundDevice]:
    """The Tuya devices broadcasting on the LAN within ``scan_time`` seconds.

    Blocks for the whole scan. Raises :class:`DeviceError` when it cannot run (e.g. another
    program holds the UDP ports).
    """
    scan = scanner or tinytuya_scanner.devices
    try:
        reply = scan(
            verbose=False,
            scantime=scan_time,
            color=False,
            poll=False,
            forcescan=False,
            byID=True,
            tuyadevices=_NO_DEVICES,
        )
    except Exception as exc:  # library boundary: tinytuya may raise anything
        # The message may embed an IP: report only the type.
        raise DeviceError(f"network scan failed ({type(exc).__name__})") from None
    found = []
    for device_id, info in (reply or {}).items():
        if not isinstance(info, dict) or not device_id or not is_lan_address(info.get("ip")):
            continue
        found.append(FoundDevice(str(device_id), str(info["ip"]), str(info.get("version") or "")))
    return found
