"""The flyout: a frameless window next to the tray, in the Windows 11 style.

One window holding a stack of pages. The main page has the target selector, the power
button for the selected target and the control panel of the target's device type (from the
panel registry). The flyout reads the real state of the devices each time it opens and
closes when it loses focus or on Esc.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from homedock.core import ControlService, Target
from homedock.devices import DeviceState
from homedock.ui import strings, theme
from homedock.ui.bridge import ServiceBridge
from homedock.ui.icons import paint_chevron
from homedock.ui.panels import PanelContext, PanelRegistry, default_panels
from homedock.ui.placement import flyout_position
from homedock.ui.selector import PowerButton, TargetButton, TargetList
from homedock.ui.target_model import build_model
from homedock.ui.widgets import PaintedButton, label

log = logging.getLogger(__name__)

# A click on the tray icon first takes the focus away from the flyout (hiding it), then
# toggles it: within this many seconds of such a hide, the toggle must not reopen it.
REOPEN_GUARD = 0.3


class PageStack(QWidget):
    """Pages on top of each other; only the top one is shown. The base page stays."""

    changed = Signal()

    def __init__(self, base: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._pages = [base]
        self._layout.addWidget(base)

    def current(self) -> QWidget:
        return self._pages[-1]

    def depth(self) -> int:
        return len(self._pages)

    def push(self, page: QWidget) -> None:
        self.current().hide()
        self._pages.append(page)
        self._layout.addWidget(page)
        page.show()
        self.changed.emit()

    def pop(self) -> None:
        if len(self._pages) == 1:
            return
        page = self._pages.pop()
        self._layout.removeWidget(page)
        page.hide()
        page.deleteLater()
        self.current().show()
        self.changed.emit()

    def reset(self) -> None:
        """Back to the base page."""
        while len(self._pages) > 1:
            self.pop()


class MainPage(QWidget):
    """Target selector, power button and the control panel of the selected target."""

    manage_requested = Signal()
    layout_changed = Signal()

    def __init__(
        self,
        service: ControlService,
        bridge: ServiceBridge,
        panels: PanelRegistry,
        *,
        names: Callable[[], Mapping[str, str]],
        last_target: Callable[[], Target | None],
        set_last_target: Callable[[Target], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._bridge = bridge
        self._panels = panels
        self._names = names
        self._last_target = last_target
        self._set_last_target = set_last_target
        self._target: Target | None = None
        self._pending_power = 0  # power commands still running
        self.panel: QWidget | None = None

        self.target_button = TargetButton()
        self.power_button = PowerButton()
        self.target_list = TargetList()
        self.target_list.hide()
        self._content = QWidget()  # the panel; hidden while the target list is open
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content.hide()

        header = QHBoxLayout()
        header.setSpacing(theme.SPACING)
        header.addWidget(self.target_button)
        header.addWidget(self.power_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.PADDING, theme.PADDING, theme.PADDING, theme.PADDING)
        layout.setSpacing(theme.SPACING - 1)
        layout.addLayout(header)
        layout.addWidget(self.target_list)
        layout.addWidget(self._content)

        self.target_button.toggled.connect(self._show_list)
        self.target_list.chosen.connect(self.select)
        self.target_list.manage_requested.connect(self.manage_requested)
        self.power_button.clicked.connect(self._switch)
        bridge.state_changed.connect(self._sync)
        bridge.online_changed.connect(self._sync)

    @property
    def target(self) -> Target | None:
        return self._target

    def reload(self) -> None:
        """Show the latest names and groups, keep the target if it still exists and read the
        real state of every device (answers update the page as they arrive)."""
        self.target_button.setChecked(False)
        model = build_model(self.service, self._names())
        preferred = self._target if self._target is not None else self._last_target()
        self._set_target(model.choose(preferred))
        self._sync()
        for device_type in dict.fromkeys(d.type for d in self.service.devices):
            self._track(self.service.refresh(Target.all_of(device_type)))

    def select(self, target: Target) -> None:
        """Control ``target`` from now on (remembered for the next start) and re-read it."""
        self.target_button.setChecked(False)
        if target != self._target:
            self._set_target(target)
            try:
                self._set_last_target(target)
            except OSError as error:
                log.error("cannot save the selected target: %s", type(error).__name__)
        self._sync()
        self._track(self.service.refresh(target))

    def _set_target(self, target: Target | None) -> None:
        if target == self._target:
            return
        self._target = target
        if self.panel is not None:
            self._content_layout.removeWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None
        if target is not None:
            self.panel = self._panels.create(PanelContext(self.service, self._bridge, target))
        if self.panel is not None:
            self._content_layout.addWidget(self.panel)
            self.panel.show()  # shown with the content, not on a later event loop pass
        self._show_list(self.target_button.isChecked())

    def _sync(self, *_args: object) -> None:
        """Show the cached state: header, power button and list. While a power command
        runs, the button keeps the requested state (members answer one by one)."""
        model = build_model(self.service, self._names())
        entry = model.find(self._target)
        if entry is None:
            self.target_button.set_target(strings.NO_DEVICES, "")
        else:
            self.target_button.set_target(entry.title, entry.subtitle)
        self.power_button.setEnabled(entry is not None and entry.can_power)
        if not self._pending_power:
            self.power_button.setChecked(entry is not None and entry.on)
        self.target_list.set_model(model, self._target)

    def _show_list(self, shown: bool) -> None:
        self.target_list.setVisible(shown)
        self._content.setVisible(not shown and self.panel is not None)
        self.layout_changed.emit()

    def _switch(self, on: bool) -> None:
        # Qt has already flipped the button: it holds the requested power state.
        if self._target is None:
            return
        self._pending_power += 1
        future = self.service.send(self._target, DeviceState(power=on))
        self._bridge.when_done(future, self._on_switched)

    def _on_switched(self, _future: Future[Any]) -> None:
        self._pending_power -= 1
        self._sync()

    def _track(self, future: Future[Any]) -> None:
        """Show the real state once the read ends (a failure leaves no state event)."""
        self._bridge.when_done(future, self._sync)


class BackButton(PaintedButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setAccessibleName(strings.BACK)
        self.setToolTip(strings.BACK)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        self.paint_hover(painter)
        glyph = QRectF(0, 0, theme.ICON, theme.ICON)
        glyph.moveCenter(QRectF(self.rect()).center())
        paint_chevron(painter, glyph, theme.TEXT, Qt.Edge.LeftEdge)
        painter.end()


class ManagePage(QWidget):
    """ "Grupos e lâmpadas". Only the navigation for now: the content comes with issue #12."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.back_button = BackButton()
        self.back_button.clicked.connect(self.back_requested)
        title = label(strings.MANAGE_TITLE, theme.font(theme.TITLE, bold=True), theme.TEXT)
        message = label(strings.MANAGE_SOON, theme.font(theme.CAPTION), theme.TEXT_SECONDARY)
        message.setWordWrap(True)

        header = QHBoxLayout()
        header.setSpacing(theme.SPACING)
        header.addWidget(self.back_button)
        header.addWidget(title, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.PADDING, theme.PADDING, theme.PADDING, theme.PADDING)
        layout.setSpacing(theme.PADDING)
        layout.addLayout(header)
        layout.addWidget(message)


