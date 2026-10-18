"""Hue ring and temperature arc: round controls with a draggable marker.

A press on the band (or on the marker) starts a drag; the marker follows the pointer's
angle around the centre, also off the band. ``moved`` reports every new value while the
button is held and ``released`` the final one; a click is a press and a release. Values set
by code emit nothing. The maths lives in :mod:`homedock.ui.dial_math`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from homedock.ui import strings, theme
from homedock.ui.dial_math import (
    ARC_SPAN,
    ARC_START,
    angle_to_hue,
    blend,
    compass_angle,
    drag_temperature,
    gradient_position,
    hsv_to_hex,
    hue_to_angle,
    in_arc,
    polar,
    temperature_to_angle,
)
from homedock.ui.widgets import draw_text

RADIUS = (theme.DIAL_SIZE - theme.DIAL_BAND) / 2  # the band's centre line
SPLIT = 1e-4  # gradient stops this close make a hard edge


class Dial(QWidget):
    """The common part: geometry, dragging and painting of the marker and the preview."""

    moved = Signal(int)
    released = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(theme.DIAL_SIZE, theme.DIAL_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value = 0
        self._dragging = False
        self._changed = False  # the value changed during the current drag
        self._grab = 0.0  # angle between the pointer and the marker when the drag started

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        """Show ``value`` without emitting; ignored while the user drags the marker."""
        if self._dragging:
            return
        self._value = self._normalised(value)
        self._value_shown()

    # --- what each dial defines ---------------------------------------------------------------

    def _normalised(self, value: int) -> int:
        raise NotImplementedError

    def _angle(self) -> float:
        """Where the marker of the current value is."""
        raise NotImplementedError

    def _value_at(self, angle: float) -> int:
        raise NotImplementedError

    def _accepts(self, angle: float) -> bool:
        """Whether a press on the band at ``angle`` may start a drag."""
        return True

    def _color(self) -> QColor:
        """The colour of the marker and the preview."""
        raise NotImplementedError

    def _caption(self) -> str:
        """The text under the preview."""
        raise NotImplementedError

    def _paint_band(self, painter: QPainter) -> None:
        raise NotImplementedError

    # --- geometry -----------------------------------------------------------------------------

    def _centre(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def _marker_centre(self) -> QPointF:
        centre = self._centre()
        return QPointF(*polar(centre.x(), centre.y(), RADIUS, self._angle()))

    def _pointer_angle(self, position: QPointF) -> float:
        offset = position - self._centre()
        return compass_angle(offset.x(), offset.y())

    def _on_marker(self, position: QPointF) -> bool:
        offset = position - self._marker_centre()
        return math.hypot(offset.x(), offset.y()) <= theme.DIAL_MARKER / 2

    def _on_band(self, position: QPointF) -> bool:
        offset = position - self._centre()
        distance = math.hypot(offset.x(), offset.y())
        return abs(distance - RADIUS) <= theme.DIAL_BAND / 2 and self._accepts(
            self._pointer_angle(position)
        )

    # --- mouse --------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        position = event.position()
        if event.button() != Qt.MouseButton.LeftButton or self._dragging:
            event.ignore()
            return
        if self._on_marker(position):
            # Grabbing the marker does not move it: the drag keeps the grab offset.
            grab = (self._pointer_angle(position) - self._angle() + 180) % 360 - 180
            self._start_drag(grab)
        elif self._on_band(position):
            self._start_drag(0.0)
            self._drag_to(position)
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._drag_to(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            event.ignore()
            return
        self._drag_to(event.position())
        self._end_drag()

    def hideEvent(self, event: QHideEvent) -> None:
        self._end_drag()  # e.g. the flyout closed under the pointer: no release will come
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._end_drag()
        super().changeEvent(event)

    def _end_drag(self) -> None:
        """Finish the drag where it is, as if the button were released there."""
        if not self._dragging:
            return
        self._dragging = False
        if self._changed:
            self.released.emit(self._value)

    def _start_drag(self, grab: float) -> None:
        self._dragging = True
        self._changed = False
        self._grab = grab

    def _drag_to(self, position: QPointF) -> None:
        value = self._value_at((self._pointer_angle(position) - self._grab) % 360)
        if value == self._value:
            return
        self._value = value
        self._changed = True
        self._value_shown()
        self.moved.emit(value)

    def _value_shown(self) -> None:
        self.setAccessibleDescription(self._caption())
        self.update()

    # --- painting -----------------------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(theme.DISABLED_OPACITY)
        self._paint_band(painter)
        self._paint_preview(painter)
        self._paint_marker(painter)
        painter.end()

    def _band_pen(self, gradient: QConicalGradient, cap: Qt.PenCapStyle) -> QPen:
        return QPen(gradient, theme.DIAL_BAND, Qt.PenStyle.SolidLine, cap)

    def _band_rect(self) -> QRectF:
        rect = QRectF(0, 0, 2 * RADIUS, 2 * RADIUS)
        rect.moveCenter(self._centre())
        return rect

    def _paint_marker(self, painter: QPainter) -> None:
        border = theme.DIAL_MARKER_BORDER
        radius = (theme.DIAL_MARKER - border) / 2
        painter.setPen(QPen(theme.MARKER_SHADOW, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(self._marker_centre(), radius + border / 2, radius + border / 2)
        painter.setPen(QPen(theme.MARKER_BORDER, border))
        painter.setBrush(self._color())
        painter.drawEllipse(self._marker_centre(), radius, radius)

    def _paint_preview(self, painter: QPainter) -> None:
        centre = self._centre()
        radius = theme.DIAL_PREVIEW / 2
        painter.setPen(QPen(theme.colors.surface_border, 1))
        painter.setBrush(self._color())
        preview = QPointF(centre.x(), centre.y() - theme.DIAL_PREVIEW_OFFSET)
        painter.drawEllipse(preview, radius, radius)

        width = 2 * (RADIUS - theme.DIAL_BAND / 2)  # the hole of the band
        line = QRectF(0, 0, width, theme.BODY * 2)
        line.moveCenter(QPointF(centre.x(), centre.y() + theme.DIAL_LABEL_OFFSET))
        draw_text(painter, line, self._caption(), theme.font(), align=Qt.AlignmentFlag.AlignHCenter)


class HueRing(Dial):
    """The 360° hue ring, red at the top and clockwise like the colour wheel; the marker
    and the preview show the colour at full brightness, with the hex code under it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(strings.HUE)
        self._saturation = 100
        self._value_shown()

    def saturation(self) -> int:
        return self._saturation

    def set_saturation(self, saturation: int) -> None:
        self._saturation = saturation
        self._value_shown()

    def set_color(self, hue: int, saturation: int) -> None:
        self._saturation = saturation
        self.set_value(hue)

    def hex_code(self) -> str:
        return hsv_to_hex(self._value, self._saturation)

    def _normalised(self, value: int) -> int:
        return value % 360

    def _angle(self) -> float:
        return hue_to_angle(self._value)

    def _value_at(self, angle: float) -> int:
        return angle_to_hue(angle)

    def _color(self) -> QColor:
        return QColor(self.hex_code())

    def _caption(self) -> str:
        return self.hex_code()

    def _paint_band(self, painter: QPainter) -> None:
        gradient = QConicalGradient(self._centre(), 90)
        for hue in range(0, 360, 60):
            gradient.setColorAt(gradient_position(hue), QColor(hsv_to_hex(hue, 100)))
        gradient.setColorAt(1, QColor(hsv_to_hex(0, 100)))
        painter.setPen(self._band_pen(gradient, Qt.PenCapStyle.FlatCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(self._band_rect())


class TemperatureArc(Dial):
    """The colour temperature arc: 270°, open at the bottom, warm on the left and cold on
    the right; the preview shows the tint of the white and its kind (quente / neutro /
    frio). Presses in the opening are ignored; a drag into it stops at the end it came
    from, until the pointer comes back onto that end's half of the arc."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(strings.TEMPERATURE)
        self._held: int | None = None  # the end a drag into the opening is held at
        self._value_shown()

    def tint(self) -> str:
        return blend([c.name() for c in theme.TEMPERATURE_COLORS], self._value / 100)

    def label(self) -> str:
        return strings.temperature_label(self._value)

    def _normalised(self, value: int) -> int:
        return min(max(value, 0), 100)

    def _angle(self) -> float:
        return temperature_to_angle(self._value)

    def _accepts(self, angle: float) -> bool:
        return in_arc(angle)

    def _start_drag(self, grab: float) -> None:
        super()._start_drag(grab)
        self._held = None

    def _value_at(self, angle: float) -> int:
        value, self._held = drag_temperature(angle, self._value, self._held)
        return value

    def _color(self) -> QColor:
        return QColor(self.tint())

    def _caption(self) -> str:
        return self.label()

    def _paint_band(self, painter: QPainter) -> None:
        warm, neutral, cold = theme.TEMPERATURE_COLORS
        gradient = QConicalGradient(self._centre(), 90)
        bottom = gradient_position(180)
        gradient.setColorAt(0, neutral)
        gradient.setColorAt(gradient_position(ARC_START), warm)
        gradient.setColorAt(bottom - SPLIT, warm)  # the round caps reach into the opening
        gradient.setColorAt(bottom + SPLIT, cold)
        gradient.setColorAt(gradient_position(ARC_START + ARC_SPAN), cold)
        gradient.setColorAt(1, neutral)

        path = QPainterPath()
        start = 90 - ARC_START  # Qt angles: counter-clockwise from 3 o'clock
        path.arcMoveTo(self._band_rect(), start)
        path.arcTo(self._band_rect(), start, -ARC_SPAN)
        painter.setPen(self._band_pen(gradient, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
