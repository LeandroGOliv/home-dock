"""The dials demo window builds and reports what the dials emit."""

from PySide6.QtCore import QPoint, Qt

from dials_demo import DemoWindow
from homedock.ui import theme
from homedock.ui.dial_math import polar


def test_the_demo_reports_the_dial_signals(qtbot):
    window = DemoWindow()
    qtbot.addWidget(window)
    window.show()
    ring = window.ring
    radius = (theme.DIAL_SIZE - theme.DIAL_BAND) / 2
    x, y = polar(ring.width() / 2, ring.height() / 2, radius, 180)

    qtbot.mouseClick(ring, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))

    assert window.log.text() == "hue released: 180"


def test_the_saturation_slider_changes_the_ring_preview(qtbot):
    window = DemoWindow()
    qtbot.addWidget(window)

    window.saturation.setValue(0)

    assert window.ring.hex_code() == "#FFFFFF"
