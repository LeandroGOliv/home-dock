"""Colours, sizes and fonts of the flyout, measured on the mockups in ``docs/ui`` (dark).

Widgets read them from here only. The colours that depend on the theme live in a
:class:`Colors` palette; :data:`colors` is the one in use.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtGui import QColor, QFont


# Colours that follow the theme
@dataclass(frozen=True)
class Colors:
    """One theme's colours. Widgets read the current ones from :data:`colors` when they
    paint, so a new palette shows on the next repaint."""

    window: QColor
    window_border: QColor
    surface: QColor  # selector button, target list, cards
    surface_border: QColor
    hover: QColor
    selected: QColor
    text: QColor
    text_secondary: QColor
    accent: QColor  # fills: a selected option, a checked box, a slider
    accent_text: QColor  # text and icons in the accent colour, such as a link
    on_accent: QColor  # icons and text drawn over the accent colour
    device_off: QColor  # ring of a device that is off or offline
    device_online: QColor  # status of a reachable device (manage page)
    danger: QColor  # text of a destructive action ("Excluir grupo")
    slider_rail: QColor  # the part of a slider's track after the thumb
    slider_thumb_fill: QColor
    slider_thumb_border: QColor
    focus: QColor  # the ring of a control reached with the keyboard
    row_border: QColor  # a device row on the manage and group pages
    dial_outline: QColor  # around the dial band and preview, where they would melt away

    def with_accent(self, accent: QColor, text: QColor | None = None) -> Colors:
        """These colours with ``accent``, ``text`` as the accent for text (``accent``
        itself when not given) and text over the accent in black or white."""
        return replace(
            self,
            accent=accent,
            accent_text=accent if text is None else text,
            on_accent=text_on(accent),
        )


DARK = Colors(
    window=QColor("#202020"),
    window_border=QColor("#3A3A3A"),
    surface=QColor("#2B2B2B"),
    surface_border=QColor("#3A3A3A"),
    hover=QColor("#323232"),
    selected=QColor("#383838"),
    text=QColor("#F3F3F3"),
    text_secondary=QColor("#B3B3B3"),
    accent=QColor("#F2B544"),
    accent_text=QColor("#F2B544"),
    on_accent=QColor("#1A1A1A"),
    device_off=QColor("#6B6B6B"),
    device_online=QColor("#3DD68C"),
    danger=QColor("#FF8A80"),
    slider_rail=QColor("#9E9E9E"),
    slider_thumb_fill=QColor("#454545"),
    slider_thumb_border=QColor("#5A5A5A"),
    focus=QColor("#FFFFFF"),
    row_border=QColor(0, 0, 0, 0),  # none in the mockups
    dial_outline=QColor(0, 0, 0, 0),
)

# No mockup: the light colours of the Windows 11 flyouts, checked for contrast in the tests.
LIGHT = Colors(
    window=QColor("#F3F3F3"),
    window_border=QColor("#C8C8C8"),
    surface=QColor("#FBFBFB"),
    surface_border=QColor("#E5E5E5"),
    hover=QColor("#EAEAEA"),
    selected=QColor("#E0E0E0"),
    text=QColor("#1A1A1A"),
    text_secondary=QColor("#5C5C5C"),
    accent=QColor("#0067C0"),
    accent_text=QColor("#003E92"),
    on_accent=QColor("#FFFFFF"),
    device_off=QColor("#8A8A8A"),
    device_online=QColor("#0F7B0F"),
    danger=QColor("#C42B1C"),
    slider_rail=QColor("#8A8A8A"),
    slider_thumb_fill=QColor("#FFFFFF"),
    slider_thumb_border=QColor("#C8C8C8"),
    focus=QColor("#1A1A1A"),
    row_border=QColor("#E5E5E5"),
    dial_outline=QColor(0, 0, 0, 40),
)

colors = DARK


def use(palette: Colors) -> None:
    """Make ``palette`` the current colours (the widgets still need restyling)."""
    global colors
    colors = palette


def contrast_ratio(first: QColor, second: QColor) -> float:
    """The WCAG contrast ratio of two colours, from 1 (same) to 21 (black on white)."""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def text_on(background: QColor) -> QColor:
    """Black or white, whichever reads better on ``background``."""
    black, white = QColor("#000000"), QColor("#FFFFFF")
    return max((white, black), key=lambda text: contrast_ratio(text, background))


def _luminance(color: QColor) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(c) for c in (color.redF(), color.greenF(), color.blueF()))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


# Colours shared by every theme
DEVICE_ON = QColor("#FF9F1C")  # dot of a device that is on
MARKER_BORDER = QColor("#FFFFFF")  # ring of the hue / temperature marker
MARKER_SHADOW = QColor(0, 0, 0, 110)  # keeps the marker visible on the light whites
DISABLED_OPACITY = 0.4
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
TABS_HEIGHT = 44  # the Branco | Cor switch
TABS_INSET = 4  # gap between the switch's border and the selected option
SLIDER_HEIGHT = 24  # the area that takes clicks
SLIDER_TRACK = 4
SLIDER_THUMB = 20
FOCUS_WIDTH = 2
SLIDER_THUMB_DOT = 12  # the accent dot in the thumb; a bit bigger while hovered
PANEL_GAP = 18  # between the switch, the dial and the sliders
SECTION_GAP = 24  # between the control panel and the scenes
SCENE_HEIGHT = 40  # a scene button
SCENE_GAP = 8
EDITOR_HEIGHT = 32  # the scene name field; also the scenes header
EDITOR_GAP = 4  # between the name field and its check / cross buttons
FIELD_PADDING = 8  # text inset of a text box
LINK_HEIGHT = 28  # a text link such as "+ Salvar atual"
SCROLLBAR_WIDTH = 6  # thickness
SCROLLBAR_GAP = 4  # between the scenes and their scroll bar
CARD_HEIGHT = 62  # a group on the manage page
CARD_GAP = 8
ITEM_HEIGHT = 44  # a device row on the manage page, a member row on the group page
ITEM_GAP = 6
ITEM_PADDING = 12  # text inset of a card or a row
BUTTON_HEIGHT = 40  # "Procurar lâmpadas novas", "Salvar", "Excluir grupo"
BUTTON_GAP = 10
FIELD_HEIGHT = 40  # the group name
CHECKBOX = 20
CHECKBOX_RADIUS = 4

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
