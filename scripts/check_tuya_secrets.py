"""Pre-commit hook: block commits that contain Tuya secrets.

Generic secret scanners cannot recognise a Tuya local key (16 random characters), so this
hook compares staged files against the *real* values found in the local wizard outputs:

1. Rejects any staged file named like a tinytuya wizard output (or a copy of one), a
   HomeDock data file (``config.json``, its ``.corrupt-*`` backups, logs) or ``.env``.
2. Loads device IDs, local keys, IPs, MACs, UUIDs, serial numbers, account IDs, the
   location and cloud credentials from every wizard output in the local secret sources and
   rejects any staged file, text or binary, whose name or content contains one of them: the
   raw bytes are searched in UTF-8 and UTF-16, ignoring case, also JSON-escaped (MACs also
   without separators). A staged file that cannot be read is rejected too.

Secret values are only compared in memory and are never printed. A source file that
exists but cannot be read fails the hook: it would otherwise check nothing.

Secret sources (directories) default to ``%APPDATA%\\HomeDock`` and
``%USERPROFILE%\\tuya-wizard``; override with ``HOMEDOCK_SECRET_SOURCES``
(``os.pathsep``-separated). Missing sources are skipped, so the hook still runs in CI.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

FORBIDDEN_FILENAMES = frozenset(
    {"devices.json", "tuya-raw.json", "snapshot.json", "tinytuya.json", "config.json"}
)
FORBIDDEN_PATTERNS = (
    # copies of wizard outputs: "devices (1).json", "tinytuya.json.bak"...
    *(f"{stem}*.json" for stem in ("devices", "tinytuya", "tuya-raw", "snapshot")),
    *(f"{stem}.json.*" for stem in ("devices", "tinytuya", "tuya-raw", "snapshot")),
    "*.corrupt-*.json",
    "*.log",
    "*.log.[0-9]*",
    ".env",
    ".env.*",
)
ALLOWED_FILENAMES = frozenset({"devices.example.json"})
SOURCE_FILES = ("devices.json", "tinytuya.json", "tuya-raw.json", "snapshot.json")
SECRET_FIELDS = frozenset(
    {
        # device: wizard devices.json, tuya-raw.json results, snapshot.json devices
        "id",
        "key",
        "local_key",
        "ip",
        "last_ip",
        "mac",
        "uuid",
        "sn",
        "node_id",
        "gateway_id",
        # account and home location (tuya-raw.json)
        "uid",
        "owner_id",
        "lat",
        "lon",
        # cloud credentials (tinytuya.json)
        "apiKey",
        "apiSecret",
        "apiDeviceID",
    }
)
MIN_SECRET_LENGTH = 6
ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be")


class SourceError(Exception):
    """A secret source exists but cannot be read, so nothing could be checked."""


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
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        # Parent folder and name only: the full path holds the Windows user name.
        where = f"{path.parent.name}{os.sep}{path.name}"
        raise SourceError(f"cannot read {where} ({type(error).__name__})") from None


def _secret_fields(data: object) -> Iterator[tuple[str, str]]:
    """Every (field, value) of a secret field, at any depth of the document."""
    if isinstance(data, dict):
        for field, value in data.items():
            if field in SECRET_FIELDS and isinstance(value, (str, int, float)):
                if not isinstance(value, bool):
                    yield field, str(value)
            elif isinstance(value, (dict, list)):
                yield from _secret_fields(value)
    elif isinstance(data, list):
        for item in data:
            yield from _secret_fields(item)


def load_secrets(sources: Iterable[Path]) -> dict[str, str]:
    """Return a mapping of secret value -> field name (the kind of secret)."""
    secrets: dict[str, str] = {}
    for source in sources:
        for name in SOURCE_FILES:
            for field, value in _secret_fields(_read_json(source / name)):
                value = value.strip()
                if len(value) >= MIN_SECRET_LENGTH:
                    secrets[value] = field
    return secrets


def _needles(value: str, field: str) -> set[bytes]:
    """The lower-case byte forms of a secret that a staged file might contain."""
    forms = {value.lower()}
    if field == "mac":
        digits = re.sub(r"[^0-9a-f]", "", value.lower())
        pairs = [digits[i : i + 2] for i in range(0, len(digits), 2)]
        forms |= {digits, ":".join(pairs), "-".join(pairs)}
    forms |= {json.dumps(form)[1:-1] for form in forms}  # as written inside a JSON string
    return {form.encode(encoding) for form in forms for encoding in ENCODINGS}


def _forbidden_name(name: str) -> bool:
    name = name.lower()
    if name in ALLOWED_FILENAMES:
        return False
    return name in FORBIDDEN_FILENAMES or any(fnmatch.fnmatch(name, p) for p in FORBIDDEN_PATTERNS)


def find_violations(filenames: Iterable[str], secrets: dict[str, str]) -> list[str]:
    needles = [(field, _needles(value, field)) for value, field in secrets.items()]
    violations = []
    for name in filenames:
        path = Path(name)
        if _forbidden_name(path.name):
            violations.append(f"{name}: wizard output or app data must never be committed")
            continue
        try:
            content = path.read_bytes().lower()
        except OSError as error:
            violations.append(f"{name}: cannot be read ({type(error).__name__}), not checked")
            continue
        content += b"\0" + name.lower().encode("utf-8")  # the name may hold a secret too
        kinds = sorted({field for field, forms in needles if any(f in content for f in forms)})
        if kinds:
            violations.append(f"{name}: contains real Tuya secret(s): {', '.join(kinds)}")
    return violations


def main(argv: list[str] | None = None) -> int:
    filenames = sys.argv[1:] if argv is None else argv
    try:
        secrets = load_secrets(default_sources())
    except SourceError as error:
        print(f"block-tuya-secrets: {error}; fix or move it to check commits", file=sys.stderr)
        return 1
    if not secrets:
        print("block-tuya-secrets: no local secret sources found; only checking file names.")
    violations = find_violations(filenames, secrets)
    for violation in violations:
        print(f"block-tuya-secrets: {violation}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