class Flyout(QWidget):
    """The control window. ``toggle()`` / ``open()`` are what the tray calls; call
    ``shutdown()`` when the app quits."""

    def __init__(
        self,
        service: ControlService,
        *,
        names: Callable[[], Mapping[str, str]],
        last_target: Callable[[], Target | None],
        set_last_target: Callable[[Target], None],
        panels: PanelRegistry | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``set_last_target`` persists the selected target and raises ``OSError``."""
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(strings.APP_NAME)
        self.setFont(theme.font())
        self.setFixedWidth(theme.WIDTH)
        self._clock = clock
        self._auto_hidden_at = -math.inf

        self.bridge = ServiceBridge(service, self)
        self.main = MainPage(
            service,
            self.bridge,
            panels or default_panels(),
            names=names,
            last_target=last_target,
            set_last_target=set_last_target,
        )
        self.pages = PageStack(self.main)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)

        self.main.manage_requested.connect(self._open_manage)
        self.main.layout_changed.connect(self._fit)
        self.pages.changed.connect(self._fit)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        elif self._clock() - self._auto_hidden_at >= REOPEN_GUARD:
            self.open()

    def open(self) -> None:
        """Show the main page with fresh device state, in the tray corner of the screen
        under the cursor."""
        if not self.isVisible():
            self.pages.reset()
            self.main.reload()
        self._fit()
        self.show()
        self.raise_()
        self.activateWindow()

    def shutdown(self) -> None:
        """Hide for good: device answers still on their way are ignored."""
        self.bridge.detach()
        self.hide()

    def _open_manage(self) -> None:
        page = ManagePage()
        page.back_requested.connect(self.pages.pop)
        self.pages.push(page)

    def _fit(self) -> None:
        """Take the height of the current page and stay in the tray corner."""
        layout = self.layout()
        layout.activate()
        if layout.hasHeightForWidth():
            height = layout.totalHeightForWidth(theme.WIDTH)
        else:
            height = layout.totalSizeHint().height()
        self.setFixedHeight(height)
        screen = QGuiApplication.screenAt(QCursor.pos()) if not self.isVisible() else None
        screen = screen or self.screen() or QGuiApplication.primaryScreen()
        self.move(
            flyout_position(
                screen.geometry(), screen.availableGeometry(), self.size(), theme.MARGIN
            )
        )

    # --- Qt events ----------------------------------------------------------------------

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            self._auto_hidden_at = self._clock()
            self.hide()
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(theme.WINDOW_BORDER, 1))
        painter.setBrush(theme.WINDOW)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(frame, theme.WINDOW_RADIUS, theme.WINDOW_RADIUS)
        painter.end()
