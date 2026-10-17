"""Import of ``devices.json`` (the Tuya wizard output copied to %APPDATA%\\HomeDock).

The file holds local keys, device IDs and IPs: it is only read here, and every sensitive
value is returned in :attr:`DeviceImport.secrets` so the logs can mask it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from homedock.devices import DeviceCatalog, DriverRegistry, default_registry

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


def _secrets(entries: list[object]) -> frozenset[str]:
    return frozenset(
        value.strip()
        for entry in entries
        if isinstance(entry, dict)
        for name in SECRET_FIELDS
        if isinstance(value := entry.get(name), str) and len(value.strip()) >= MIN_SECRET_LENGTH
    )
