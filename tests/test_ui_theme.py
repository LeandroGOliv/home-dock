"""The flyout's colours: one palette at a time, applied to every widget when it changes."""

from dataclasses import replace

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QScrollArea

from homedock.ui import theme
from homedock.ui.controls import NameEditor, TextField
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
