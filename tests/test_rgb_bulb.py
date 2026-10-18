"""RGB bulb driver: DPS payloads per capability and mode, state decoding, caching."""

import pytest

from homedock.devices import Capability, Color, Device, DeviceError, DeviceState, WorkMode
from homedock.devices.rgb_bulb import (
    CACHE_TTL,
    MIN_BRIGHTNESS,
    RgbBulb,
    decode_colour,
    to_percent,
    to_raw,
)
from homedock.devices.spec import DeviceSpec

BULB_CODES = {
    "20": "switch_led",
    "21": "work_mode",
    "22": "bright_value_v2",
    "23": "temp_value_v2",
    "24": "colour_data_v2",
}
# Blue (H 240, S 1000) stored at V 500.
WHITE_DPS = {"20": True, "21": "white", "22": 500, "23": 300, "24": "00f003e801f4"}
COLOUR_DPS = {**WHITE_DPS, "21": "colour"}


def bulb_spec(codes=None, category="dj") -> DeviceSpec:
    return DeviceSpec(
        id="dev-1",
        name="Sala",
        local_key="key-1",
        ip="192.0.2.10",
        version="3.4",
        category=category,
        dps_codes=BULB_CODES if codes is None else codes,
    )


class FakeLink:
    """In-memory Tuya link: answers queued partial pushes first, then the full DPS."""

    def __init__(self, dps, pushes=()):
        self.dps = dict(dps)
        self.pushes = list(pushes)
        self.writes: list[dict] = []
        self.status_calls = 0
        self.fail = False
        self.closed = False

    def status(self):
        self.status_calls += 1
        self._check()
        if self.pushes:
            return dict(self.pushes.pop(0))
        return dict(self.dps)

    def set_values(self, values):
        self._check()
        self.writes.append(dict(values))
        self.dps.update(values)
        return dict(values)

    def close(self):
        self.closed = True

    def _check(self):
        if self.fail:
            raise DeviceError("Err 905: Device Unreachable")


def make_bulb(dps=WHITE_DPS, pushes=(), codes=None) -> tuple[RgbBulb, FakeLink]:
    link = FakeLink(dps, pushes)
    return RgbBulb(bulb_spec(codes), connect=lambda _spec: link), link


def written(dps, changes: DeviceState, codes=None) -> list[dict]:
    bulb, link = make_bulb(dps, codes=codes)
    bulb.apply(changes)
    return link.writes


# --- identity and matching ----------------------------------------------------------------


def test_bulb_satisfies_the_device_protocol():
    bulb, _ = make_bulb()
    assert isinstance(bulb, Device)
    assert (bulb.id, bulb.name) == ("dev-1", "Sala")


def test_full_mapping_exposes_every_light_capability():
    bulb, _ = make_bulb()
    assert bulb.capabilities == frozenset(Capability)


def test_mapping_without_temperature_drops_that_capability():
    codes = {k: v for k, v in BULB_CODES.items() if k != "23"}
    bulb, _ = make_bulb(codes=codes)
    assert Capability.COLOR_TEMPERATURE not in bulb.capabilities


def test_matches_dj_bulbs_with_v2_dps():
    assert RgbBulb.matches(bulb_spec())


@pytest.mark.parametrize(
    "spec",
    [
        bulb_spec(category="kt"),
        bulb_spec(codes={"1": "switch_led", "2": "work_mode", "3": "bright_value"}),
        bulb_spec(codes={}),
    ],
    ids=["other-category", "v1-dps", "no-mapping"],
)
def test_does_not_match_other_devices(spec):
    assert not RgbBulb.matches(spec)


def test_starts_offline_and_does_not_connect_on_creation():
    connections = []
    bulb = RgbBulb(bulb_spec(), connect=lambda spec: connections.append(spec))
    assert bulb.online is False
    assert connections == []


# --- reading state ------------------------------------------------------------------------


def test_reads_white_mode_state():
    bulb, _ = make_bulb(WHITE_DPS)
    assert bulb.read_state() == DeviceState(
        power=True,
        work_mode=WorkMode.WHITE,
        brightness=50,
        color_hsv=Color(240, 100),
        color_temperature=30,
    )
    assert bulb.online is True


