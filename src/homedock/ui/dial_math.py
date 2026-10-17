"""Geometry and colour maths of the hue ring and the temperature arc, as pure functions.

Angles are compass angles: degrees clockwise from the top (12 o'clock), in screen
coordinates (y grows downwards). The hue ring puts hue 0° at the top. The temperature arc
spans 270°, open at the bottom: warm (0 %) at the bottom left, cold (100 %) at the bottom
right, neutral at the top.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

ARC_START = 225.0  # warm end
ARC_SPAN = 270.0
ARC_END = (ARC_START + ARC_SPAN) % 360  # cold end
_DEAD_ZONE_MIDDLE = ARC_SPAN + (360 - ARC_SPAN) / 2  # offset from ARC_START of the bottom

RGB = tuple[int, int, int]


def compass_angle(dx: float, dy: float) -> float:
    """The direction of ``(dx, dy)`` from the centre, in [0, 360); 0 for the centre itself."""
    angle = math.degrees(math.atan2(dx, -dy)) % 360
    return 0.0 if angle >= 360 else angle  # a tiny negative angle rounds up to 360


def polar(cx: float, cy: float, radius: float, angle: float) -> tuple[float, float]:
    """The point at ``radius`` from ``(cx, cy)`` in the direction ``angle``."""
    rad = math.radians(angle)
    return cx + radius * math.sin(rad), cy - radius * math.cos(rad)


def gradient_position(angle: float) -> float:
    """Where ``angle`` falls on a ``QConicalGradient`` starting at the top (Qt angle 90°);
    its positions run counter-clockwise from 0 to 1."""
    return ((360 - angle) % 360) / 360


def hue_to_angle(hue: float) -> float:
    return hue % 360


def angle_to_hue(angle: float) -> int:
    """The hue (0-359°) under ``angle``."""
    return round(angle) % 360


def temperature_to_angle(temperature: float) -> float:
    """The angle of a colour temperature (0 = warmest, 100 = coldest) on the arc."""
    return (ARC_START + temperature / 100 * ARC_SPAN) % 360


def in_arc(angle: float) -> bool:
    return _arc_offset(angle) <= ARC_SPAN


def angle_to_temperature(angle: float) -> int:
    """The colour temperature (0-100) under ``angle``; an angle in the dead zone at the
    bottom snaps to the nearest end (the bottom centre itself to the warm end)."""
    offset = _arc_offset(angle)
    if offset > ARC_SPAN:
        return 100 if offset < _DEAD_ZONE_MIDDLE else 0
    return round(offset / ARC_SPAN * 100)


def drag_temperature(angle: float, current: int, held: int | None) -> tuple[int, int | None]:
    """The colour temperature under ``angle`` during a drag, and the end it is held at.

    A drag entering the opening holds the end it came from (the one nearer ``current``)
    and stays there until the pointer comes back onto that end's half of the arc, so a
    drag across the opening never jumps from one end to the other. ``held`` is what the
    previous call returned (``None`` when the drag starts).
    """
    if not in_arc(angle):
        end = held if held is not None else (0 if current < 50 else 100)
        return end, end
    value = angle_to_temperature(angle)
    if held is None or (value < 50) == (held == 0):
        return value, None
    return held, held


def _arc_offset(angle: float) -> float:
    return (angle - ARC_START) % 360


def hsv_to_hex(hue: float, saturation: float, value: float = 100) -> str:
    """``#RRGGBB`` of hue 0-360°, saturation and value 0-100 %."""
    chroma = value / 100 * saturation / 100
    sector = (hue % 360) / 60
    second = chroma * (1 - abs(sector % 2 - 1))
    smallest = value / 100 - chroma
    r, g, b = [
        (chroma, second, 0),
        (second, chroma, 0),
        (0, chroma, second),
        (0, second, chroma),
        (second, 0, chroma),
        (chroma, 0, second),
    ][int(sector)]
    return _to_hex(tuple(_channel((c + smallest) * 255) for c in (r, g, b)))


def hex_to_hsv(text: str) -> tuple[int, int, int]:
    """Hue (0-359°), saturation and value (0-100 %) of ``#RRGGBB`` (``#`` optional)."""
    r, g, b = _from_hex(text)
    largest, smallest = max(r, g, b), min(r, g, b)
    delta = largest - smallest
    if delta == 0:
        hue = 0.0
    elif largest == r:
        hue = 60 * (((g - b) / delta) % 6)
    elif largest == g:
        hue = 60 * ((b - r) / delta + 2)
    else:
        hue = 60 * ((r - g) / delta + 4)
    saturation = delta / largest * 100 if largest else 0
    return round(hue) % 360, round(saturation), round(largest / 255 * 100)


def blend(colors: Sequence[str], fraction: float) -> str:
    """The colour at ``fraction`` (0-1, clamped) of a linear gradient through ``colors``
    (``#RRGGBB``), evenly spaced."""
    stops = [_from_hex(color) for color in colors]
    position = min(max(fraction, 0.0), 1.0) * (len(stops) - 1)
    index = min(int(position), len(stops) - 2)
    local = position - index
    start, end = stops[index], stops[index + 1]
    return _to_hex(tuple(_channel(a + (b - a) * local) for a, b in zip(start, end, strict=True)))


def _channel(value: float) -> int:
    return min(max(math.floor(value + 0.5), 0), 255)  # half up, not to even


def _to_hex(rgb: tuple[int, ...]) -> str:
    return "#" + "".join(f"{c:02X}" for c in rgb)


def _from_hex(text: str) -> RGB:
    digits = text.removeprefix("#")
    if len(digits) != 6 or any(c not in "0123456789abcdefABCDEF" for c in digits):
        raise ValueError(f"not a #RRGGBB colour: {text!r}")
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
