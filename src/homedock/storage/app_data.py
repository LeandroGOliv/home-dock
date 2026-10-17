"""Start-up of the storage layer: logs, device import and config, in that order."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from homedock.masking import RedactingFilter
from homedock.storage.config import Config, load_config, save_config
from homedock.storage.devices import DeviceImport, import_devices
from homedock.storage.files import AppPaths
from homedock.storage.logs import setup_logging

log = logging.getLogger(__name__)


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
