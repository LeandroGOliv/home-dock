"""Hue ring and temperature arc: clicks and drags emit the value under the pointer."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QRegion
from PySide6.QtWidgets import QWidget

from homedock.ui import strings, theme
from homedock.ui.dial_math import hex_to_hsv, polar
from homedock.ui.dials import Dial, HueRing, TemperatureArc

MIDDLE = (theme.DIAL_SIZE - theme.DIAL_BAND) / 2  # radius of the band's centre line


def at(dial: Dial, angle: float, radius: float = MIDDLE) -> QPoint:
    """The widget point at ``angle`` and ``radius`` from the dial's centre."""
    x, y = polar(dial.width() / 2, dial.height() / 2, radius, angle)
    return QPoint(round(x), round(y))


class Recorder:
    def __init__(self, dial: Dial) -> None:
        self.moved: list[int] = []
        self.released: list[int] = []
        dial.moved.connect(self.moved.append)
        dial.released.connect(self.released.append)


def press(qtbot, dial: Dial, point: QPoint) -> None:
    qtbot.mousePress(dial, Qt.MouseButton.LeftButton, pos=point)


def move(qtbot, dial: Dial, point: QPoint) -> None:
    qtbot.mouseMove(dial, point)


def release(qtbot, dial: Dial, point: QPoint) -> None:
    qtbot.mouseRelease(dial, Qt.MouseButton.LeftButton, pos=point)


@pytest.fixture
def ring(qtbot) -> HueRing:
    widget = HueRing()
    qtbot.addWidget(widget)
    widget.set_color(0, 100)
    widget.show()
    return widget


@pytest.fixture
def arc(qtbot) -> TemperatureArc:
    widget = TemperatureArc()
    qtbot.addWidget(widget)
    widget.set_value(50)
    widget.show()
    return widget


# --- hue ring ---------------------------------------------------------------------------------


def test_the_ring_has_the_mockup_size(ring):
    assert ring.width() == ring.height() == theme.DIAL_SIZE


def test_clicking_the_ring_picks_the_hue_under_the_pointer(ring, qtbot):
    signals = Recorder(ring)

    qtbot.mouseClick(ring, Qt.MouseButton.LeftButton, pos=at(ring, 90))

    assert signals.moved == [90]
    assert signals.released == [90]
    assert ring.value() == 90


@pytest.mark.parametrize(
    "radius", [MIDDLE - theme.DIAL_BAND / 2 + 1, MIDDLE + theme.DIAL_BAND / 2 - 1]
)
def test_the_whole_band_is_clickable(ring, qtbot, radius):
    qtbot.mouseClick(ring, Qt.MouseButton.LeftButton, pos=at(ring, 180, radius))

    assert ring.value() == 180


def test_dragging_emits_every_hue_and_the_last_one_on_release(ring, qtbot):
    signals = Recorder(ring)

    press(qtbot, ring, at(ring, 90))
    move(qtbot, ring, at(ring, 135))
    move(qtbot, ring, at(ring, 180))
    release(qtbot, ring, at(ring, 180))

    assert signals.moved == [90, 135, 180]
    assert signals.released == [180]


def test_the_drag_follows_the_angle_off_the_band(ring, qtbot):
    signals = Recorder(ring)

    press(qtbot, ring, at(ring, 90))
    move(qtbot, ring, at(ring, 270, 20))  # near the centre
    move(qtbot, ring, at(ring, 315, 400))  # far outside the widget
    release(qtbot, ring, at(ring, 315, 400))

    assert signals.moved == [90, 270, 315]
    assert signals.released == [315]


def test_dragging_across_the_top_wraps_around(ring, qtbot):
    signals = Recorder(ring)

    press(qtbot, ring, at(ring, 350))
    move(qtbot, ring, at(ring, 10))
    release(qtbot, ring, at(ring, 10))

    assert signals.moved == [350, 10]


def test_pressing_the_marker_does_not_make_it_jump(ring, qtbot):
    ring.set_value(100)
    signals = Recorder(ring)

    qtbot.mouseClick(ring, Qt.MouseButton.LeftButton, pos=at(ring, 103))  # inside the marker

    assert ring.value() == 100
    assert signals.moved == signals.released == []


def test_the_marker_keeps_its_distance_to_the_pointer_while_dragged(ring, qtbot):
    ring.set_value(100)
    signals = Recorder(ring)

    press(qtbot, ring, at(ring, 103))  # 3° past the marker's centre
    move(qtbot, ring, at(ring, 200))
    release(qtbot, ring, at(ring, 200))

    assert signals.moved == [197]
    assert signals.released == [197]


def test_the_marker_grabbed_across_the_top_drags_without_jumping(ring, qtbot):
    ring.set_value(1)
    signals = Recorder(ring)

    press(qtbot, ring, at(ring, 358))  # 3° before the marker, across 0°
    move(qtbot, ring, at(ring, 90))
    release(qtbot, ring, at(ring, 90))

    assert signals.moved == [93]


def test_a_drag_back_to_the_start_still_reports_the_release(ring, qtbot):
    signals = Recorder(ring)

    press(qtbot, ring, at(ring, 90))
    move(qtbot, ring, at(ring, 120))
    move(qtbot, ring, at(ring, 90))
    release(qtbot, ring, at(ring, 90))

    assert signals.moved == [90, 120, 90]
    assert signals.released == [90]


