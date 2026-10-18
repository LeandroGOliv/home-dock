"""Generic controls of the flyout, in the Windows 11 style: a slider, a segmented control, a
text link, an inline name field and a discreet notice.

Like the dials, the slider and the segmented control emit what the user does and nothing
for values set by code, so a panel can show the device state without echoing it back as a
command.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QEnterEvent,
    QFocusEvent,
    QFontMetrics,
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
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from homedock.ui import strings, theme
from homedock.ui.icons import paint_check, paint_close
from homedock.ui.widgets import PaintedButton, draw_text, label

PAGE_STEP = 10  # Page Up / Page Down
NOTICE_DURATION = 6000  # milliseconds a notice stays
MAX_NAME = 40
LINK_PADDING = 6


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
            painter.setPen(QPen(theme.colors.focus, theme.FOCUS_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = theme.FOCUS_WIDTH / 2
            ring = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
            painter.drawRoundedRect(ring, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)
        middle = self.height() / 2
        left, length = self._track()
        thumb = self._thumb_x()
        radius = theme.SLIDER_TRACK / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.colors.slider_rail)
        rail = QRectF(left, middle - radius, length, theme.SLIDER_TRACK)
        painter.drawRoundedRect(rail, radius, radius)
        painter.setBrush(theme.colors.accent)
        filled = QRectF(left, middle - radius, thumb - left, theme.SLIDER_TRACK)
        painter.drawRoundedRect(filled, radius, radius)

        centre = QPointF(thumb, middle)
        outer = theme.SLIDER_THUMB / 2 - 0.5
        painter.setPen(QPen(theme.colors.slider_thumb_border, 1))
        painter.setBrush(theme.colors.slider_thumb_fill)
        painter.drawEllipse(centre, outer, outer)
        dot = theme.SLIDER_THUMB_DOT / 2 + (1 if self.isEnabled() and self.underMouse() else 0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.colors.accent)
        painter.drawEllipse(centre, dot, dot)
        painter.end()


class SliderRow(QWidget):
    """A slider with its title on the left and its value in percent on the right."""

    def __init__(
        self, title: str, minimum: int, maximum: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.title = label(title, theme.font())
        self.amount = label("", theme.font(), secondary=True)
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
        color = theme.colors.text
        if self.isChecked():
            fill = theme.colors.accent.lighter(108) if self.hovered() else theme.colors.accent
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)
            color = theme.colors.on_accent
        else:
            self.paint_hover(painter)
        if not self.isEnabled():
            color = theme.colors.device_off
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
        painter.setPen(QPen(theme.colors.surface_border, 1))
        painter.setBrush(theme.colors.surface)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.CONTROL_RADIUS + theme.TABS_INSET / 2
        painter.drawRoundedRect(frame, radius, radius)
        painter.end()


class LinkButton(PaintedButton):
    """Accent-coloured text that acts like a button (e.g. "+ Salvar atual", "Desfazer")."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(theme.font())
        width = metrics.horizontalAdvance(self.text()) + 2 * LINK_PADDING
        return QSize(width, theme.LINK_HEIGHT)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        self.paint_hover(painter)
        color = theme.colors.accent_text if self.isEnabled() else theme.colors.device_off
        draw_text(
            painter,
            QRectF(self.rect()),
            self.text(),
            theme.font(),
            color,
            Qt.AlignmentFlag.AlignHCenter,
        )
        painter.end()


class IconButton(PaintedButton):
    """A square button with a painted glyph (the name field's ✓ and ✕)."""

    def __init__(
        self,
        glyph: Callable[..., None],
        name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self.setFixedSize(theme.EDITOR_HEIGHT, theme.EDITOR_HEIGHT)
        self.setAccessibleName(name)
        self.setToolTip(name)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        self.paint_hover(painter)
        glyph = QRectF(0, 0, theme.ICON, theme.ICON)
        glyph.moveCenter(QRectF(self.rect()).center())
        colors = theme.colors
        self._glyph(painter, glyph, colors.text if self.isEnabled() else colors.device_off)
        painter.end()


class TextField(QLineEdit):
    """A one-line box for a name, in the theme's colours and without Qt's context menu."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFont(theme.font())
        self.setMaxLength(MAX_NAME)
        # Qt's own menu (Undo, Cut, Copy...) would be in English: no translation is loaded.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.apply_theme()

    def apply_theme(self) -> None:
        colors = theme.colors
        self.setStyleSheet(f"""
QLineEdit {{
    background: {colors.surface.name()}; color: {colors.text.name()};
    border: 1px solid {colors.surface_border.name()}; border-radius: {theme.ROW_RADIUS}px;
    padding: 0 {theme.FIELD_PADDING}px;
    selection-background-color: {colors.accent.name()};
    selection-color: {colors.on_accent.name()};
    placeholder-text-color: {colors.text_secondary.name()};
}}
QLineEdit:focus {{ border-bottom: 2px solid {colors.accent.name()}; }}
""")


class NameField(TextField):
    """A text box where Esc cancels (instead of closing the flyout)."""

    cancelled = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class NameEditor(QWidget):
    """An inline field for a name (a dialog would take the focus and close the flyout):
    Enter or ✓ accepts it, Esc or ✕ cancels (Esc never reaches the flyout, which would
    close). ``placeholder`` also names the field for screen readers."""

    accepted = Signal(str)
    cancelled = Signal()

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = NameField()
        self.field.setFixedHeight(theme.EDITOR_HEIGHT)
        self.field.setPlaceholderText(placeholder)
        self.field.setAccessibleName(placeholder)
        self.save_button = IconButton(paint_check, strings.SAVE)
        self.cancel_button = IconButton(paint_close, strings.CANCEL)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.EDITOR_GAP)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.save_button)
        layout.addWidget(self.cancel_button)

        self.field.returnPressed.connect(self._accept)
        self.field.textChanged.connect(self._sync)
        self.field.cancelled.connect(self.cancelled)
        self.save_button.clicked.connect(self._accept)
        self.cancel_button.clicked.connect(self.cancelled)

    def start(self, text: str) -> None:
        """Edit ``text``, all selected so typing replaces it."""
        self.field.setText(text)
        self.field.selectAll()
        self._sync()
        self.field.setFocus(Qt.FocusReason.OtherFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:  # e.g. on ✓ or ✕
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def _sync(self) -> None:
        self.save_button.setEnabled(bool(self.field.text().strip()))

    def _accept(self) -> None:
        name = self.field.text().strip()
        if name:
            self.accepted.emit(name)


class Notice(QWidget):
    """A discreet line of text with an optional action link. It hides by itself, but not
    under the pointer: the flyout would shrink while the user reaches for the action."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.text = label("", theme.font(theme.CAPTION), secondary=True)
        self.text.setWordWrap(True)
        self.action = LinkButton("")
        self.action.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(NOTICE_DURATION)
        self._callback: Callable[[], object] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.action)
        self.action.clicked.connect(self._act)

    def set_message(self, text: str, action: tuple[str, Callable[[], object]] | None) -> None:
        self.text.setText(text)
        self.action.setVisible(action is not None)
        if action is not None:
            self.action.setText(action[0])
            self.action.updateGeometry()
        self._callback = action[1] if action is not None else None
        self.timer.start()

    def enterEvent(self, event: QEnterEvent) -> None:
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self.isVisible():
            self.timer.start()
        super().leaveEvent(event)

    def _act(self) -> None:
        if self._callback is not None:
            self._callback()
