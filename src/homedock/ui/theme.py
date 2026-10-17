"""Colours, sizes and fonts of the flyout, measured on the mockups in ``docs/ui`` (dark).

Widgets read them from here only. Following the Windows theme and accent colour comes
with issue #13.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

# Colours
WINDOW = QColor("#202020")
WINDOW_BORDER = QColor("#3A3A3A")
SURFACE = QColor("#2B2B2B")  # selector button, target list, cards
SURFACE_BORDER = QColor("#3A3A3A")
HOVER = QColor("#323232")
SELECTED = QColor("#383838")
TEXT = QColor("#F3F3F3")
TEXT_SECONDARY = QColor("#B3B3B3")
ACCENT = QColor("#F2B544")
ON_ACCENT = QColor("#1A1A1A")  # icons and text drawn over the accent colour
DEVICE_ON = QColor("#FF9F1C")  # dot of a device that is on
DEVICE_OFF = QColor("#6B6B6B")  # ring of a device that is off or offline
MARKER_BORDER = QColor("#FFFFFF")  # ring of the hue / temperature marker
MARKER_SHADOW = QColor(0, 0, 0, 110)  # keeps the marker visible on the light whites
# The temperature arc, warm → neutral → cold (evenly spaced); also the tint of its preview
TEMPERATURE_COLORS = (QColor("#FFA957"), QColor("#FFF1E0"), QColor("#C9DAFF"))

# Sizes, in device-independent pixels (the mockups are drawn at 2x)
WIDTH = 360
MARGIN = 12  # gap between the flyout and the screen edge / taskbar
PADDING = 21
SPACING = 12
WINDOW_RADIUS = 8
CONTROL_RADIUS = 6
LIST_RADIUS = 8
ROW_RADIUS = 4
HEADER_HEIGHT = 44  # target button and power button
ROW_HEIGHT = 44
ROW_GAP = 2
ROW_INSET = 7  # gap between the list border and a row's highlight
ROW_PADDING = 10  # gap between a row's highlight and its text
SELECTION_BAR = (4, 16)  # width, height
DOT = 10
ICON = 16
LIST_MAX_HEIGHT = 520  # beyond this the target list scrolls
DIAL_SIZE = 220  # outer diameter of the hue ring and the temperature arc
DIAL_BAND = 24  # width of the coloured band
DIAL_MARKER = 22
DIAL_MARKER_BORDER = 3
DIAL_PREVIEW = 56  # the colour preview in the middle
DIAL_PREVIEW_OFFSET = 13  # preview centre above the dial centre
DIAL_LABEL_OFFSET = 34  # hex code / label centre below the dial centre

# Fonts (pixel sizes)
FAMILIES = ["Segoe UI Variable Text", "Segoe UI"]
TITLE = 16
BODY = 14
CAPTION = 13


def font(size: int = BODY, *, bold: bool = False) -> QFont:
    result = QFont()
    result.setFamilies(FAMILIES)
    result.setPixelSize(size)
    if bold:
        result.setWeight(QFont.Weight.DemiBold)
    return result
