"""Helpers for UI tests: drive the control service through a manual executor, find the points
to click on the controls."""

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from executors import ManualExecutor
from homedock.ui import theme
from homedock.ui.dial_math import polar


def settle(executor: ManualExecutor) -> None:
    """Run the queued device I/O, then deliver what it queued for the UI thread."""
    executor.run_all()
    QApplication.processEvents()


def slider_point(slider, value: float) -> QPoint:
    """The point of a :class:`~homedock.ui.controls.Slider` where ``value`` lies."""
    left = theme.SLIDER_THUMB / 2
    width = slider.width() - theme.SLIDER_THUMB
    span = slider.maximum() - slider.minimum()
    return QPoint(round(left + width * (value - slider.minimum()) / span), slider.height() // 2)


def dial_point(dial, angle: float) -> QPoint:
    """The point on the band of a dial at the compass ``angle``."""
    radius = (theme.DIAL_SIZE - theme.DIAL_BAND) / 2
    x, y = polar(dial.width() / 2, dial.height() / 2, radius, angle)
    return QPoint(round(x), round(y))
