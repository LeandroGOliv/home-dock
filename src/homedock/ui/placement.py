"""Where the flyout goes: in the screen corner next to the tray, on the taskbar's side."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QPoint, QRect, QSize


class Edge(StrEnum):
    BOTTOM = "bottom"
    TOP = "top"
    LEFT = "left"
    RIGHT = "right"


def taskbar_edge(screen: QRect, available: QRect) -> Edge:
    """The screen edge the taskbar is on: the side the available area gives up.

    An auto-hidden taskbar gives up nothing; Windows then keeps the tray at the bottom.
    """
    gaps = {
        Edge.BOTTOM: screen.bottom() - available.bottom(),
        Edge.TOP: available.top() - screen.top(),
        Edge.LEFT: available.left() - screen.left(),
        Edge.RIGHT: screen.right() - available.right(),
    }
    edge = max(gaps, key=lambda e: gaps[e])  # a tie keeps the first: bottom
    return edge if gaps[edge] > 0 else Edge.BOTTOM


def flyout_position(screen: QRect, available: QRect, size: QSize, margin: int) -> QPoint:
    """Top-left corner of a window of ``size`` in the tray corner of ``available``.

    The tray sits at the right end of a horizontal taskbar and at the bottom of a vertical
    one, so the window goes bottom-right, top-right (taskbar on top) or bottom-left
    (taskbar on the left), ``margin`` away from the edges. It never leaves the available
    area through its top-left corner, even when it is larger than the area.
    """
    edge = taskbar_edge(screen, available)
    if edge == Edge.LEFT:
        x = available.left() + margin
    else:
        x = available.right() + 1 - margin - size.width()
    if edge == Edge.TOP:
        y = available.top() + margin
    else:
        y = available.bottom() + 1 - margin - size.height()
    return QPoint(max(x, available.left()), max(y, available.top()))
