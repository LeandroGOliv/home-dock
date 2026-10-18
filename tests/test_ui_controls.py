"""Slider and segmented control: what the user clicks, drags or types is what they emit."""

import pytest
from PySide6.QtCore import QPoint, Qt

from homedock.ui import theme
from homedock.ui.controls import SegmentedControl, Slider, SliderRow
from ui_helpers import slider_point


class Recorder:
    def __init__(self, slider: Slider) -> None:
        self.moved: list[int] = []
        self.released: list[int] = []
        slider.moved.connect(self.moved.append)
        slider.released.connect(self.released.append)


@pytest.fixture
def slider(qtbot) -> Slider:
    widget = Slider(0, 100)
    qtbot.addWidget(widget)
    widget.setFixedWidth(200 + theme.SLIDER_THUMB)  # 2 px per step
    widget.set_value(50)
    widget.show()
    return widget


# --- slider -----------------------------------------------------------------------------------


def test_clicking_the_track_jumps_to_the_value_under_the_pointer(slider, qtbot):
    signals = Recorder(slider)

    qtbot.mouseClick(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 80))

    assert slider.value() == 80
    assert signals.moved == [80]
    assert signals.released == [80]


def test_dragging_reports_every_new_value_and_the_final_one_on_release(slider, qtbot):
    signals = Recorder(slider)

    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))
    qtbot.mouseMove(slider, slider_point(slider, 30))
    qtbot.mouseMove(slider, slider_point(slider, 30))  # no change, no signal
    qtbot.mouseMove(slider, slider_point(slider, 40))
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 40))

    assert signals.moved == [20, 30, 40]
    assert signals.released == [40]


def test_dragging_beyond_the_ends_stops_at_the_limits(slider, qtbot):
    signals = Recorder(slider)

    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 90))
    qtbot.mouseMove(slider, QPoint(slider.width() + 50, 0))
    assert slider.value() == 100
    qtbot.mouseMove(slider, QPoint(-50, 0))
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(-50, 0))

    assert slider.value() == 0
    assert signals.released == [0]


def test_a_click_on_the_current_value_emits_nothing(slider, qtbot):
    signals = Recorder(slider)

    qtbot.mouseClick(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 50))

    assert signals.moved == signals.released == []


def test_values_set_by_code_emit_nothing_and_are_clamped(slider):
    signals = Recorder(slider)

    slider.set_value(150)
    assert slider.value() == 100
    slider.set_value(-3)
    assert slider.value() == 0

    assert signals.moved == signals.released == []


def test_values_set_by_code_wait_until_the_drag_ends(slider, qtbot):
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))

    slider.set_value(70)  # e.g. a late answer of the device

    assert slider.value() == 20
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))
    slider.set_value(70)
    assert slider.value() == 70


def test_hiding_the_slider_mid_drag_ends_the_drag(slider, qtbot):
    signals = Recorder(slider)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))

    slider.hide()  # e.g. the flyout lost the focus

    assert signals.released == [20]
    slider.set_value(60)
    assert slider.value() == 60


def test_disabling_the_slider_mid_drag_ends_the_drag(slider, qtbot):
    signals = Recorder(slider)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))

    slider.setEnabled(False)

    assert signals.released == [20]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (Qt.Key.Key_Right, 51),
        (Qt.Key.Key_Up, 51),
        (Qt.Key.Key_Left, 49),
        (Qt.Key.Key_Down, 49),
        (Qt.Key.Key_PageUp, 60),
        (Qt.Key.Key_PageDown, 40),
        (Qt.Key.Key_Home, 0),
        (Qt.Key.Key_End, 100),
    ],
)
def test_the_keyboard_moves_the_value(slider, qtbot, key, value):
    signals = Recorder(slider)

    qtbot.keyClick(slider, key)

    assert slider.value() == value
    assert signals.moved == signals.released == [value]


def test_the_keyboard_stops_at_the_limits(slider, qtbot):
    slider.set_value(100)
    signals = Recorder(slider)

    qtbot.keyClick(slider, Qt.Key.Key_Right)

    assert slider.value() == 100
    assert signals.moved == []


def test_keys_are_ignored_while_dragging(slider, qtbot):
    signals = Recorder(slider)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))

    qtbot.keyClick(slider, Qt.Key.Key_End)

    assert slider.value() == 20
    assert signals.moved == [20]


def test_a_second_press_during_a_drag_is_ignored(slider, qtbot):
    signals = Recorder(slider)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))

    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 80))

    assert slider.value() == 20
    assert signals.moved == [20]


def test_other_buttons_are_ignored(slider, qtbot):
    signals = Recorder(slider)

    qtbot.mouseClick(slider, Qt.MouseButton.RightButton, pos=slider_point(slider, 80))

    assert slider.value() == 50
    assert signals.moved == []


def test_a_slider_paints_in_every_state(slider, qtbot):
    slider.grab()
    slider.setEnabled(False)
    slider.grab()


# --- slider row -------------------------------------------------------------------------------


def test_the_row_shows_its_title_and_the_value_in_percent(qtbot):
    row = SliderRow("Brilho", 1, 100)
    qtbot.addWidget(row)
    row.slider.setFixedWidth(200 + theme.SLIDER_THUMB)
    row.show()

    row.set_value(70)
    assert (row.title.text(), row.amount.text()) == ("Brilho", "70%")

    qtbot.mouseClick(row.slider, Qt.MouseButton.LeftButton, pos=slider_point(row.slider, 30))
    assert row.amount.text() == "30%"


# --- segmented control ------------------------------------------------------------------------


@pytest.fixture
def tabs(qtbot) -> SegmentedControl:
    widget = SegmentedControl([("white", "Branco"), ("color", "Cor")])
    qtbot.addWidget(widget)
    widget.setFixedWidth(theme.WIDTH - 2 * theme.PADDING)
    widget.show()
    return widget


def test_the_first_option_starts_selected(tabs):
    assert tabs.current() == "white"
    assert [b.text() for b in tabs.buttons] == ["Branco", "Cor"]
    assert [b.isChecked() for b in tabs.buttons] == [True, False]


def test_clicking_an_option_selects_it_and_emits_its_key(tabs, qtbot):
    chosen = []
    tabs.chosen.connect(chosen.append)

    qtbot.mouseClick(tabs.buttons[1], Qt.MouseButton.LeftButton)

    assert tabs.current() == "color"
    assert [b.isChecked() for b in tabs.buttons] == [False, True]
    assert chosen == ["color"]


def test_clicking_the_selected_option_emits_nothing(tabs, qtbot):
    chosen = []
    tabs.chosen.connect(chosen.append)

    qtbot.mouseClick(tabs.buttons[0], Qt.MouseButton.LeftButton)

    assert tabs.current() == "white"
    assert chosen == []


def test_an_option_set_by_code_emits_nothing(tabs):
    chosen = []
    tabs.chosen.connect(chosen.append)

    tabs.set_current("color")

    assert tabs.current() == "color"
    assert [b.isChecked() for b in tabs.buttons] == [False, True]
    assert chosen == []


def test_the_segmented_control_paints(tabs):
    tabs.grab()
    tabs.setEnabled(False)
    tabs.grab()
