"""Icons painted with QPainter, so the app ships no image files (``HomeDock.exe`` gets its
icon from :func:`bulb_pixmap` too, at build time)."""

from __future__ import annotations

import math

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
        icon.addPixmap(bulb_pixmap(size))
    return icon


def bulb_pixmap(size: int) -> QPixmap:
    """The tray bulb, ``size`` pixels square."""
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


# --- glyphs painted inside widgets ------------------------------------------------------------


def _stroke(painter: QPainter, color: QColor, width: float = 1.5) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def paint_power(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """The power symbol: a ring open at the top crossed by a vertical bar."""
    painter.save()
    _stroke(painter, color, 2)
    ring = rect.adjusted(1.5, 2.5, -1.5, -0.5)
    painter.drawArc(ring, 130 * 16, 280 * 16)  # Qt angles: 1/16°, counter-clockwise from 3h
    centre = rect.center().x()
    painter.drawLine(QPointF(centre, rect.top() + 0.5), QPointF(centre, rect.center().y()))
    painter.restore()


def paint_chevron(painter: QPainter, rect: QRectF, color: QColor, direction: Qt.Edge) -> None:
    """A chevron pointing to ``direction`` (top, bottom, left or right)."""
    painter.save()
    _stroke(painter, color)
    c = rect.center()
    w, h = rect.width() * 0.3, rect.height() * 0.17  # half the span, half the depth
    offsets = {
        Qt.Edge.TopEdge: ((-w, h), (0, -h), (w, h)),
        Qt.Edge.BottomEdge: ((-w, -h), (0, h), (w, -h)),
        Qt.Edge.LeftEdge: ((h, -w), (-h, 0), (h, w)),
        Qt.Edge.RightEdge: ((-h, -w), (h, 0), (-h, w)),
    }[direction]
    points = [QPointF(c.x() + dx, c.y() + dy) for dx, dy in offsets]
    painter.drawPolyline(QPolygonF(points))
    painter.restore()


def paint_gear(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """An outlined cog with eight teeth."""
    painter.save()
    _stroke(painter, color)
    c = rect.center()
    outer = min(rect.width(), rect.height()) / 2 - 0.75
    inner = outer * 0.74
    outline = QPolygonF()
    for tooth in range(8):
        middle = tooth * 45
        for offset, radius in ((-15, inner), (-9, outer), (9, outer), (15, inner)):
            angle = math.radians(middle + offset)
            outline.append(
                QPointF(c.x() + radius * math.cos(angle), c.y() + radius * math.sin(angle))
            )
    painter.drawPolygon(outline)
    painter.drawEllipse(c, outer * 0.32, outer * 0.32)
    painter.restore()


def paint_check(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """A check mark."""
    painter.save()
    _stroke(painter, color)
    w, h = rect.width(), rect.height()
    points = [(0.2, 0.52), (0.42, 0.72), (0.8, 0.3)]
    painter.drawPolyline(
        QPolygonF([QPointF(rect.x() + x * w, rect.y() + y * h) for x, y in points])
    )
    painter.restore()


def paint_close(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """A cross (close / cancel)."""
    painter.save()
    _stroke(painter, color)
    box = rect.adjusted(
        rect.width() * 0.25, rect.height() * 0.25, -rect.width() * 0.25, -rect.height() * 0.25
    )
    painter.drawLine(box.topLeft(), box.bottomRight())
    painter.drawLine(box.topRight(), box.bottomLeft())
    painter.restore()


def paint_pencil(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """A pencil pointing down-left, over a short line (rename)."""
    painter.save()
    _stroke(painter, color)
    w, h = rect.width(), rect.height()
    body = [(0.16, 0.84), (0.22, 0.62), (0.64, 0.2), (0.8, 0.36), (0.38, 0.78), (0.16, 0.84)]
    painter.drawPolyline(QPolygonF([QPointF(rect.x() + x * w, rect.y() + y * h) for x, y in body]))
    painter.drawLine(
        QPointF(rect.x() + 0.52 * w, rect.y() + 0.86 * h),
        QPointF(rect.x() + 0.86 * w, rect.y() + 0.86 * h),
    )
    painter.restore()


def paint_refresh(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """A circular arrow going clockwise, its head at the top (search again)."""
    painter.save()
    _stroke(painter, color)
    ring = rect.adjusted(1.5, 1.5, -1.5, -1.5)
    painter.drawArc(ring, 80 * 16, 300 * 16)  # Qt angles: 1/16°, counter-clockwise from 3h
    radius = ring.width() / 2
    angle = math.radians(80)
    tip = QPointF(
        ring.center().x() + radius * math.cos(angle), ring.center().y() - radius * math.sin(angle)
    )
    wing = rect.width() * 0.22
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(tip.x() - wing, tip.y() - wing),
                tip,
                QPointF(tip.x() - wing, tip.y() + wing),
            ]
        )
    )
    painter.restore()
