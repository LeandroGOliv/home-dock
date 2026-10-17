"""Application start-up: one instance, storage, control service, tray icon and flyout."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from homedock.core import ControlService, GroupBook, Target
from homedock.storage import AppData, open_app_data
from homedock.ui import strings
from homedock.ui.flyout import Flyout
from homedock.ui.single_instance import DEFAULT_NAME, SingleInstance
from homedock.ui.tray import TrayController

log = logging.getLogger(__name__)

INSTANCE_NAME = DEFAULT_NAME


class HomeDock:
    """The running app: the control service over the imported devices, flyout and tray."""

    def __init__(self, data: AppData, service: ControlService | None = None) -> None:
        self.data = data
        self.service = service or ControlService(
            data.devices.catalog.devices, GroupBook(data.config.groups)
        )
        self.flyout = Flyout(
            self.service,
            names=lambda: self.data.config.names,
            last_target=lambda: self.data.config.settings.last_target,
            set_last_target=self._save_last_target,
        )
        self.tray = TrayController(
            self.service,
            self.flyout,
            names=lambda: self.data.config.names,
            scenes=lambda: self.data.config.scenes,
            start_with_windows=lambda: self.data.config.settings.start_with_windows,
            set_start_with_windows=self._save_start_with_windows,
        )
        self.tray.quit_requested.connect(QApplication.quit)

    def show(self) -> None:
        self.tray.show()

    def close(self) -> None:
        self.tray.close()
        self.flyout.shutdown()
        self.flyout.close()
        self.service.shutdown()

    def _save_start_with_windows(self, enabled: bool) -> None:
        # Only the preference for now; the Windows "Run" entry comes with issue #15.
        self._save_settings(start_with_windows=enabled)

    def _save_last_target(self, target: Target) -> None:
        self._save_settings(last_target=target)

    def _save_settings(self, **changes: object) -> None:
        config = self.data.config
        self.data.save(replace(config, settings=replace(config.settings, **changes)))


def run(argv: Sequence[str] | None = None) -> int:
    """Run the tray app until the user quits. A second instance exits at once."""
    instance = SingleInstance.acquire(INSTANCE_NAME)
    if instance is None:
        return 0
    with instance:
        app = QApplication.instance() or QApplication(list(argv or sys.argv))
        app.setApplicationName(strings.APP_NAME)
        app.setQuitOnLastWindowClosed(False)  # the flyout is not a main window
        home = HomeDock(open_app_data())
        home.show()
        try:
            return app.exec()
        finally:
            home.close()
            log.info("HomeDock closed")
