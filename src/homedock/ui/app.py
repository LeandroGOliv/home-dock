"""Application start-up: one instance, storage, control service, tray icon and flyout."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import replace
from typing import Protocol

from PySide6.QtWidgets import QApplication

from homedock.core import (
    ControlService,
    Group,
    GroupBook,
    Recovery,
    Scene,
    Schedule,
    Target,
    start_timer,
)
from homedock.devices import FoundDevice, scan_lan
from homedock.storage import AppData, DeviceReload, StartWithWindows, open_app_data
from homedock.ui import strings
from homedock.ui.flyout import Flyout
from homedock.ui.single_instance import DEFAULT_NAME, SingleInstance
from homedock.ui.system_theme import SystemTheme
from homedock.ui.tray import TrayController

log = logging.getLogger(__name__)

INSTANCE_NAME = DEFAULT_NAME


class InBackground(Protocol):
    """Runs ``work`` off the UI thread (see :func:`run_in_thread`)."""

    def __call__[T](self, work: Callable[[], T]) -> Future[T]: ...


class HomeDock:
    """The running app: the control service over the imported devices, the recovery of the
    devices that stop answering, flyout and tray."""

    def __init__(
        self,
        data: AppData,
        service: ControlService | None = None,
        scan: Callable[[], Sequence[FoundDevice]] = scan_lan,
        in_background: InBackground | None = None,
        schedule: Schedule = start_timer,
        start_with_windows: StartWithWindows | None = None,
    ) -> None:
        """``scan`` looks for devices on the LAN, ``in_background`` runs the reload of the
        devices off the UI thread, ``schedule`` times the probes of the offline devices and
        ``start_with_windows`` is the Windows ``Run`` entry (all replaceable in tests)."""
        self.data = data
        self.start_with_windows = start_with_windows or StartWithWindows()
        self.service = service or ControlService(
            data.devices.catalog.devices, GroupBook(data.config.groups)
        )
        self._scan = scan
        self._in_background = in_background or run_in_thread
        self._reload_lock = threading.Lock()  # one scan at a time: they share the UDP ports
        self._closed = False
        self.recovery = Recovery(self.service, self._rediscover, schedule=schedule)
        self.recovery.start()
        self.flyout = Flyout(
            self.service,
            names=lambda: self.data.config.names,
            last_target=lambda: self.data.config.settings.last_target,
            set_last_target=self._save_last_target,
            scenes=lambda: self.data.config.scenes,
            save_scenes=self._save_scenes,
            save_names=self._save_names,
            save_groups=self._save_groups,
            reload_devices=self._reload_devices,
        )
        self.tray = TrayController(
            self.service,
            self.flyout,
            names=lambda: self.data.config.names,
            scenes=lambda: self.data.config.scenes,
            start_with_windows=self.start_with_windows.is_enabled,
            set_start_with_windows=self.start_with_windows.set_enabled,
        )
        self.tray.quit_requested.connect(QApplication.quit)

    def show(self) -> None:
        self.tray.show()

    def close(self) -> None:
        self._closed = True
        self.recovery.stop()
        self.tray.close()
        self.flyout.shutdown()
        self.flyout.close()
        self.service.shutdown()

    def _save_last_target(self, target: Target) -> None:
        self._save_settings(last_target=target)

    def _save_scenes(self, scenes: Sequence[Scene]) -> None:
        self.data.save(replace(self.data.config, scenes=tuple(scenes)))

    def _save_names(self, names: Mapping[str, str]) -> None:
        self.data.save(replace(self.data.config, names=dict(names)))

    def _save_groups(self, groups: Sequence[Group]) -> None:
        self.data.save(replace(self.data.config, groups=tuple(groups)))

    def _reload_devices(self) -> Future[DeviceReload]:
        return self._in_background(self._reload)

    def _reload(self) -> DeviceReload:
        """Scan, refresh devices.json and control the devices it now lists (blocks)."""
        with self._reload_lock:
            result = self.data.reload_devices(self._scan)
            if result.devices.problem is None:
                self.service.replace_devices(result.devices.catalog.devices)
            return result

    def _rediscover(self) -> Future[DeviceReload | None]:
        return self._in_background(self._recover)

    def _recover(self) -> DeviceReload | None:
        """The reload asked by the recovery when devices keep failing (blocks).

        A reload already running scans too: wait for it instead (``None``), as after quitting.
        The devices are replaced only when an IP changed: a scan finding the same IPs (a bulb
        left unplugged) leaves the connections of the healthy ones alone.
        """
        if self._closed:
            return None
        if not self._reload_lock.acquire(blocking=False):
            with self._reload_lock:
                return None
        try:
            result = self.data.reload_devices(self._scan)
            if result.devices.problem is None and result.updated_ips and not self._closed:
                log.info("%d device IP(s) changed: controlling them there", result.updated_ips)
                self.service.replace_devices(result.devices.catalog.devices)
            return result
        finally:
            self._reload_lock.release()

    def _save_settings(self, **changes: object) -> None:
        config = self.data.config
        self.data.save(replace(config, settings=replace(config.settings, **changes)))


def run_in_thread[T](work: Callable[[], T]) -> Future[T]:
    """Run ``work`` on a daemon thread: quitting never waits for it (a scan takes seconds)."""
    future: Future[T] = Future()

    def target() -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(work())
        except BaseException as error:
            future.set_exception(error)

    threading.Thread(target=target, name="homedock-reload", daemon=True).start()
    return future


def run(argv: Sequence[str] | None = None) -> int:
    """Run the tray app until the user quits. A second instance exits at once."""
    instance = SingleInstance.acquire(INSTANCE_NAME)
    if instance is None:
        return 0
    with instance:
        app = QApplication.instance() or QApplication(list(argv or sys.argv))
        app.setApplicationName(strings.APP_NAME)
        app.setQuitOnLastWindowClosed(False)  # the flyout is not a main window
        log.info("UI language: %s", strings.language)
        translation = strings.install_qt_translation(app)  # before any widget, like the theme
        system_theme = SystemTheme(app)  # before any widget: they start in the right colours
        home = HomeDock(open_app_data())
        home.show()
        try:
            return app.exec()
        finally:
            home.close()
            system_theme.stop()
            if translation is not None:
                app.removeTranslator(translation)
            log.info("HomeDock closed")