def test_reads_colour_mode_brightness_from_the_colour_value():
    bulb, _ = make_bulb({**COLOUR_DPS, "22": 1000, "24": "0078012c0064"})
    state = bulb.read_state()
    assert state.work_mode is WorkMode.COLOR
    assert state.color_hsv == Color(120, 30)
    assert state.brightness == 10


@pytest.mark.parametrize(
    ("raw", "percent"), [(10, 1), (14, 1), (15, 2), (504, 50), (505, 51), (1000, 100)]
)
def test_white_brightness_rounds_half_up(raw, percent):
    bulb, _ = make_bulb({**WHITE_DPS, "22": raw})
    assert bulb.read_state().brightness == percent


@pytest.mark.parametrize(("raw", "percent"), [(0, 0), (1000, 100)])
def test_temperature_maps_to_percent(raw, percent):
    bulb, _ = make_bulb({**WHITE_DPS, "23": raw})
    assert bulb.read_state().color_temperature == percent


@pytest.mark.parametrize("mode", ["scene", "music"])
def test_unsupported_work_mode_leaves_mode_and_brightness_unknown(mode):
    bulb, _ = make_bulb({**WHITE_DPS, "21": mode})
    state = bulb.read_state()
    assert state.work_mode is None
    assert state.brightness is None
    assert state.power is True


def test_malformed_colour_data_leaves_colour_unknown():
    bulb, _ = make_bulb({**COLOUR_DPS, "24": "zz"})
    state = bulb.read_state()
    assert state.color_hsv is None
    assert state.brightness is None


def test_partial_push_is_merged_and_followed_by_a_full_read():
    bulb, link = make_bulb(WHITE_DPS, pushes=[{"20": True}])
    assert bulb.read_state().brightness == 50
    assert link.status_calls == 2


def test_partial_pushes_only_raise_when_state_was_never_read():
    bulb, link = make_bulb(WHITE_DPS, pushes=[{"20": True}] * 3)
    with pytest.raises(DeviceError):
        bulb.read_state()

    link.pushes = []
    bulb.read_state()  # a full read fills the cache
    link.pushes = [{"22": 100}] * 3
    assert bulb.read_state().brightness == 10


def test_read_failure_marks_offline():
    bulb, link = make_bulb()
    bulb.read_state()
    link.fail = True
    with pytest.raises(DeviceError):
        bulb.read_state()
    assert bulb.online is False


# --- power --------------------------------------------------------------------------------


@pytest.mark.parametrize("dps", [WHITE_DPS, COLOUR_DPS], ids=["white", "colour"])
@pytest.mark.parametrize("power", [True, False])
def test_power_sends_only_dps_20(dps, power):
    assert written(dps, DeviceState(power=power)) == [{"20": power}]


# --- white mode ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("percent", "raw"), [(0, 10), (1, 10), (2, 20), (50, 500), (99, 990), (100, 1000)]
)
def test_white_brightness_writes_dps_22_with_minimum_10(percent, raw):
    assert written(WHITE_DPS, DeviceState(brightness=percent)) == [{"22": raw}]


@pytest.mark.parametrize(("percent", "raw"), [(0, 0), (37, 370), (100, 1000)])
def test_white_temperature_writes_dps_23(percent, raw):
    assert written(WHITE_DPS, DeviceState(color_temperature=percent)) == [{"23": raw}]


def test_white_brightness_and_temperature_go_in_one_write():
    changes = DeviceState(power=True, brightness=80, color_temperature=20)
    assert written(WHITE_DPS, changes) == [{"20": True, "22": 800, "23": 200}]


# --- colour mode --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("percent", "value"), [(0, "000a"), (1, "000a"), (50, "01f4"), (100, "03e8")]
)
def test_colour_brightness_changes_only_v_of_dps_24(percent, value):
    assert written(COLOUR_DPS, DeviceState(brightness=percent)) == [{"24": "00f003e8" + value}]


