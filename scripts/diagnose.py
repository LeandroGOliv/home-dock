"""Diagnostics for the real Tuya bulbs.

Connects to every device in ``%APPDATA%\\HomeDock\\devices.json``, prints the protocol
version that works and every DPS reported, then exercises power, white mode, colour mode
and brightness, and finally restores each bulb to its original state (also on errors and
Ctrl+C).

Device IDs and IPs are masked in the output; local keys are never printed.

Usage::

    uv run python scripts/diagnose.py --dry-run          # read-only
    uv run python scripts/diagnose.py                    # all tests, all bulbs
    uv run python scripts/diagnose.py --only 2 --tests power,white
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PROTOCOL_VERSIONS = ("3.4", "3.3", "3.5", "3.1")
STATE_DPS = ("20", "21", "22", "23", "24")
POWER, MODE, WHITE_BRIGHTNESS, TEMPERATURE, COLOUR = STATE_DPS
POWER_MEMORY, DO_NOT_DISTURB = "33", "34"
ALL_TESTS = ("power", "white", "colour", "colour-brightness", "power-memory")


class DiagnosticError(RuntimeError):
    pass


class TuyaDevice(Protocol):
    def status(self) -> dict[str, Any]: ...
    def set_multiple_values(self, data: dict[str, Any]) -> Any: ...


# --- pure helpers -------------------------------------------------------------------------


def mask(value: object) -> str:
    """Mask an identifier for display: keep the first and last two characters."""
    text = str(value or "")
    if len(text) <= 4:
        return "…" if text else "(empty)"
    return f"{text[:2]}…{text[-2:]}"


def encode_hsv(hue: int, saturation: int, value: int) -> str:
    """Encode HSV as the bulb's ``HHHHSSSSVVVV`` hex string (H 0-360, S/V 0-1000)."""
    if not (0 <= hue <= 360 and 0 <= saturation <= 1000 and 0 <= value <= 1000):
        raise ValueError(f"HSV out of range: {hue}, {saturation}, {value}")
    return f"{hue:04x}{saturation:04x}{value:04x}"


def decode_hsv(text: str) -> tuple[int, int, int]:
    if len(text) != 12:
        raise ValueError(f"expected 12 hex characters, got {len(text)}")
    return int(text[0:4], 16), int(text[4:8], 16), int(text[8:12], 16)


