"""Import of ``devices.json`` (the Tuya wizard output copied to %APPDATA%\\HomeDock).

The file holds local keys, device IDs and IPs: every sensitive value read is returned in
:attr:`DeviceImport.secrets` so the logs can mask it. The app only changes the IPs (and a
missing protocol version) of its entries, with what a LAN scan found.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from homedock.devices import DeviceCatalog, DriverRegistry, FoundDevice, default_registry
from homedock.storage.files import write_atomic

log = logging.getLogger(__name__)

SECRET_FIELDS = ("id", "key", "local_key", "ip", "mac", "uuid", "sn", "node_id")
# Shorter values (e.g. a placeholder) would mask unrelated text in the logs.
MIN_SECRET_LENGTH = 6


class ImportProblem(StrEnum):
    MISSING = "missing"  # no devices.json yet: the user has not run the wizard
    UNREADABLE = "unreadable"  # I/O error, invalid UTF-8 or invalid JSON
    INVALID = "invalid"  # valid JSON, but not a list of devices


@dataclass(frozen=True)
class DeviceImport:
    catalog: DeviceCatalog = field(default_factory=DeviceCatalog)
    secrets: frozenset[str] = field(default=frozenset(), repr=False)
    problem: ImportProblem | None = None


@dataclass(frozen=True, slots=True)
class IpUpdate:
    updated: int = 0  # entries whose IP was filled in or changed
    not_imported: int = 0  # Tuya devices found on the LAN that are not in the file


def import_devices(path: Path, registry: DriverRegistry | None = None) -> DeviceImport:
    """Build the devices listed in ``path``. Never connects and never raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        log.info("no devices file yet")
        return DeviceImport(problem=ImportProblem.MISSING)
    except (OSError, ValueError) as error:
        log.error("cannot read the devices file: %s", type(error).__name__)
        return DeviceImport(problem=ImportProblem.UNREADABLE)
    if not isinstance(data, list):
        log.error("the devices file is not a list of devices")
        return DeviceImport(problem=ImportProblem.INVALID)
    catalog = (registry or default_registry()).load(data)
    log.info(
        "imported %d device(s), %d unsupported", len(catalog.devices), len(catalog.unsupported)
    )
    return DeviceImport(catalog, _secrets(data))


def update_ips(path: Path, found: Iterable[FoundDevice]) -> IpUpdate:
    """Write the IPs found by a LAN scan into ``path``: entries whose IP is empty or another
    one get the new IP (and the protocol version found, when they have none).

    The file is rewritten atomically, only when something changed; every other field is
    kept. A file that cannot be read is left alone (the import reports it). Raises
    ``OSError`` when the file cannot be written.
    """
    by_id = {device.id: device for device in found}
    try:
        entries = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return IpUpdate(not_imported=len(by_id))
    except (OSError, ValueError) as error:
        log.error("cannot read the devices file: %s", type(error).__name__)
        return IpUpdate()
    if not isinstance(entries, list):
        return IpUpdate()
    known = {str(e.get("id")) for e in entries if isinstance(e, dict)}
    updated = 0
    changed = False
    for entry in entries:
        device = by_id.get(str(entry.get("id"))) if isinstance(entry, dict) else None
        if device is None:
            continue
        if entry.get("ip") != device.ip:
            entry["ip"] = device.ip
            updated += 1
            changed = True
        if not entry.get("version") and device.version:
            entry["version"] = device.version
            changed = True
    if changed:
        write_atomic(path, _dump(entries))
    return IpUpdate(updated, len(by_id.keys() - known))


def _dump(entries: list[Any]) -> str:
    """The wizard's own layout (4-space indent), so the file stays familiar."""
    return json.dumps(entries, ensure_ascii=False, indent=4) + "\n"


def _secrets(entries: list[object]) -> frozenset[str]:
    return frozenset(
        value.strip()
        for entry in entries
        if isinstance(entry, dict)
        for name in SECRET_FIELDS
        if isinstance(value := entry.get(name), str) and len(value.strip()) >= MIN_SECRET_LENGTH
    )