@pytest.mark.parametrize(
    ("color", "hue_sat"),
    [(Color(0, 0), "00000000"), (Color(360, 100), "016803e8"), (Color(30, 55), "001e0226")],
)
def test_colour_hue_and_saturation_keep_the_current_v(color, hue_sat):
    assert written(COLOUR_DPS, DeviceState(color_hsv=color)) == [{"24": hue_sat + "01f4"}]


def test_colour_and_brightness_go_in_one_dps_24():
    changes = DeviceState(color_hsv=Color(120, 100), brightness=100)
    assert written(COLOUR_DPS, changes) == [{"24": "007803e803e8"}]


def test_colour_mode_never_writes_dps_22():
    changes = DeviceState(power=True, brightness=100)
    assert all("22" not in w for w in written(COLOUR_DPS, changes))


# --- mode switching -----------------------------------------------------------------------


def test_work_mode_alone_writes_dps_21():
    assert written(WHITE_DPS, DeviceState(work_mode=WorkMode.COLOR)) == [{"21": "colour"}]
    assert written(COLOUR_DPS, DeviceState(work_mode=WorkMode.WHITE)) == [{"21": "white"}]


def test_colour_in_white_mode_switches_to_colour():
    changes = DeviceState(color_hsv=Color(0, 100))
    assert written(WHITE_DPS, changes) == [{"21": "colour", "24": "000003e801f4"}]


def test_temperature_in_colour_mode_switches_to_white():
    changes = DeviceState(color_temperature=100)
    assert written(COLOUR_DPS, changes) == [{"21": "white", "23": 1000}]


def test_explicit_white_mode_sends_white_brightness():
    changes = DeviceState(work_mode=WorkMode.WHITE, brightness=40)
    assert written(COLOUR_DPS, changes) == [{"21": "white", "22": 400}]


def test_explicit_mode_drops_values_of_the_other_mode():
    changes = DeviceState(
        work_mode=WorkMode.COLOR, brightness=100, color_hsv=Color(60, 100), color_temperature=0
    )
    assert written(WHITE_DPS, changes) == [{"21": "colour", "24": "003c03e803e8"}]


def test_colour_and_temperature_without_mode_keep_the_current_mode():
    changes = DeviceState(color_hsv=Color(60, 100), color_temperature=0)
    assert written(WHITE_DPS, changes) == [{"23": 0}]


def test_scene_mode_ignores_brightness_alone():
    changes = DeviceState(power=True, brightness=50)
    assert written({**WHITE_DPS, "21": "scene"}, changes) == [{"20": True}]


def test_colour_in_scene_mode_switches_to_colour():
    changes = DeviceState(color_hsv=Color(0, 0))
    assert written({**WHITE_DPS, "21": "scene"}, changes) == [
        {"21": "colour", "24": "0000000001f4"}
    ]


# --- apply bookkeeping --------------------------------------------------------------------


def test_unsupported_capabilities_are_skipped():
    codes = {k: v for k, v in BULB_CODES.items() if k != "23"}
    assert written(WHITE_DPS, DeviceState(color_temperature=50), codes=codes) == []


def test_apply_reads_the_state_once_before_the_first_write():
    bulb, link = make_bulb(COLOUR_DPS)
    bulb.apply(DeviceState(brightness=10))
    bulb.apply(DeviceState(brightness=20))
    assert link.status_calls == 1


def test_apply_returns_the_resulting_state_from_the_cache():
    bulb, link = make_bulb(WHITE_DPS)
    state = bulb.apply(DeviceState(color_hsv=Color(0, 100)))
    assert state.work_mode is WorkMode.COLOR
    assert state.color_hsv == Color(0, 100)
    assert state.brightness == 50
    assert link.status_calls == 1


def test_apply_failure_marks_offline():
    bulb, link = make_bulb()
    link.fail = True
    with pytest.raises(DeviceError):
        bulb.apply(DeviceState(power=False))
    assert bulb.online is False


def test_close_closes_the_link():
    bulb, link = make_bulb()
    bulb.read_state()
    bulb.close()
    assert link.closed


# --- review follow-ups: conversions, decoding and cache edges -----------------------------


@pytest.mark.parametrize("percent", range(1, 101))
def test_percent_round_trips_through_raw(percent):
    assert to_percent(to_raw(percent)) == percent
    assert to_percent(to_raw(percent, MIN_BRIGHTNESS)) == percent


