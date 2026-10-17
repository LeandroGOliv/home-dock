"""Geometry and colour maths of the hue ring and the temperature arc (pure functions)."""

import pytest

from homedock.ui.dial_math import (
    ARC_END,
    ARC_START,
    angle_to_hue,
    angle_to_temperature,
    blend,
    compass_angle,
    drag_temperature,
    gradient_position,
    hex_to_hsv,
    hsv_to_hex,
    hue_to_angle,
    in_arc,
    polar,
    temperature_to_angle,
)

# --- angles -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dx", "dy", "angle"),
    [
        (0, -1, 0),  # up (screen y grows downwards)
        (1, -1, 45),
        (1, 0, 90),
        (0, 1, 180),
        (-1, 0, 270),
        (-1, -1, 315),
        (0, -0.001, 0),
        (0, 0, 0),  # the centre itself has no direction
    ],
)
def test_compass_angle_is_clockwise_from_the_top(dx, dy, angle):
    assert compass_angle(dx, dy) == pytest.approx(angle)


@pytest.mark.parametrize("dx", [-0.001, -1e-9])
def test_compass_angle_just_left_of_the_top_is_below_360(dx):
    assert 359 < compass_angle(dx, -1) < 360


@pytest.mark.parametrize(
    ("angle", "point"),
    [(0, (100, 90)), (90, (110, 100)), (180, (100, 110)), (270, (90, 100))],
)
def test_polar_places_a_point_at_an_angle_around_the_centre(angle, point):
    assert polar(100, 100, 10, angle) == pytest.approx(point)


@pytest.mark.parametrize("angle", [0, 33, 90, 135, 225, 300, 359])
def test_polar_and_compass_angle_are_inverse(angle):
    x, y = polar(0, 0, 50, angle)
    assert compass_angle(x, y) == pytest.approx(angle)


@pytest.mark.parametrize(
    ("angle", "position"),
    [(0, 0.0), (90, 0.75), (180, 0.5), (270, 0.25), (360, 0.0), (ARC_START, 0.375)],
)
def test_gradient_position_runs_counter_clockwise_from_the_top(angle, position):
    assert gradient_position(angle) == pytest.approx(position)


# --- hue ring ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hue", "angle"), [(0, 0), (28, 28), (90, 90), (180, 180), (359, 359), (360, 0)]
)
def test_hue_is_the_clockwise_angle_from_the_top(hue, angle):
    assert hue_to_angle(hue) == pytest.approx(angle)


@pytest.mark.parametrize(
    ("angle", "hue"),
    [(0, 0), (27.6, 28), (180, 180), (359.4, 359), (359.6, 0), (360, 0), (-1, 359), (721, 1)],
)
def test_angle_to_hue_rounds_and_wraps_around(angle, hue):
    assert angle_to_hue(angle) == hue


# --- temperature arc --------------------------------------------------------------------------


def test_the_arc_spans_270_degrees_open_at_the_bottom():
    assert ARC_START == 225  # warm end, bottom left
    assert ARC_END == 135  # cold end, bottom right


@pytest.mark.parametrize(
    ("temperature", "angle"), [(0, 225), (25, 292.5), (50, 0), (75, 67.5), (100, 135)]
)
def test_temperature_runs_clockwise_from_warm_to_cold(temperature, angle):
    assert temperature_to_angle(temperature) == pytest.approx(angle)


@pytest.mark.parametrize(
    ("angle", "temperature"),
    [
        (225, 0),
        (226, 0),
        (292.5, 25),
        (300, 28),
        (0, 50),
        (360, 50),
        (67.5, 75),
        (134, 100),
        (135, 100),
    ],
)
def test_angle_to_temperature_on_the_arc(angle, temperature):
    assert angle_to_temperature(angle) == temperature


@pytest.mark.parametrize(
    ("angle", "temperature"),
    [
        (135.5, 100),  # dead zone, right half: the cold end
        (170, 100),
        (179.9, 100),
        (180, 0),  # the bottom centre goes to the warm end
        (200, 0),
        (224.9, 0),  # dead zone, left half: the warm end
    ],
)
def test_the_dead_zone_snaps_to_the_nearest_end(angle, temperature):
    assert angle_to_temperature(angle) == temperature


