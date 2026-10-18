"""Helpers for UI tests: drive the control service through a manual executor, find the point
to click on a slider."""

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from executors import ManualExecutor
from homedock.ui import theme


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
