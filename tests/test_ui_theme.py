"""The flyout's colours: one palette at a time, applied to every widget when it changes."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPalette, QRegion
from PySide6.QtWidgets import QScrollArea, QWidget

from homedock.ui import theme
from homedock.ui.controls import NameEditor, TextField
from homedock.ui.dial_math import polar
from homedock.ui.dials import HueRing, TemperatureArc
from homedock.ui.manage import ScrollBody
from homedock.ui.scenes import SceneStrip
from homedock.ui.selector import TargetButton, TargetList
from homedock.ui.widgets import label, restyle_all


def use_changed(**fields: str) -> None:
    theme.use(replace(theme.DARK, **{name: QColor(value) for name, value in fields.items()}))
    restyle_all()


def text_color(widget) -> QColor:
    return widget.palette().color(widget.foregroundRole())


def test_the_dark_palette_is_used_until_another_is_chosen():
    assert theme.colors == theme.DARK


def test_use_replaces_the_current_palette():
    colors = replace(theme.DARK, accent=QColor("#123456"))
    theme.use(colors)
    assert theme.colors is colors


def test_labels_take_the_new_text_colours(qtbot):
    title = label("Cenas", theme.font())
    caption = label("Nenhuma", theme.font(), secondary=True)
    qtbot.addWidget(title)
    qtbot.addWidget(caption)
    assert text_color(title) == theme.DARK.text
    assert text_color(caption) == theme.DARK.text_secondary

    use_changed(text="#101010", text_secondary="#202020")

    assert text_color(title).name() == "#101010"
    assert text_color(caption).name() == "#202020"


def test_text_fields_take_the_new_colours(qtbot):
    field = TextField()
    editor = NameEditor("Nome")
    qtbot.addWidget(field)
    qtbot.addWidget(editor)

    use_changed(accent="#123456", surface="#654321", text_secondary="#202020")

    for line_edit in (field, editor.field):
        assert "#123456" in line_edit.styleSheet()
        assert "#654321" in line_edit.styleSheet()
        placeholder = line_edit.palette().color(QPalette.ColorRole.PlaceholderText)
        assert placeholder.name() == "#202020"


def test_scroll_bars_take_the_new_colours(qtbot):
    body, strip, targets = ScrollBody(), SceneStrip(), TargetList()
    for widget in (body, strip, targets):
        qtbot.addWidget(widget)

    use_changed(device_off="#123456")

    for widget in (body, strip, targets.findChild(QScrollArea)):
        assert "#123456" in widget.styleSheet()


def test_painted_widgets_use_the_current_palette(qtbot):
    button = TargetButton()
    qtbot.addWidget(button)
    button.resize(200, 44)
    use_changed(surface="#123456")

    image = QImage(button.size(), QImage.Format.Format_ARGB32)
    button.render(image)
    assert image.pixelColor(QPoint(40, 22)).name() == "#123456"


# --- contrast -------------------------------------------------------------------------------

BLACK, WHITE = QColor("#000000"), QColor("#FFFFFF")
PALETTES = pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
# Accents Windows offers, as the flyouts show them: light shades on dark, dark ones on light.
ACCENTS = ["#40BDFF", "#0055A1", "#F2B544", "#FFB900", "#E81123", "#00CC6A", "#744DA9", "#767676"]


def test_contrast_ratio_spans_one_to_twenty_one():
    assert theme.contrast_ratio(BLACK, WHITE) == pytest.approx(21)
    assert theme.contrast_ratio(WHITE, BLACK) == pytest.approx(21)
    assert theme.contrast_ratio(QColor("#777777"), QColor("#777777")) == pytest.approx(1)


def test_contrast_ratio_matches_the_wcag_formula():
    assert theme.contrast_ratio(QColor("#767676"), WHITE) == pytest.approx(4.54, abs=0.01)


@pytest.mark.parametrize(("background", "expected"), [("#40BDFF", BLACK), ("#0055A1", WHITE)])
def test_text_on_picks_black_or_white(background, expected):
    assert theme.text_on(QColor(background)) == expected


@PALETTES
@pytest.mark.parametrize("accent", ACCENTS)
def test_text_over_any_accent_is_readable(palette, accent):
    colors = palette.with_accent(QColor(accent))
    assert colors.accent == QColor(accent)
    assert theme.contrast_ratio(colors.on_accent, colors.accent) >= 4.5


@PALETTES
@pytest.mark.parametrize("background", ["window", "surface", "hover", "selected"])
def test_text_is_readable_on_every_background(palette, background):
    fill = getattr(palette, background)
    assert theme.contrast_ratio(palette.text, fill) >= 4.5
    assert theme.contrast_ratio(palette.text_secondary, fill) >= 4.5


@PALETTES
def test_status_and_focus_colours_stand_out(palette):
    assert theme.contrast_ratio(palette.danger, palette.window) >= 4.5
    assert theme.contrast_ratio(palette.device_online, palette.surface) >= 3
    assert theme.contrast_ratio(palette.focus, palette.window) >= 3


def test_the_light_palette_is_light():
    assert theme.contrast_ratio(theme.LIGHT.window, WHITE) < 1.2
    assert theme.contrast_ratio(theme.LIGHT.text, BLACK) < 1.5


# --- dials ----------------------------------------------------------------------------------


def band_edge_and_middle(dial) -> tuple[QColor, QColor]:
    """The colours of the band beside the marker: just inside its outer edge, and in its
    middle (same angle, so same colour without an outline)."""
    image = QImage(dial.size(), QImage.Format.Format_ARGB32)
    image.fill(theme.colors.window)
    dial.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)  # no background
    centre, angle = dial.width() / 2, 60

    def at(radius: float) -> QColor:
        x, y = polar(centre, centre, radius, angle)
        return image.pixelColor(QPoint(int(x), int(y)))

    return at(theme.DIAL_SIZE / 2 - 1), at((theme.DIAL_SIZE - theme.DIAL_BAND) / 2)


@pytest.mark.parametrize("dial_type", [HueRing, TemperatureArc])
def test_the_dial_band_is_outlined_on_the_light_theme(qtbot, dial_type):
    """The pale parts of the band (yellow, warm white) would melt into a light window."""
    theme.use(theme.LIGHT)
    dial = dial_type()
    qtbot.addWidget(dial)
    edge, middle = band_edge_and_middle(dial)
    assert edge.lightness() < middle.lightness() - 10


@pytest.mark.parametrize("dial_type", [HueRing, TemperatureArc])
def test_the_dial_band_has_no_outline_on_the_dark_theme(qtbot, dial_type):
    dial = dial_type()
    qtbot.addWidget(dial)
    edge, middle = band_edge_and_middle(dial)
    assert abs(edge.lightness() - middle.lightness()) <= 4