def load_devices(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DiagnosticError(f"devices file not found: {path}") from exc
    if not isinstance(data, list):
        raise DiagnosticError("devices file must contain a JSON list")
    return [d for d in data if isinstance(d, dict) and d.get("id") and d.get("key")]


def select_devices(devices: list[dict[str, Any]], only: str | None) -> list[dict[str, Any]]:
    """Filter by 1-based index or case-insensitive name substring."""
    if not only:
        return devices
    if only.isdigit():
        index = int(only) - 1
        if not 0 <= index < len(devices):
            raise DiagnosticError(f"--only {only}: there are {len(devices)} devices")
        return [devices[index]]
    chosen = [d for d in devices if only.lower() in str(d.get("name", "")).lower()]
    if not chosen:
        raise DiagnosticError(f"--only {only!r} matched no device")
    return chosen


def parse_tests(text: str) -> list[str]:
    tests = [t.strip() for t in text.split(",") if t.strip()]
    unknown = sorted(set(tests) - set(ALL_TESTS))
    if unknown:
        raise DiagnosticError(f"unknown tests: {', '.join(unknown)}")
    return tests


def dps_code(device: dict[str, Any], dps: str) -> str:
    mapping = device.get("mapping") or {}
    return str((mapping.get(dps) or {}).get("code", "?"))


# --- device session -----------------------------------------------------------------------


@dataclass
class Check:
    test: str
    ok: bool | None  # None = informative only
    detail: str


class Session:
    """Reads and writes DPS on one device, waiting for the bulb to settle after writes."""

    def __init__(
        self,
        device: TuyaDevice,
        settle: float,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ) -> None:
        self.device = device
        self.settle = settle
        self.sleep = sleep
        self.log = log

    def read(self, attempts: int = 3) -> dict[str, Any]:
        """Return the full status; bulbs may answer with a partial push after a write."""
        for _ in range(attempts):
            response = self.device.status()
            if not isinstance(response, dict) or "dps" not in response:
                raise DiagnosticError(f"status failed: {describe_error(response)}")
            dps = {str(k): v for k, v in response["dps"].items()}
            if all(k in dps for k in STATE_DPS):
                return dps
            self.sleep(self.settle)
        raise DiagnosticError(f"partial status after {attempts} attempts: {sorted(dps)}")

    def write(self, values: dict[str, Any], label: str) -> dict[str, Any]:
        self.log(f"    -> {label}: {values}")
        response = self.device.set_multiple_values(values)
        if isinstance(response, dict) and "Err" in response:
            raise DiagnosticError(f"write failed: {describe_error(response)}")
        self.sleep(self.settle)
        return self.read()


def describe_error(response: object) -> str:
    if isinstance(response, dict):
        return f"Err {response.get('Err')}: {response.get('Error')}"
    return repr(response)


def snapshot(dps: dict[str, Any]) -> dict[str, Any]:
    return {k: dps[k] for k in STATE_DPS if k in dps}


def restore(session: Session, original: dict[str, Any]) -> Check:
    """Restore values first, then the mode, then power (power last avoids flashes)."""
    values = {k: original[k] for k in (WHITE_BRIGHTNESS, TEMPERATURE, COLOUR) if k in original}
    if values:
        session.write(values, "restore values")
    if MODE in original:
        session.write({MODE: original[MODE]}, "restore mode")
    if POWER in original:
        session.write({POWER: original[POWER]}, "restore power")
    final = snapshot(session.read())
    diff = {k: (original[k], final.get(k)) for k in original if final.get(k) != original[k]}
    return Check("restore", not diff, "identical to original" if not diff else f"diff: {diff}")


# --- tests --------------------------------------------------------------------------------


def expect(test: str, dps: dict[str, Any], key: str, value: Any, what: str) -> Check:
    got = dps.get(key)
    return Check(test, got == value, f"{what}: sent {value!r}, read {got!r}")


def test_power(session: Session) -> list[Check]:
    before = snapshot(session.read())
    checks = [expect("power", session.write({POWER: False}, "turn off"), POWER, False, "off")]
    after = session.write({POWER: True}, "turn on")
    checks.append(expect("power", after, POWER, True, "on"))
    kept = {k: v for k, v in before.items() if k != POWER}
    changed = {k: (v, after.get(k)) for k, v in kept.items() if after.get(k) != v}
    detail = "DPS 21-24 preserved after off/on" if not changed else f"changed: {changed}"
    checks.append(Check("power", not changed, detail))
    return checks


def test_white(session: Session) -> list[Check]:
    checks = []
    dps = session.write({POWER: True, MODE: "white"}, "white mode")
    checks.append(expect("white", dps, MODE, "white", "mode"))
    for temperature, name in ((0, "warmest"), (1000, "coldest"), (500, "middle")):
        dps = session.write({TEMPERATURE: temperature}, f"temperature {name}")
        checks.append(expect("white", dps, TEMPERATURE, temperature, f"temperature {name}"))
    for brightness in (10, 500, 1000):
        dps = session.write({WHITE_BRIGHTNESS: brightness}, f"white brightness {brightness}")
        checks.append(expect("white", dps, WHITE_BRIGHTNESS, brightness, "white brightness"))
    return checks


def test_colour(session: Session) -> list[Check]:
    checks = []
    dps = session.write({POWER: True, MODE: "colour"}, "colour mode")
    checks.append(expect("colour", dps, MODE, "colour", "mode"))
    for hue, saturation, name in (
        (0, 1000, "red"),
        (120, 1000, "green"),
        (240, 1000, "blue"),
        (30, 300, "pale orange"),
    ):
        value = encode_hsv(hue, saturation, 1000)
        dps = session.write({COLOUR: value}, name)
        checks.append(expect("colour", dps, COLOUR, value, name))
    return checks


def test_colour_brightness(session: Session) -> list[Check]:
    checks = []
    dps = session.write(
        {POWER: True, MODE: "colour", COLOUR: encode_hsv(240, 1000, 1000)}, "blue, full brightness"
    )
    white_before = dps.get(WHITE_BRIGHTNESS)
    for value in (100, 1000):
        sent = encode_hsv(240, 1000, value)
        dps = session.write({COLOUR: sent}, f"colour brightness V={value}")
        checks.append(expect("colour-brightness", dps, COLOUR, sent, f"V={value}"))
    unchanged = dps.get(WHITE_BRIGHTNESS) == white_before
    checks.append(
        Check(
            "colour-brightness",
            unchanged,
            f"DPS 22 {'unchanged' if unchanged else 'changed'} by V "
            f"({white_before!r} -> {dps.get(WHITE_BRIGHTNESS)!r})",
        )
    )
    dps = session.write({WHITE_BRIGHTNESS: 300}, "probe: DPS 22 while in colour mode")
    checks.append(
        Check(
            "colour-brightness",
            None,
            f"after DPS 22=300 in colour mode: mode={dps.get(MODE)!r}, colour={dps.get(COLOUR)!r}",
        )
    )
    return checks


def test_power_memory(session: Session) -> list[Check]:
    dps = session.read()
    return [
        Check("power-memory", None, f"DPS {key} ({name}) = {dps.get(key, 'not reported')!r}")
        for key, name in ((POWER_MEMORY, "power_memory"), (DO_NOT_DISTURB, "do_not_disturb"))
    ]


TEST_FUNCTIONS: dict[str, Callable[[Session], list[Check]]] = {
    "power": test_power,
    "white": test_white,
    "colour": test_colour,
    "colour-brightness": test_colour_brightness,
    "power-memory": test_power_memory,
}


def run_tests(session: Session, tests: Iterable[str]) -> list[Check]:
    """Run the tests and always restore the original state, even on errors or Ctrl+C."""
    original = snapshot(session.read())
    session.log(f"    original state: {original}")
    checks: list[Check] = []
    try:
        for name in tests:
            session.log(f"  [{name}]")
            try:
                checks.extend(TEST_FUNCTIONS[name](session))
            except DiagnosticError as exc:
                checks.append(Check(name, False, str(exc)))
    finally:
        session.log("  [restore]")
        checks.append(restore(session, original))
    return checks


# --- tinytuya wiring ----------------------------------------------------------------------


def connect(entry: dict[str, Any], timeout: float) -> tuple[Any, str, dict[str, Any]]:
    """Try the configured protocol version first, then the others."""
    import tinytuya  # imported lazily so the pure helpers stay importable without it

    if not entry.get("ip"):
        raise DiagnosticError("no IP in devices.json; run `python -m tinytuya scan` at home")
    configured = str(entry.get("version") or "")
    versions = [configured, *(v for v in PROTOCOL_VERSIONS if v != configured)]
    errors = []
    for version in filter(None, versions):
        device = tinytuya.Device(entry["id"], entry["ip"], entry["key"], version=float(version))
        device.set_socketTimeout(timeout)
        device.set_socketRetryLimit(1)
        # A fresh connection per call returns the full status instead of queued partial pushes.
        device.set_socketPersistent(False)
        response = device.status()
        if isinstance(response, dict) and "dps" in response:
            return device, version, {str(k): v for k, v in response["dps"].items()}
        device.close()
        errors.append(f"v{version}: {describe_error(response)}")
    raise DiagnosticError("could not connect — " + "; ".join(errors))


def diagnose_device(entry: dict[str, Any], args: argparse.Namespace) -> list[Check]:
    print(f"\n=== {entry.get('name', '?')} ===")
    print(
        f"  id {mask(entry.get('id'))} · ip {mask(entry.get('ip'))} · "
        f"category {entry.get('category')} · model {entry.get('model')} · "
        f"version in file {entry.get('version')}"
    )
    try:
        device, version, dps = connect(entry, args.timeout)
    except DiagnosticError as exc:
        print(f"  !! {exc}")
        return [Check("connect", False, str(exc))]
    checks = [
        Check(
            "connect",
            version == str(entry.get("version")),
            f"protocol {version} (file says {entry.get('version')})",
        )
    ]
    print(f"  connected with protocol {version}")
    print("  DPS reported:")
    for key in sorted(dps, key=int):
        print(f"    {key:>3} {dps_code(entry, key):<18} {dps[key]!r}")
    try:
        if not args.dry_run:
            checks += run_tests(Session(device, args.settle), args.tests)
    finally:
        device.close()
    return checks


def print_summary(results: dict[str, list[Check]]) -> None:
    print("\n=== Summary ===")
    for name, checks in results.items():
        print(f"\n{name}")
        for check in checks:
            mark = {True: "PASS", False: "FAIL", None: "INFO"}[check.ok]
            print(f"  {mark}  {check.test:<18} {check.detail}")


def main(argv: list[str] | None = None) -> int:
    default_devices = Path(os.environ.get("APPDATA", "")) / "HomeDock" / "devices.json"
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--devices", type=Path, default=default_devices)
    parser.add_argument("--only", help="1-based index or part of the device name")
    parser.add_argument(
        "--tests",
        default=",".join(ALL_TESTS),
        help=f"comma-separated subset of: {', '.join(ALL_TESTS)}",
    )
    parser.add_argument("--dry-run", action="store_true", help="only connect and read status")
    parser.add_argument("--settle", type=float, default=1.5, help="seconds to wait after writes")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        args.tests = parse_tests(args.tests)
        devices = select_devices(load_devices(args.devices), args.only)
    except DiagnosticError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    results: dict[str, list[Check]] = {}
    try:
        for number, entry in enumerate(devices, start=1):
            results[f"{number}. {entry.get('name', '?')}"] = diagnose_device(entry, args)
    except KeyboardInterrupt:
        print("\ninterrupted (original state restored for the device in progress)")
    print_summary(results)
    failed = any(c.ok is False for checks in results.values() for c in checks)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
