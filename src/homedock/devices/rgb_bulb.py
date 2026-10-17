"""Driver for Tuya RGB+CCT bulbs with the v2 DPS set (Positivo PSBAM, category ``dj``).

Every DPS number, code, range and encoding of the bulb lives in this module. Mapping
confirmed on real bulbs by ``scripts/diagnose.py`` (see CLAUDE.md "Device / DPS notes").
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from homedock.devices.base import (
    Capability,
    Color,
    DeviceError,
    DeviceState,
    DeviceType,
    WorkMode,
)
from homedock.devices.spec import DeviceSpec
from homedock.devices.tuya import LinkFactory, TuyaLink, connect_tinytuya

CATEGORY = "dj"
POWER_DP = "20"  # bool
MODE_DP = "21"  # "white" / "colour" / "scene" / "music"
WHITE_BRIGHTNESS_DP = "22"  # 10-1000; writing it in colour mode switches to white
TEMPERATURE_DP = "23"  # 0 (warm) - 1000 (cold)
COLOUR_DP = "24"  # "HHHHSSSSVVVV" hex: H 0-360, S 0-1000, V 0-1000

CODES = {
    POWER_DP: "switch_led",
    MODE_DP: "work_mode",
    WHITE_BRIGHTNESS_DP: "bright_value_v2",
    TEMPERATURE_DP: "temp_value_v2",
    COLOUR_DP: "colour_data_v2",
}
REQUIRED_DPS = (POWER_DP, MODE_DP, WHITE_BRIGHTNESS_DP, COLOUR_DP)
MODES = {WorkMode.WHITE: "white", WorkMode.COLOR: "colour"}
RAW_MAX = 1000  # full scale of brightness, saturation, temperature and V
MIN_BRIGHTNESS = 10  # dimmest raw brightness (white DPS and colour V)
READ_ATTEMPTS = 3
# The Tuya app or a power cut may change the bulb behind our back: re-read a cache this old
# (seconds) before writing, so the mode-dependent DPS choice is never made on stale data.
CACHE_TTL = 10.0


# --- pure conversions ---------------------------------------------------------------------


def to_raw(percent: int, minimum: int = 0) -> int:
    return max(minimum, percent * RAW_MAX // 100)


def to_percent(raw: int) -> int:
    return (raw * 100 + RAW_MAX // 2) // RAW_MAX


def encode_colour(hue: int, saturation: int, value: int) -> str:
    return f"{hue:04x}{saturation:04x}{value:04x}"


def decode_colour(text: object) -> tuple[int, int, int] | None:
    """Raw (H, S, V) of a colour DPS value, or ``None`` if it is malformed."""
    if not isinstance(text, str) or len(text) != 12:
        return None
    try:
        hue, saturation, value = (int(text[i : i + 4], 16) for i in (0, 4, 8))
    except ValueError:
        return None
    if hue > 360 or saturation > RAW_MAX or value > RAW_MAX:
        return None
    return hue, saturation, value


def state_from_dps(dps: dict[str, Any]) -> DeviceState:
    """Normalised state of the bulb from its (cached) DPS."""
    mode = next((m for m, raw in MODES.items() if raw == dps.get(MODE_DP)), None)
    colour = decode_colour(dps.get(COLOUR_DP))
    brightness = None
    white_brightness = dps.get(WHITE_BRIGHTNESS_DP)
    if mode is WorkMode.WHITE and _is_int(white_brightness):
        brightness = to_percent(white_brightness)
    elif mode is WorkMode.COLOR and colour is not None:
        brightness = to_percent(colour[2])
    temperature = dps.get(TEMPERATURE_DP)
    return DeviceState(
        power=dps.get(POWER_DP) if isinstance(dps.get(POWER_DP), bool) else None,
        work_mode=mode,
        brightness=brightness,
        color_hsv=Color(colour[0], to_percent(colour[1])) if colour else None,
        color_temperature=to_percent(temperature) if _is_int(temperature) else None,
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def target_mode(changes: DeviceState, current: WorkMode | None) -> WorkMode | None:
    """Mode the bulb must be in: explicit, implied by a colour/temperature change, or kept."""
    if changes.work_mode is not None:
        return changes.work_mode
    if changes.color_hsv is not None and changes.color_temperature is None:
        return WorkMode.COLOR
    if changes.color_temperature is not None and changes.color_hsv is None:
        return WorkMode.WHITE
    return current


def build_payload(changes: DeviceState, dps: dict[str, Any]) -> dict[str, Any]:
    """DPS to write for ``changes`` given the current DPS.

    Only the DPS of the target mode are written: white brightness/temperature in white
    mode, colour data in colour mode. Values for the other mode are dropped, because
    writing them would switch the bulb's mode.
    """
    payload: dict[str, Any] = {}
    if changes.power is not None:
        payload[POWER_DP] = changes.power
    current = state_from_dps(dps).work_mode
    mode = target_mode(changes, current)
    if mode is not None and (changes.work_mode is not None or mode is not current):
        payload[MODE_DP] = MODES[mode]
    if mode is WorkMode.WHITE:
        if changes.brightness is not None:
            payload[WHITE_BRIGHTNESS_DP] = to_raw(changes.brightness, MIN_BRIGHTNESS)
        if changes.color_temperature is not None:
            payload[TEMPERATURE_DP] = to_raw(changes.color_temperature)
    elif mode is WorkMode.COLOR and (
        changes.color_hsv is not None or changes.brightness is not None
    ):
        # Unknown current colour: fall back to white light rather than a saturated hue.
        hue, saturation, value = decode_colour(dps.get(COLOUR_DP)) or (0, 0, RAW_MAX)
        if changes.color_hsv is not None:
            hue, saturation = changes.color_hsv.hue, to_raw(changes.color_hsv.saturation)
        if changes.brightness is not None:
            value = to_raw(changes.brightness, MIN_BRIGHTNESS)
        payload[COLOUR_DP] = encode_colour(hue, saturation, value)
    return payload


# --- driver -------------------------------------------------------------------------------


class RgbBulb:
    """RGB+CCT bulb. Keeps a DPS cache fed by full reads, partial pushes and writes."""

    type = DeviceType.RGB_BULB

    def __init__(
        self,
        spec: DeviceSpec,
        connect: LinkFactory = connect_tinytuya,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.id = spec.id
        self.name = spec.name
        self.capabilities = self._capabilities(spec)
        self.online = False
        self._spec = spec
        self._connect = connect
        self._link: TuyaLink | None = None
        self._dps: dict[str, Any] = {}
        self._clock = clock
        self._synced_at = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def matches(spec: DeviceSpec) -> bool:
        return spec.category == CATEGORY and all(
            spec.dps_codes.get(dp) == CODES[dp] for dp in REQUIRED_DPS
        )

    @staticmethod
    def _capabilities(spec: DeviceSpec) -> frozenset[Capability]:
        capabilities = {
            Capability.POWER,
            Capability.WORK_MODE,
            Capability.BRIGHTNESS,
            Capability.COLOR_HSV,
        }
        if spec.dps_codes.get(TEMPERATURE_DP) == CODES[TEMPERATURE_DP]:
            capabilities.add(Capability.COLOR_TEMPERATURE)
        return frozenset(capabilities)

    def read_state(self) -> DeviceState:
        with self._lock:
            self._refresh()
            return state_from_dps(self._dps)

    def apply(self, changes: DeviceState) -> DeviceState:
        changes = changes.restricted_to(self.capabilities)
        with self._lock:
            if not self._has_full_state() or self._clock() - self._synced_at > CACHE_TTL:
                self._refresh()
            payload = build_payload(changes, self._dps)
            if payload:
                echoed = self._io(lambda link: link.set_values(payload))
                # On a persistent socket the reply may be an older queued push rather than
                # the echo of this write, so merge it first and let the payload win.
                self._dps.update(echoed)
                self._dps.update(payload)
            return state_from_dps(self._dps)

    def close(self) -> None:
        with self._lock:
            if self._link is not None:
                self._link.close()
                self._link = None

    def _required_dps(self) -> tuple[str, ...]:
        if Capability.COLOR_TEMPERATURE in self.capabilities:
            return (*REQUIRED_DPS, TEMPERATURE_DP)
        return REQUIRED_DPS

    def _has_full_state(self, dps: dict[str, Any] | None = None) -> bool:
        dps = self._dps if dps is None else dps
        return all(dp in dps for dp in self._required_dps())

    def _refresh(self) -> None:
        """Read the full state; a persistent socket may first return queued partial pushes."""
        for _ in range(READ_ATTEMPTS):
            dps = self._io(lambda link: link.status())
            self._dps.update(dps)
            if self._has_full_state(dps):
                self._synced_at = self._clock()
                return
        if not self._has_full_state():
            raise DeviceError(f"incomplete status after {READ_ATTEMPTS} reads")
        self._synced_at = self._clock()

    def _io(self, operation: Callable[[TuyaLink], dict[str, Any]]) -> dict[str, Any]:
        if self._link is None:
            self._link = self._connect(self._spec)
        try:
            result = operation(self._link)
        except DeviceError:
            # The bulb may have changed meanwhile (reconnect, power cut): forget the cache.
            self.online = False
            self._dps.clear()
            raise
        self.online = True
        return result
