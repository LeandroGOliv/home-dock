"""Start-up of the storage layer: logs, device import and config, in that order."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from homedock.devices import DeviceError, FoundDevice
from homedock.masking import RedactingFilter
from homedock.storage.config import Config, load_config, save_config
from homedock.storage.devices import DeviceImport, IpUpdate, import_devices, update_ips
from homedock.storage.files import AppPaths
from homedock.storage.logs import setup_logging

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceReload:
    """What a reload of the devices found. ``devices`` is the new import; when its
    ``problem`` is set, the devices imported before are kept."""

    devices: DeviceImport
    updated_ips: int = 0
    not_imported: int = 0  # Tuya devices on the LAN missing from devices.json
    scan_failed: bool = False
    write_failed: bool = False  # the new IPs could not be written to devices.json


@dataclass
class AppData:
    """What the app loaded from ``paths.root``. ``config_backup``: see :class:`LoadedConfig`."""

    paths: AppPaths
    devices: DeviceImport
    config: Config
    config_backup: Path | None
    log_filter: RedactingFilter

    def save(self, config: Config) -> None:
        """Persist ``config`` (atomically) and keep it as the current one. Raises ``OSError``."""
        save_config(self.paths.config_file, config)
        self.config = config

    def reload_devices(self, scan: Callable[[], Sequence[FoundDevice]]) -> DeviceReload:
        """Scan the LAN, write the IPs found into ``devices.json`` and import it again.

        Blocks for the whole scan: call it off the UI thread. A failed scan still re-imports
        the file. Never raises.
        """
        scan_failed = write_failed = False
        try:
            found = list(scan())
        except DeviceError as error:
            log.warning("cannot scan the network: %s", error)
            found, scan_failed = [], True
        self.log_filter.add(*(value for device in found for value in (device.id, device.ip)))
        update = IpUpdate()
        if found:
            try:
                update = update_ips(self.paths.devices_file, found)
            except OSError as error:
                log.error("cannot write the devices file: %s", type(error).__name__)
                write_failed = True
        devices = import_devices(self.paths.devices_file)
        self.log_filter.add(*devices.secrets)
        if devices.problem is None:
            self.devices = devices
        log.info(
            "devices reloaded: %d found on the network, %d IP(s) updated, %d not imported",
            len(found),
            update.updated,
            update.not_imported,
        )
        return DeviceReload(devices, update.updated, update.not_imported, scan_failed, write_failed)


def open_app_data(paths: AppPaths | None = None) -> AppData:
    """Set up logging, import the devices and load the config (creating it if needed).

    The log masks every sensitive value of ``devices.json`` from then on.
    """
    paths = paths or AppPaths.default()
    log_filter = setup_logging(paths.logs_dir)
    log.info("starting HomeDock")
    devices = import_devices(paths.devices_file)
    log_filter.add(*devices.secrets)
    loaded = load_config(paths.config_file)
    data = AppData(paths, devices, loaded.config, loaded.backup, log_filter)
    if not paths.config_file.exists():
        try:
            data.save(loaded.config)
        except OSError as error:
            log.error("cannot write the config file: %s", type(error).__name__)
    return data
