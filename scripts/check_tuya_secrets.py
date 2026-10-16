"""Pre-commit hook: block commits that contain Tuya secrets.

Generic secret scanners cannot recognise a Tuya local key (16 random characters), so this
hook compares staged files against the *real* values found in the local wizard outputs:

1. Rejects any staged file named like a tinytuya wizard output.
2. Loads device IDs, local keys, IPs, MACs, UUIDs, serial numbers and cloud credentials
   from the local secret sources and rejects any staged file that contains one of them.

Secret values are only compared in memory and are never printed.

Secret sources (directories) default to ``%APPDATA%\\HomeDock`` and
``%USERPROFILE%\\tuya-wizard``; override with ``HOMEDOCK_SECRET_SOURCES``
(``os.pathsep``-separated). Missing sources are skipped, so the hook still runs in CI.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

FORBIDDEN_FILENAMES = frozenset({"devices.json", "tuya-raw.json", "snapshot.json", "tinytuya.json"})
DEVICE_SECRET_FIELDS = ("id", "key", "local_key", "ip", "mac", "uuid", "sn", "node_id")
CLOUD_SECRET_FIELDS = ("apiKey", "apiSecret", "apiDeviceID")
MIN_SECRET_LENGTH = 6


def default_sources() -> list[Path]:
    override = os.environ.get("HOMEDOCK_SECRET_SOURCES")
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p]
    sources = []
    if appdata := os.environ.get("APPDATA"):
        sources.append(Path(appdata) / "HomeDock")
    sources.append(Path.home() / "tuya-wizard")
    return sources


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _device_secrets(data: object) -> Iterator[tuple[str, str]]:
    if not isinstance(data, list):
        return
    for device in data:
        if not isinstance(device, dict):
            continue
        for field in DEVICE_SECRET_FIELDS:
            value = device.get(field)
            if isinstance(value, str):
                yield field, value


def _cloud_secrets(data: object) -> Iterator[tuple[str, str]]:
    if not isinstance(data, dict):
        return
    for field in CLOUD_SECRET_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            yield field, value


def load_secrets(sources: Iterable[Path]) -> dict[str, str]:
    """Return a mapping of secret value -> field name (the kind of secret)."""
    secrets: dict[str, str] = {}
    for source in sources:
        pairs = [
            *_device_secrets(_read_json(source / "devices.json")),
            *_cloud_secrets(_read_json(source / "tinytuya.json")),
        ]
        for field, value in pairs:
            value = value.strip()
            if len(value) >= MIN_SECRET_LENGTH:
                secrets[value] = field
    return secrets


def find_violations(filenames: Iterable[str], secrets: dict[str, str]) -> list[str]:
    violations = []
    for name in filenames:
        path = Path(name)
        if path.name.lower() in FORBIDDEN_FILENAMES:
            violations.append(f"{name}: tinytuya wizard output must never be committed")
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        kinds = sorted({field for value, field in secrets.items() if value in content})
        if kinds:
            violations.append(f"{name}: contains real Tuya secret(s): {', '.join(kinds)}")
    return violations


def main(argv: list[str] | None = None) -> int:
    filenames = sys.argv[1:] if argv is None else argv
    secrets = load_secrets(default_sources())
    if not secrets:
        print("block-tuya-secrets: no local secret sources found; only checking file names.")
    violations = find_violations(filenames, secrets)
    for violation in violations:
        print(f"block-tuya-secrets: {violation}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
