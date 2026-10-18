"""Tray icon and its context menu.

Left click toggles the flyout. The right-click menu offers: Abrir painel · Ligar todos ·
Desligar todos · a toggle per device (showing its current state) · Cenas ▸ · Iniciar com o
Windows ☑ · Sair. Works on generic devices: every device with the ``power`` capability gets
a toggle. Commands go through the control service and never block the UI thread; the menu
reads the real device state each time it opens and updates live as answers arrive.
Checkable items keep the menu open, so several devices can be toggled in a row.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from functools import partial
from typing import Any, Protocol

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from homedock.core import ControlService, Scene, Target
from homedock.devices import Capability, Device, DeviceState
from homedock.ui import strings
from homedock.ui.bridge import ServiceBridge
from homedock.ui.icons import tray_icon

log = logging.getLogger(__name__)


class Flyout(Protocol):
    def toggle(self) -> None: ...

    def open(self) -> None: ...


class StayOpenMenu(QMenu):
    """A menu that stays open when a checkable item is toggled, by mouse or keyboard (Enter
    or space); every other item closes it as usual, and so do Esc and a click outside."""

    _TOGGLE_KEYS = frozenset({Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pressed = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pressed = self.rect().contains(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # Like QMenu: only a click that started in the menu chooses the item under it.
        pressed, self._pressed = self._pressed, False
        item = self.actionAt(event.position().toPoint())
        if pressed and item is not None and item is self.activeAction() and _toggles(item):
            item.trigger()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        item = self.activeAction()
        if event.key() in self._TOGGLE_KEYS and item is not None and _toggles(item):
            if not event.isAutoRepeat():  # holding the key down toggles once
                item.trigger()
            return
        super().keyPressEvent(event)


def _toggles(item: QAction) -> bool:
    return item.isEnabled() and item.isCheckable() and item.menu() is None


class TrayController(QObject):
    """Owns the tray icon and its menu. Call :meth:`show` once, :meth:`close` on exit."""

    quit_requested = Signal()

    def __init__(
        self,
        service: ControlService,
        flyout: Flyout,
        *,
        names: Callable[[], Mapping[str, str]],
        scenes: Callable[[], Sequence[Scene]],
        start_with_windows: Callable[[], bool],
        set_start_with_windows: Callable[[bool], None],
        parent: QObject | None = None,
    ) -> None:
        """``names`` gives the display names chosen by the user (device id → name);
        ``set_start_with_windows`` persists the preference and raises ``OSError``."""
        super().__init__(parent)
        self.service = service
        self._flyout = flyout
        self._names = names
        self._scenes = scenes
        self._start_with_windows = start_with_windows
        self._set_start_with_windows = set_start_with_windows
        self._devices = [d for d in service.devices if Capability.POWER in d.capabilities]
        self._closed = False

        self._bridge = ServiceBridge(service, self)
        self._bridge.state_changed.connect(self._on_device_changed)
        self._bridge.online_changed.connect(self._on_device_changed)

        self.menu = StayOpenMenu()
        self.device_actions: dict[str, QAction] = {}
        self._build_menu()
        self.menu.aboutToShow.connect(self._on_menu_about_to_show)

        self.tray = QSystemTrayIcon(tray_icon(), self)
        self.tray.setToolTip(strings.APP_NAME)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

    def show(self) -> None:
        self.tray.show()
        self._refresh()

    def close(self) -> None:
        """Hide the icon and drop the menu; answers still on their way are ignored."""
        if self._closed:
            return
        self._closed = True
        self._bridge.detach()
        self.tray.hide()
        self.menu.deleteLater()

    # --- menu -------------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = self.menu
        menu.addAction(strings.OPEN_PANEL).triggered.connect(self._flyout.open)
        menu.addSeparator()
        for text, power in ((strings.TURN_ALL_ON, True), (strings.TURN_ALL_OFF, False)):
            item = menu.addAction(text)
            item.setEnabled(bool(self._devices))
            item.triggered.connect(partial(self._turn_all, power))
        menu.addSeparator()
        for device in self._devices:
            item = menu.addAction(_escaped(self._name(device)))
            item.setCheckable(True)
            item.triggered.connect(partial(self._toggle, device.id))
            self.device_actions[device.id] = item
        if not self._devices:
            menu.addAction(strings.NO_DEVICES).setEnabled(False)
        menu.addSeparator()
        self._scenes_menu = menu.addMenu(strings.SCENES)
        self._fill_scenes()
        menu.addSeparator()
        self._start_action = menu.addAction(strings.START_WITH_WINDOWS)
        self._start_action.setCheckable(True)
        self._start_action.setChecked(self._start_with_windows())
        self._start_action.triggered.connect(self._on_start_with_windows)
        menu.addSeparator()
        menu.addAction(strings.QUIT).triggered.connect(self.quit_requested.emit)
        self._sync_devices()

    def _fill_scenes(self) -> None:
        self._scenes_menu.clear()
        scenes = self._scenes()
        for scene in scenes:
            item = self._scenes_menu.addAction(_escaped(scene.name))
            item.triggered.connect(partial(self._apply_scene, scene))
        if not scenes:
            self._scenes_menu.addAction(strings.NO_SCENES).setEnabled(False)

    def _on_menu_about_to_show(self) -> None:
        self._fill_scenes()
        self._start_action.setChecked(self._start_with_windows())
        self._sync_devices()
        self._refresh()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._flyout.toggle()

    # --- device state -----------------------------------------------------------------

    def _name(self, device: Device) -> str:
        return self._names().get(device.id, device.name)

    def _sync_devices(self) -> None:
        for device in self._devices:
            self._sync_device(device)

    def _sync_device(self, device: Device) -> None:
        item = self.device_actions[device.id]
        label = strings.device_label(self._name(device), self.service.is_online(device.id))
        item.setText(_escaped(label))
        state = self.service.state(device.id)
        item.setChecked(bool(state and state.power))

    def _on_device_changed(self, device_id: str, _value: object) -> None:
        device = next((d for d in self._devices if d.id == device_id), None)
        if device is not None:
            self._sync_device(device)

    # --- commands ---------------------------------------------------------------------

    def _targets(self) -> list[Target]:
        """One automatic group per device type: together, every device with power."""
        return [Target.all_of(t) for t in dict.fromkeys(d.type for d in self._devices)]

    def _refresh(self) -> None:
        for target in self._targets():
            self._track(self.service.refresh(target))

    def _turn_all(self, power: bool) -> None:
        for target in self._targets():
            self._track(self.service.send(target, DeviceState(power=power)))

    def _toggle(self, device_id: str) -> None:
        # Qt has already flipped the check mark: it holds the requested power state.
        power = self.device_actions[device_id].isChecked()
        self._track(self.service.send(Target.device(device_id), DeviceState(power=power)))

    def _apply_scene(self, scene: Scene) -> None:
        self._track(self.service.apply_scene(scene))

    def _track(self, future: Future[Any]) -> None:
        """Show the real state once the command ends (a failure leaves no state event)."""
        self._bridge.when_done(future, lambda _done: self._sync_devices())

    # --- settings ---------------------------------------------------------------------

    def _on_start_with_windows(self, checked: bool) -> None:
        try:
            self._set_start_with_windows(checked)
        except OSError as error:
            log.error("cannot save the start-with-Windows setting: %s", type(error).__name__)
            self._start_action.setChecked(not checked)


def _escaped(text: str) -> str:
    """Menu text shown literally: a single ``&`` would mark a keyboard shortcut."""
    return text.replace("&", "&&")