@pytest.mark.parametrize(
    ("angle", "inside"),
    [
        (225, True),
        (270, True),
        (0, True),
        (90, True),
        (135, True),
        (135.5, False),
        (180, False),
        (224.5, False),
    ],
)
def test_in_arc(angle, inside):
    assert in_arc(angle) is inside


@pytest.mark.parametrize(
    ("angle", "current", "held", "result"),
    [
        (0, 40, None, (50, None)),  # on the arc: the value under the pointer
        (170, 98, None, (100, 100)),  # into the opening from the cold end: held there
        (190, 100, 100, (100, 100)),  # across the opening's middle: still held
        (230, 100, 100, (100, 100)),  # onto the warm end: still held
        (300, 100, 100, (100, 100)),  # anywhere on the warm half
        (90, 100, 100, (83, None)),  # back on the cold half: released
        (200, 10, None, (0, 0)),  # into the opening from the warm end
        (45, 0, 0, (0, 0)),  # the cold half does not release the warm end
        (250, 0, 0, (9, None)),
        (170, 20, None, (0, 0)),  # through the centre from the warm half: the warm end
    ],
)
def test_a_drag_through_the_opening_stays_at_the_end_it_came_from(angle, current, held, result):
    assert drag_temperature(angle, current, held) == result


@pytest.mark.parametrize("temperature", range(0, 101, 5))
def test_temperature_and_angle_are_inverse(temperature):
    assert angle_to_temperature(temperature_to_angle(temperature)) == temperature


# --- colours ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hsv", "hex_code"),
    [
        ((0, 100, 100), "#FF0000"),
        ((60, 100, 100), "#FFFF00"),
        ((120, 100, 100), "#00FF00"),
        ((180, 100, 100), "#00FFFF"),
        ((240, 100, 100), "#0000FF"),
        ((300, 100, 100), "#FF00FF"),
        ((360, 100, 100), "#FF0000"),
        ((28, 85, 100), "#FF8B26"),  # the mockup's colour
        ((0, 0, 100), "#FFFFFF"),
        ((200, 50, 0), "#000000"),
        ((210, 50, 50), "#406080"),
    ],
)
def test_hsv_to_hex(hsv, hex_code):
    assert hsv_to_hex(*hsv) == hex_code


def test_hsv_to_hex_defaults_to_full_value():
    assert hsv_to_hex(28, 85) == "#FF8B26"


@pytest.mark.parametrize(
    ("hex_code", "hsv"),
    [
        ("#FF0000", (0, 100, 100)),
        ("#00ff00", (120, 100, 100)),
        ("0000FF", (240, 100, 100)),
        ("#FF8B26", (28, 85, 100)),
        ("#FFFFFF", (0, 0, 100)),
        ("#000000", (0, 0, 0)),
        ("#406080", (210, 50, 50)),
        ("#FF0001", (0, 100, 100)),  # a hue just below 360 rounds to 0
    ],
)
def test_hex_to_hsv(hex_code, hsv):
    assert hex_to_hsv(hex_code) == hsv


@pytest.mark.parametrize("hue", range(0, 360, 15))
@pytest.mark.parametrize("saturation", [40, 85, 100])
def test_hsv_survives_a_round_trip_through_hex(hue, saturation):
    assert hex_to_hsv(hsv_to_hex(hue, saturation)) == (hue, saturation, 100)


@pytest.mark.parametrize("text", ["", "#FFF", "#GG0000", "#FF00000", "FF 000"])
def test_hex_to_hsv_rejects_invalid_codes(text):
    with pytest.raises(ValueError):
        hex_to_hsv(text)


@pytest.mark.parametrize(
    ("fraction", "color"),
    [
        (0, "#000000"),
        (0.25, "#404040"),
        (0.5, "#808080"),
        (0.75, "#BFBFBF"),
        (1, "#FFFFFF"),
        (-1, "#000000"),
        (2, "#FFFFFF"),
    ],
)
def test_blend_interpolates_between_two_colours(fraction, color):
    assert blend(["#000000", "#FFFFFF"], fraction) == color


@pytest.mark.parametrize(
    ("fraction", "color"),
    [(0, "#FF0000"), (0.25, "#808000"), (0.5, "#00FF00"), (0.75, "#008080"), (1, "#0000FF")],
)
def test_blend_spaces_several_colours_evenly(fraction, color):
    assert blend(["#FF0000", "#00FF00", "#0000FF"], fraction) == color
