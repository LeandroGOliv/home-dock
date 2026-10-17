"""Demo window for the hue ring and the temperature arc (manual validation of issue #9).

Shows both dials on the flyout background, a saturation slider for the ring and the
signals they emit. Talks to no device.

Usage::

    uv run python scripts/dials_demo.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from homedock.ui import theme
from homedock.ui.dials import Dial, HueRing, TemperatureArc
from homedock.ui.widgets import label


class DemoWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HomeDock - dials demo")
        palette = self.palette()
        palette.setColor(self.backgroundRole(), theme.WINDOW)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.ring = HueRing()
        self.ring.set_color(28, 85)
        self.arc = TemperatureArc()
        self.arc.set_value(50)
        self.saturation = QSlider(Qt.Orientation.Horizontal)
        self.saturation.setRange(0, 100)
        self.saturation.setValue(self.ring.saturation())
        self.saturation.valueChanged.connect(self.ring.set_saturation)
        self.log = label("", theme.font(theme.CAPTION), theme.TEXT_SECONDARY)

        dials = QHBoxLayout()
        dials.setSpacing(theme.PADDING * 2)
        dials.addWidget(self.ring)
        dials.addWidget(self.arc)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*[theme.PADDING] * 4)
        layout.setSpacing(theme.SPACING)
        layout.addLayout(dials)
        layout.addWidget(label("Saturation", theme.font(), theme.TEXT))
        layout.addWidget(self.saturation)
        layout.addWidget(self.log)

        self._watch(self.ring, "hue")
        self._watch(self.arc, "temperature")

    def _watch(self, dial: Dial, name: str) -> None:
        dial.moved.connect(lambda value: self._show(f"{name} moved: {value}"))
        dial.released.connect(lambda value: self._show(f"{name} released: {value}"))

    def _show(self, text: str) -> None:
        self.log.setText(text)
        print(text)


def main() -> int:
    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
