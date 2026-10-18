"""Small painting helpers shared by the flyout widgets."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

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
            painter.setBrush(theme.colors.hover)
            painter.drawRoundedRect(QRectF(self.rect()), theme.ROW_RADIUS, theme.ROW_RADIUS)


def draw_text(
    painter: QPainter,
    rect: QRectF,
    text: str,
    font: QFont,
    color: QColor | None = None,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
) -> None:
    """``text`` on one line, vertically centred in ``rect``, elided when it does not fit;
    in the theme's text colour unless ``color`` is given."""
    if rect.width() <= 0 or not text:
        return
    painter.setFont(font)
    painter.setPen(theme.colors.text if color is None else color)
    elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()))
    painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, elided)


@runtime_checkable
class Themed(Protocol):
    """A widget that sets colours outside ``paintEvent`` (a palette, a style sheet) and
    sets them again from :data:`theme.colors` when the theme changes."""

    def apply_theme(self) -> None: ...


def restyle_all() -> None:
    """Show the current :data:`theme.colors` on every widget of the app."""
    for widget in QApplication.allWidgets():
        if isinstance(widget, Themed):
            widget.apply_theme()
        widget.update()


class Label(QLabel):
    """A label in the theme's text colour, or its secondary one."""

    def __init__(self, text: str, font: QFont, *, secondary: bool = False) -> None:
        super().__init__(text)
        self._secondary = secondary
        self.setFont(font)
        self.apply_theme()

    def apply_theme(self) -> None:
        palette = self.palette()
        color = theme.colors.text_secondary if self._secondary else theme.colors.text
        palette.setColor(self.foregroundRole(), color)
        self.setPalette(palette)


def label(text: str, font: QFont, *, secondary: bool = False) -> Label:
    return Label(text, font, secondary=secondary)
