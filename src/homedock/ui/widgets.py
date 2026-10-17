"""Small painting helpers shared by the flyout widgets."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from homedock.ui import theme


class PaintedButton(QAbstractButton):
    """A button drawn in ``paintEvent`` that repaints when the mouse enters or leaves it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hovered(self) -> bool:
        return self.isEnabled() and self.underMouse()

    def painter(self) -> QPainter:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        return painter

    def paint_hover(self, painter: QPainter) -> None:
        """The rounded highlight of a hovered row or icon button."""
        if self.hovered():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.HOVER)
            painter.drawRoundedRect(QRectF(self.rect()), theme.ROW_RADIUS, theme.ROW_RADIUS)


def draw_text(
    painter: QPainter,
    rect: QRectF,
    text: str,
    font: QFont,
    color: QColor = theme.TEXT,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
) -> None:
    """``text`` on one line, vertically centred in ``rect``, elided when it does not fit."""
    if rect.width() <= 0 or not text:
        return
    painter.setFont(font)
    painter.setPen(color)
    elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()))
    painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, elided)


def label(text: str, font: QFont, color: QColor) -> QLabel:
    result = QLabel(text)
    result.setFont(font)
    palette = result.palette()
    palette.setColor(result.foregroundRole(), color)
    result.setPalette(palette)
    return result