def test_zero_brightness_reads_back_as_one_percent():
    assert to_percent(to_raw(0, MIN_BRIGHTNESS)) == 1


@pytest.mark.parametrize(
    "text", ["zzzz03e801f4", "016903e801f4", "000003e903e8", "00f003e801f", None, 42]
)
def test_decode_colour_rejects_malformed_values(text):
    assert decode_colour(text) is None


def test_non_bool_power_is_unknown():
    bulb, _ = make_bulb({**WHITE_DPS, "20": 1})
    assert bulb.read_state().power is None


def test_bool_in_white_brightness_is_not_a_brightness():
    bulb, _ = make_bulb({**WHITE_DPS, "22": True})
    assert bulb.read_state().brightness is None


def test_colour_brightness_with_malformed_colour_data_falls_back_to_white_light():
    assert written({**COLOUR_DPS, "24": "zz"}, DeviceState(brightness=50)) == [
        {"24": "0000000001f4"}
    ]


def test_explicit_same_mode_still_writes_dps_21():
    changes = DeviceState(work_mode=WorkMode.WHITE)
    assert written(WHITE_DPS, changes) == [{"21": "white"}]


def test_two_pushes_then_a_full_read_succeed():
    bulb, link = make_bulb(WHITE_DPS, pushes=[{"20": True}, {"22": 500}])
    assert bulb.read_state().brightness == 50
    assert link.status_calls == 3


def test_status_without_temperature_is_full_when_temperature_is_unmapped():
    codes = {k: v for k, v in BULB_CODES.items() if k != "23"}
    dps = {k: v for k, v in WHITE_DPS.items() if k != "23"}
    bulb, link = make_bulb(dps, codes=codes)
    assert bulb.read_state().color_temperature is None
    assert link.status_calls == 1


def test_payload_wins_over_a_stale_echo():
    bulb, link = make_bulb(WHITE_DPS)
    link.set_values = lambda values: (link.writes.append(values), {"22": 100})[1]
    assert bulb.apply(DeviceState(brightness=50)).brightness == 50


def test_empty_echo_still_updates_the_cache():
    bulb, link = make_bulb(WHITE_DPS)
    link.set_values = lambda values: (link.writes.append(values), {})[1]
    assert bulb.apply(DeviceState(brightness=80)).brightness == 80


def test_apply_after_a_failure_reads_the_state_again():
    bulb, link = make_bulb(WHITE_DPS)
    bulb.read_state()
    link.fail = True
    with pytest.raises(DeviceError):
        bulb.apply(DeviceState(power=False))
    link.fail = False
    link.dps["21"] = "colour"  # changed while unreachable (e.g. by the Tuya app)
    bulb.apply(DeviceState(brightness=100))
    assert link.writes[-1] == {"24": "00f003e803e8"}
    assert link.status_calls == 2


def test_apply_rereads_a_cache_older_than_its_ttl():
    now = [0.0]
    link = FakeLink(WHITE_DPS)
    bulb = RgbBulb(bulb_spec(), connect=lambda _spec: link, clock=lambda: now[0])
    bulb.read_state()
    link.dps["21"] = "colour"  # changed meanwhile by the Tuya app

    now[0] += CACHE_TTL - 1
    bulb.apply(DeviceState(power=True))
    assert link.status_calls == 1

    now[0] += CACHE_TTL + 1
    bulb.apply(DeviceState(brightness=100))
    assert link.status_calls == 2
    assert link.writes[-1] == {"24": "00f003e803e8"}  # not DPS 22: the bulb is in colour


def test_an_off_scene_entry_goes_in_one_write_with_its_mode_and_colour():
    # A scene saved with the bulb off: it stays off and keeps the colour for the next power-on
    # (verified on the PSBAM bulbs, issue #11).
    off_red = DeviceState(
        power=False, work_mode=WorkMode.COLOR, brightness=50, color_hsv=Color(0, 100)
    )
    assert written(WHITE_DPS, off_red) == [{"20": False, "21": "colour", "24": "000003e801f4"}]