@pytest.mark.parametrize("radius", [0, 40, MIDDLE + theme.DIAL_BAND])
def test_presses_off_the_band_are_ignored(ring, qtbot, radius):
    signals = Recorder(ring)

    press(qtbot, ring, at(ring, 60, radius))
    move(qtbot, ring, at(ring, 90))
    release(qtbot, ring, at(ring, 90))

    assert ring.value() == 0
    assert signals.moved == signals.released == []


def test_other_buttons_are_ignored(ring, qtbot):
    signals = Recorder(ring)

    qtbot.mouseClick(ring, Qt.MouseButton.RightButton, pos=at(ring, 90))

    assert ring.value() == 0
    assert signals.moved == signals.released == []


def test_set_value_emits_nothing(ring, qtbot):
    signals = Recorder(ring)

    ring.set_value(200)

    assert ring.value() == 200
    assert signals.moved == signals.released == []


def test_values_set_during_a_drag_are_ignored(ring, qtbot):
    press(qtbot, ring, at(ring, 90))

    ring.set_value(300)  # e.g. a device answering an earlier command

    assert ring.value() == 90
    release(qtbot, ring, at(ring, 90))
    ring.set_value(300)
    assert ring.value() == 300


def test_the_ring_shows_the_colour_at_full_brightness(ring):
    ring.set_color(28, 85)

    assert ring.value() == 28
    assert ring.saturation() == 85
    assert ring.hex_code() == "#FF8B26"
    assert ring.accessibleDescription() == "#FF8B26"


def test_the_saturation_changes_the_preview_only(ring):
    ring.set_color(0, 100)

    ring.set_saturation(0)

    assert ring.value() == 0
    assert ring.hex_code() == "#FFFFFF"


def test_a_hue_of_360_is_shown_as_0(ring):
    ring.set_value(360)

    assert ring.value() == 0


# --- temperature arc --------------------------------------------------------------------------


@pytest.mark.parametrize(("angle", "temperature"), [(225, 0), (292.5, 25), (0, 50), (135, 100)])
def test_clicking_the_arc_picks_the_temperature_under_the_pointer(arc, qtbot, angle, temperature):
    arc.set_value(60)
    signals = Recorder(arc)

    qtbot.mouseClick(arc, Qt.MouseButton.LeftButton, pos=at(arc, angle))

    assert signals.moved == [temperature]
    assert signals.released == [temperature]


@pytest.mark.parametrize("angle", [160, 180, 200])
def test_presses_in_the_dead_zone_are_ignored(arc, qtbot, angle):
    signals = Recorder(arc)

    qtbot.mouseClick(arc, Qt.MouseButton.LeftButton, pos=at(arc, angle))

    assert arc.value() == 50
    assert signals.moved == signals.released == []


@pytest.mark.parametrize(("start", "end", "moved"), [(90, 170, [83, 100]), (270, 190, [17, 0])])
def test_dragging_into_the_dead_zone_stops_at_the_nearest_end(arc, qtbot, start, end, moved):
    signals = Recorder(arc)

    press(qtbot, arc, at(arc, start))
    move(qtbot, arc, at(arc, end))
    release(qtbot, arc, at(arc, end))

    assert signals.moved == moved
    assert signals.released == [moved[-1]]


def test_the_arc_shows_the_tint_and_the_kind_of_white(arc):
    arc.set_value(0)
    assert arc.tint() == theme.TEMPERATURE_COLORS[0].name().upper()
    assert arc.label() == strings.WARM

    arc.set_value(100)
    assert arc.tint() == theme.TEMPERATURE_COLORS[-1].name().upper()
    assert arc.label() == strings.COLD
    assert arc.accessibleDescription() == strings.COLD


@pytest.mark.parametrize(
    ("temperature", "label"),
    [
        (0, strings.WARM),
        (33, strings.WARM),
        (34, strings.NEUTRAL),
        (50, strings.NEUTRAL),
        (66, strings.NEUTRAL),
        (67, strings.COLD),
        (100, strings.COLD),
    ],
)
def test_temperature_labels(temperature, label):
    assert strings.temperature_label(temperature) == label


# --- painting ---------------------------------------------------------------------------------


@pytest.mark.parametrize("dial_type", [HueRing, TemperatureArc])
@pytest.mark.parametrize("value", [0, 50, 100])
@pytest.mark.parametrize("enabled", [False, True])
def test_the_dials_paint_in_every_state(qtbot, dial_type, value, enabled):
    dial = dial_type()
    qtbot.addWidget(dial)
    dial.set_value(value)
    dial.setEnabled(enabled)
    image = QImage(dial.size(), QImage.Format.Format_ARGB32)
    dial.render(image)  # must not raise


def test_the_ring_paints_the_hue_under_the_marker(qtbot):
    ring = HueRing()
    qtbot.addWidget(ring)
    ring.set_color(120, 100)
    image = QImage(ring.size(), QImage.Format.Format_ARGB32)
    image.fill(theme.WINDOW)
    ring.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)  # no background

    def hue(point: QPoint) -> int:
        return hex_to_hsv(image.pixelColor(point).name())[0]

    assert hue(at(ring, 0)) in (0, 1, 359)  # red at the top
    assert hue(at(ring, 240)) == pytest.approx(240, abs=1)
    assert image.pixelColor(at(ring, 120)).name() == "#00ff00"  # the marker's fill
    assert image.pixelColor(at(ring, 90, 50)) == theme.WINDOW  # between the preview and the band
