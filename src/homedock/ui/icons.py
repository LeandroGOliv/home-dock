"""Icons painted with QPainter, so the app ships no image files."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

SIZES = (16, 20, 24, 32, 40, 48, 64)
GLASS = QColor("#F5B33D")
GLASS_OUTLINE = QColor("#8A5A00")
BASE = QColor("#B4B4B4")
BASE_OUTLINE = QColor("#4A4A4A")


def tray_icon() -> QIcon:
    """A light bulb, readable on light and dark taskbars."""
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(_bulb(size))
    return icon


def _bulb(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 64, size / 64)  # drawn on a 64x64 grid

    glass = QPainterPath()
    glass.addEllipse(QRectF(13, 4, 38, 38))
    neck = QPainterPath()
    neck.addPolygon(QPolygonF([QPointF(21, 34), QPointF(43, 34), QPointF(40, 47), QPointF(24, 47)]))
    painter.setPen(QPen(GLASS_OUTLINE, 2.5))
    painter.setBrush(GLASS)
    painter.drawPath(glass.united(neck).simplified())

    painter.setPen(QPen(BASE_OUTLINE, 2))
    painter.setBrush(BASE)
    painter.drawRoundedRect(QRectF(23, 49, 18, 5), 2, 2)
    painter.drawRoundedRect(QRectF(26, 55, 12, 5), 2, 2)
    painter.end()
    return pixmap
