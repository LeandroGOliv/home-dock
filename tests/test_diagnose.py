import json

import pytest

import diagnose
from diagnose import Check, DiagnosticError, Session


class FakeBulb:
    """In-memory bulb that mirrors the DPS it receives."""

    def __init__(self, fail_on=None):
        self.dps = {"20": True, "21": "colour", "22": 800, "23": 200, "24": "000003e803e8"}
        self.fail_on = fail_on
        self.writes = []

    def status(self):
        return {"dps": dict(self.dps)}

    def set_multiple_values(self, data):
        self.writes.append(dict(data))
        self.dps.update({str(k): v for k, v in data.items()})
        return {"dps": dict(data)}


def session_for(bulb):
    return Session(bulb, settle=0, sleep=lambda _: None, log=lambda _: None)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("bf1a2b3c4d5e6f7a8b9c", "bf…9c"), ("192.0.2.10", "19…10"), ("abc", "…"), ("", "(empty)")],
)
def test_mask_hides_the_middle(value, expected):
    assert diagnose.mask(value) == expected


@pytest.mark.parametrize(
    ("hsv", "text"),
    [
        ((0, 1000, 1000), "000003e803e8"),
        ((360, 0, 0), "016800000000"),
        ((240, 500, 10), "00f001f4000a"),
    ],
)
def test_hsv_round_trip(hsv, text):
    assert diagnose.encode_hsv(*hsv) == text
    assert diagnose.decode_hsv(text) == hsv


@pytest.mark.parametrize("hsv", [(361, 0, 0), (0, 1001, 0), (0, 0, -1)])
def test_encode_hsv_rejects_out_of_range(hsv):
    with pytest.raises(ValueError):
        diagnose.encode_hsv(*hsv)


def test_select_devices_by_index_and_name():
    devices = [{"name": "Sala"}, {"name": "Quarto"}]
    assert diagnose.select_devices(devices, "2") == [{"name": "Quarto"}]
    assert diagnose.select_devices(devices, "sal") == [{"name": "Sala"}]
    assert diagnose.select_devices(devices, None) == devices
    with pytest.raises(DiagnosticError):
        diagnose.select_devices(devices, "3")


def test_load_devices_skips_entries_without_credentials(tmp_path):
    path = tmp_path / "devices.json"
    path.write_text(json.dumps([{"id": "x", "key": "y"}, {"id": "only-id"}]), encoding="utf-8")
    assert diagnose.load_devices(path) == [{"id": "x", "key": "y"}]


def test_parse_tests_rejects_unknown_names():
    assert diagnose.parse_tests("power, white") == ["power", "white"]
    with pytest.raises(DiagnosticError):
        diagnose.parse_tests("power,disco")


def test_power_test_passes_when_bulb_keeps_its_state():
    checks = diagnose.test_power(session_for(FakeBulb()))
    assert all(c.ok for c in checks)


def test_power_test_fails_when_bulb_resets_colour_on_power_on():
    class ForgetfulBulb(FakeBulb):
        def set_multiple_values(self, data):
            result = super().set_multiple_values(data)
            if data.get("20") is True:
                self.dps["21"] = "white"
            return result

    checks = diagnose.test_power(session_for(ForgetfulBulb()))
    assert checks[-1].ok is False


def test_power_test_only_sends_dps_20():
    bulb = FakeBulb()
    diagnose.test_power(session_for(bulb))
    assert all(set(write) == {"20"} for write in bulb.writes)


def test_all_tests_pass_and_state_is_restored():
    bulb = FakeBulb()
    original = dict(bulb.dps)
    checks = diagnose.run_tests(session_for(bulb), diagnose.ALL_TESTS)
    assert not [c for c in checks if c.ok is False]
    assert bulb.dps == original
    assert checks[-1] == Check("restore", True, "identical to original")


def test_state_is_restored_when_a_test_errors():
    class FailsOnceBulb(FakeBulb):
        def set_multiple_values(self, data):
            if self.fail_on in data:
                self.fail_on = None
                raise DiagnosticError("boom")
            return super().set_multiple_values(data)

    bulb = FailsOnceBulb(fail_on="23")
    original = dict(bulb.dps)
    checks = diagnose.run_tests(session_for(bulb), ["white"])
    assert any(c.test == "white" and c.ok is False for c in checks)
    assert bulb.dps == original


def test_state_is_restored_on_keyboard_interrupt():
    bulb = FakeBulb()
    original = dict(bulb.dps)
    session = session_for(bulb)

    def interrupted(_session):
        _session.write({"20": False}, "off")
        raise KeyboardInterrupt

    diagnose.TEST_FUNCTIONS["interrupted"] = interrupted
    try:
        with pytest.raises(KeyboardInterrupt):
            diagnose.run_tests(session, ["interrupted"])
    finally:
        del diagnose.TEST_FUNCTIONS["interrupted"]
    assert bulb.dps == original


def test_restore_sets_power_last():
    bulb = FakeBulb()
    original = diagnose.snapshot(bulb.dps)
    bulb.dps.update({"20": False, "21": "white"})
    diagnose.restore(session_for(bulb), original)
    assert bulb.writes[-1] == {"20": True}
    assert bulb.writes[-2] == {"21": "colour"}


def test_failed_status_raises():
    class OfflineBulb(FakeBulb):
        def status(self):
            return {"Error": "Network Error: Device Unreachable", "Err": "905"}

    with pytest.raises(DiagnosticError, match="905"):
        session_for(OfflineBulb()).read()


def test_partial_status_is_retried_until_complete():
    class PushThenFullBulb(FakeBulb):
        calls = 0

        def status(self):
            self.calls += 1
            return {"dps": {"20": True}} if self.calls == 1 else super().status()

    bulb = PushThenFullBulb()
    assert session_for(bulb).read() == bulb.dps
    assert bulb.calls == 2


def test_status_that_stays_partial_raises():
    class PartialBulb(FakeBulb):
        def status(self):
            return {"dps": {"20": True}}

    with pytest.raises(DiagnosticError, match="partial status"):
        session_for(PartialBulb()).read()


def test_missing_ip_hint_keeps_the_scan_out_of_the_repo():
    # `tinytuya scan` writes snapshot.json (IDs, IPs) into the folder it runs in.
    with pytest.raises(DiagnosticError, match=r"tuya-wizard"):
        diagnose.connect({"id": "bf1a2b3c4d5e6f7a8b9c", "key": "fake", "ip": ""}, timeout=1)
