"""Control panel of the RGB bulb: Branco | Cor, the temperature arc or the hue ring, and the
brightness and saturation sliders.

Each control sends only its own capability; the driver turns it into the bulb's commands
(e.g. the brightness of white light or of the colour, depending on the bulb's mode). Every
drag step is sent at once: the control service keeps only the latest pending value of a
device and spaces its writes, so a drag never floods the bulbs. The panel shows the state of
the first online member of its target and follows it live.
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from shiboken6 import isValid

from homedock.core import ControlService, Target
from homedock.devices import Capability, Color, DeviceState, WorkMode
from homedock.ui import strings, theme
from homedock.ui.controls import SegmentedControl, SliderRow
from homedock.ui.dials import HueRing, TemperatureArc

if TYPE_CHECKING:
    from homedock.ui.panels import PanelContext

MIN_BRIGHTNESS = 1  # a bulb at 0 % would look off while being on


def shown_state(service: ControlService, target: Target) -> DeviceState | None:
    """The state the panel shows: the first online member's (a group may disagree), else the
    first known one, else ``None`` before any member answered."""
    known = [
        (service.is_online(d.id), state)
        for d in service.members(target)
        if (state := service.state(d.id)) is not None
    ]
    online = [state for is_online, state in known if is_online]
    if online:
        return online[0]
    return known[0][1] if known else None


class RgbBulbPanel(QWidget):
    def __init__(self, context: PanelContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = context.service
        self._bridge = context.bridge
        self._target = context.target
        self._pending = 0  # commands of this panel still running

        self.modes = SegmentedControl(
            [(WorkMode.WHITE, strings.WHITE_MODE), (WorkMode.COLOR, strings.COLOR_MODE)]
        )
        self.arc = TemperatureArc()
        self.arc.set_value(50)
        self.ring = HueRing()
        self._dials = QStackedWidget()
        self._dials.addWidget(self.arc)
        self._dials.addWidget(self.ring)
        self._dials.setFixedSize(theme.DIAL_SIZE, theme.DIAL_SIZE)
        self.brightness = SliderRow(strings.BRIGHTNESS, MIN_BRIGHTNESS, 100)
        self.brightness.set_value(100)
        self.saturation = SliderRow(strings.SATURATION, 0, 100)
        self.saturation.set_value(self.ring.saturation())
        # Hidden in white mode but keeping its room: the flyout does not jump between modes.
        policy = self.saturation.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.saturation.setSizePolicy(policy)

        capabilities = self.service.capabilities(self._target)
        self.modes.setEnabled(Capability.WORK_MODE in capabilities)
        self.arc.setEnabled(Capability.COLOR_TEMPERATURE in capabilities)
        self.ring.setEnabled(Capability.COLOR_HSV in capabilities)
        self.saturation.setEnabled(Capability.COLOR_HSV in capabilities)
        self.brightness.setEnabled(Capability.BRIGHTNESS in capabilities)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACING // 2, 0, 0)
        layout.setSpacing(theme.PANEL_GAP)
        layout.addWidget(self.modes)
        layout.addWidget(self._dials, 0, Qt.AlignmentFlag.AlignHCenter)
        sliders = QVBoxLayout()
        sliders.setSpacing(theme.SPACING)
        sliders.addWidget(self.brightness)
        sliders.addWidget(self.saturation)
        layout.addLayout(sliders)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.modes.chosen.connect(self._choose_mode)
        self.arc.moved.connect(lambda value: self._send(DeviceState(color_temperature=value)))
        self.ring.moved.connect(lambda hue: self._send_color(hue, self.saturation.value()))
        self.saturation.slider.moved.connect(self._change_saturation)
        self.brightness.slider.moved.connect(
            lambda value: self._send(DeviceState(brightness=value))
        )
        # A command may end while its control is still held, which ignores the state shown:
        # show it again on release (e.g. a failed write reverts the control then).
        for control in (self.arc, self.ring, self.brightness.slider, self.saturation.slider):
            control.released.connect(self._sync)
        self._bridge.state_changed.connect(self._sync)
        self._bridge.online_changed.connect(self._sync)

        self._show_mode(WorkMode.WHITE)
        self._sync()

    # --- user actions -------------------------------------------------------------------------

    def _choose_mode(self, mode: WorkMode) -> None:
        self._show_mode(mode)
        self._send(DeviceState(work_mode=mode))

    def _change_saturation(self, saturation: int) -> None:
        self.ring.set_saturation(saturation)
        self._send_color(self.ring.value(), saturation)

    def _send_color(self, hue: int, saturation: int) -> None:
        self._send(DeviceState(color_hsv=Color(hue, saturation)))

    def _send(self, changes: DeviceState) -> None:
        """Command the target; until every command of the panel ends, the controls keep what
        the user set (answers to earlier drag steps would move them back)."""
        self._pending += 1
        future = self.service.send(self._target, changes)
        self._bridge.when_done(future, self._on_sent)

    def _on_sent(self, _future: Future[Any]) -> None:
        if not isValid(self):  # the panel was replaced while the command ran
            return
        self._pending -= 1
        self._sync()

    # --- state --------------------------------------------------------------------------------

    def _sync(self, *_args: object) -> None:
        """Show the target's cached state (a failed command thus reverts its control)."""
        if self._pending:
            return
        state = shown_state(self.service, self._target)
        if state is None:
            return
        # A mode the panel does not know (e.g. a scene set in the Tuya app) selects no tab,
        # so either tab switches the bulb to it.
        self.modes.set_current(state.work_mode)
        if state.work_mode is not None:
            self._show_mode(state.work_mode)
        if state.color_temperature is not None:
            self.arc.set_value(state.color_temperature)
        if state.color_hsv is not None:
            self.ring.set_color(state.color_hsv.hue, state.color_hsv.saturation)
            self.saturation.set_value(state.color_hsv.saturation)
        if state.brightness is not None:
            self.brightness.set_value(state.brightness)

    def _show_mode(self, mode: WorkMode) -> None:
        color = mode is WorkMode.COLOR
        self._dials.setCurrentWidget(self.ring if color else self.arc)
        self.saturation.setVisible(color)
