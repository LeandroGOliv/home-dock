"""Flyout placement: the tray corner of the screen, following the taskbar edge."""

import pytest
from PySide6.QtCore import QPoint, QRect, QSize

from homedock.ui.placement import Edge, flyout_position, taskbar_edge

SCREEN = QRect(0, 0, 1920, 1080)
TASKBAR = 48
AVAILABLE = {
    Edge.BOTTOM: QRect(0, 0, 1920, 1080 - TASKBAR),
    Edge.TOP: QRect(0, TASKBAR, 1920, 1080 - TASKBAR),
    Edge.LEFT: QRect(TASKBAR, 0, 1920 - TASKBAR, 1080),
    Edge.RIGHT: QRect(0, 0, 1920 - TASKBAR, 1080),
}
SIZE = QSize(360, 500)
MARGIN = 12


@pytest.mark.parametrize("edge", list(Edge))
def test_the_taskbar_edge_is_the_side_the_available_area_gives_up(edge):
    assert taskbar_edge(SCREEN, AVAILABLE[edge]) == edge


def test_an_auto_hidden_taskbar_counts_as_bottom():
    assert taskbar_edge(SCREEN, SCREEN) == Edge.BOTTOM


def test_a_secondary_screen_is_measured_on_its_own_coordinates():
    screen = QRect(-1280, 200, 1280, 1024)
    available = QRect(-1280, 200, 1280, 1024 - 40)

    assert taskbar_edge(screen, available) == Edge.BOTTOM


@pytest.mark.parametrize(
    ("edge", "expected"),
    [
        (Edge.BOTTOM, QPoint(1920 - MARGIN - 360, 1080 - TASKBAR - MARGIN - 500)),
        (Edge.TOP, QPoint(1920 - MARGIN - 360, TASKBAR + MARGIN)),
        (Edge.LEFT, QPoint(TASKBAR + MARGIN, 1080 - MARGIN - 500)),
        (Edge.RIGHT, QPoint(1920 - TASKBAR - MARGIN - 360, 1080 - MARGIN - 500)),
    ],
)
def test_the_flyout_goes_to_the_tray_corner_next_to_the_taskbar(edge, expected):
    position = flyout_position(SCREEN, AVAILABLE[edge], SIZE, MARGIN)

    assert position == expected
    assert AVAILABLE[edge].contains(QRect(position, SIZE))


def test_a_flyout_taller_than_the_screen_keeps_its_top_visible():
    available = AVAILABLE[Edge.BOTTOM]

    position = flyout_position(SCREEN, available, QSize(360, 2000), MARGIN)

    assert position.y() == available.top()
