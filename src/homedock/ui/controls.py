"""Generic controls of the panels, in the Windows 11 style: a slider and a segmented control.

Like the dials, they emit what the user does and nothing for values set by code, so a
panel can show the device state without echoing it back as a command.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QFocusEvent,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from homedock.ui import strings, theme
from homedock.ui.widgets import PaintedButton, draw_text, label

PAGE_STEP = 10  # Page Up / Page Down


class Slider(QWidget):
    """A horizontal slider: a press anywhere on it jumps to that value and starts a drag.

    ``moved(int)`` reports every new value while the button is held (or a key changes it),
    ``released(int)`` the final one when the value changed. Hiding or disabling it mid-drag
    ends the drag the same way.
    """

    moved = Signal(int)
    released = Signal(int)

    def __init__(self, minimum: int, maximum: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(theme.SLIDER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._minimum = minimum
        self._maximum = maximum
        self._value = minimum
        self._dragging = False
        self._changed = False  # the value changed during the current drag
        self._focus_shown = False  # reached with the keyboard: draw the focus ring

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        """Show ``value`` without emitting; ignored while the user drags the thumb."""
        if not self._dragging:
            self._show(value)

    def sizeHint(self) -> QSize:
        return QSize(200, theme.SLIDER_HEIGHT)

    # --- geometry -----------------------------------------------------------------------------

    def _track(self) -> tuple[float, float]:
        """Left end and length of the line the thumb's centre runs along."""
        left = theme.SLIDER_THUMB / 2
        return left, max(self.width() - theme.SLIDER_THUMB, 1)

    def _value_at(self, x: float) -> int:
        left, length = self._track()
        span = self._maximum - self._minimum
        return self._clamped(self._minimum + round((x - left) / length * span))

    def _thumb_x(self) -> float:
        left, length = self._track()
        span = max(self._maximum - self._minimum, 1)
        return left + length * (self._value - self._minimum) / span

    def _clamped(self, value: int) -> int:
        return min(max(value, self._minimum), self._maximum)

    # --- input --------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._dragging:
            event.ignore()
            return
        self._dragging = True
        self._changed = False
        self._drag_to(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._drag_to(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            event.ignore()
            return
        self._drag_to(event.position().x())
        self._end_drag()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        steps = {
            Qt.Key.Key_Right: self._value + 1,
            Qt.Key.Key_Up: self._value + 1,
            Qt.Key.Key_Left: self._value - 1,
            Qt.Key.Key_Down: self._value - 1,
            Qt.Key.Key_PageUp: self._value + PAGE_STEP,
            Qt.Key.Key_PageDown: self._value - PAGE_STEP,
            Qt.Key.Key_Home: self._minimum,
            Qt.Key.Key_End: self._maximum,
        }
        key = Qt.Key(event.key())
        if key not in steps or self._dragging:
            super().keyPressEvent(event)
            return
        value = self._clamped(steps[key])
        if value != self._value:
            self._show(value)
            self.moved.emit(value)
            self.released.emit(value)

    def hideEvent(self, event: QHideEvent) -> None:
        self._end_drag()  # e.g. the flyout closed under the pointer: no release will come
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._end_drag()
        super().changeEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        keyboard = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        self._focus_shown = event.reason() in keyboard  # not for a click, like Windows
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._focus_shown = False
        self.update()
        super().focusOutEvent(event)

    def focus_shown(self) -> bool:
        return self._focus_shown

    def _drag_to(self, x: float) -> None:
        value = self._value_at(x)
        if value == self._value:
            return
        self._changed = True
        self._show(value)
        self.moved.emit(value)

    def _end_drag(self) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if self._changed:
            self.released.emit(self._value)

    def _show(self, value: int) -> None:
        self._value = self._clamped(value)
        self.update()

    # --- painting -----------------------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(theme.DISABLED_OPACITY)
        if self._focus_shown:
            painter.setPen(QPen(theme.FOCUS, theme.FOCUS_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = theme.FOCUS_WIDTH / 2
            ring = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
            painter.drawRoundedRect(ring, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)
        middle = self.height() / 2
        left, length = self._track()
        thumb = self._thumb_x()
        radius = theme.SLIDER_TRACK / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.SLIDER_RAIL)
        rail = QRectF(left, middle - radius, length, theme.SLIDER_TRACK)
        painter.drawRoundedRect(rail, radius, radius)
        painter.setBrush(theme.ACCENT)
        filled = QRectF(left, middle - radius, thumb - left, theme.SLIDER_TRACK)
        painter.drawRoundedRect(filled, radius, radius)

        centre = QPointF(thumb, middle)
        outer = theme.SLIDER_THUMB / 2 - 0.5
        painter.setPen(QPen(theme.SLIDER_THUMB_BORDER, 1))
        painter.setBrush(theme.SLIDER_THUMB_FILL)
        painter.drawEllipse(centre, outer, outer)
        dot = theme.SLIDER_THUMB_DOT / 2 + (1 if self.isEnabled() and self.underMouse() else 0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.ACCENT)
        painter.drawEllipse(centre, dot, dot)
        painter.end()


class SliderRow(QWidget):
    """A slider with its title on the left and its value in percent on the right."""

    def __init__(
        self, title: str, minimum: int, maximum: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.title = label(title, theme.font(), theme.TEXT)
        self.amount = label("", theme.font(), theme.TEXT_SECONDARY)
        self.slider = Slider(minimum, maximum)
        self.slider.setAccessibleName(title)
        self.slider.moved.connect(self._show_amount)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.amount)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING // 2)
        layout.addLayout(header)
        layout.addWidget(self.slider)
        self._show_amount(self.slider.value())

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.set_value(value)
        self._show_amount(self.slider.value())

    def _show_amount(self, value: int) -> None:
        text = strings.percent(value)
        self.amount.setText(text)
        self.slider.setAccessibleDescription(text)


class Segment(PaintedButton):
    """One option of a :class:`SegmentedControl`; the selected one is filled with the accent."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        rect = QRectF(self.rect())
        color = theme.TEXT
        if self.isChecked():
            fill = theme.ACCENT.lighter(108) if self.hovered() else theme.ACCENT
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)
            color = theme.ON_ACCENT
        else:
            self.paint_hover(painter)
        if not self.isEnabled():
            color = theme.DEVICE_OFF
        draw_text(painter, rect, self.text(), theme.font(), color, Qt.AlignmentFlag.AlignHCenter)
        painter.end()


class SegmentedControl(QWidget):
    """Mutually exclusive options side by side (e.g. Branco | Cor).

    ``chosen(key)`` fires when the user picks another option; ``set_current()`` does not.
    ``set_current(None)`` selects nothing (e.g. an unknown mode): any option is then a pick.
    """

    chosen = Signal(object)

    def __init__(
        self, options: Sequence[tuple[Hashable, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(theme.TABS_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._keys = [key for key, _ in options]
        self.buttons = [Segment(text) for _, text in options]
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QHBoxLayout(self)
        inset = theme.TABS_INSET
        layout.setContentsMargins(inset, inset, inset, inset)
        layout.setSpacing(inset)
        for index, button in enumerate(self.buttons):
            self._group.addButton(button, index)
            layout.addWidget(button)
        self.buttons[0].setChecked(True)
        self._group.idClicked.connect(self._clicked)
        self._current: int | None = 0

    def current(self) -> Hashable | None:
        return self._keys[self._current] if self._current is not None else None

    def set_current(self, key: Hashable | None) -> None:
        if key is None:
            self._current = None
            self._group.setExclusive(False)  # an exclusive group keeps one option checked
            for button in self.buttons:
                button.setChecked(False)
            self._group.setExclusive(True)
            return
        self._current = self._keys.index(key)
        self.buttons[self._current].setChecked(True)

    def _clicked(self, index: int) -> None:
        if index != self._current:
            self._current = index
            self.chosen.emit(self._keys[index])

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(theme.SURFACE_BORDER, 1))
        painter.setBrush(theme.SURFACE)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.CONTROL_RADIUS + theme.TABS_INSET / 2
        painter.drawRoundedRect(frame, radius, radius)
        painter.end()
