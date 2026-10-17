"""``config.json``: display names, groups, scenes and settings, with a versioned schema.

The file is written atomically. A file that cannot be read is moved aside
(``config.corrupt-<timestamp>.json``) and the app starts again from the defaults.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from homedock.core import Group, Scene, Target, TargetKind
from homedock.core.naming import clean_name
from homedock.devices import DeviceState
from homedock.storage.files import write_atomic

log = logging.getLogger(__name__)

CURRENT_SCHEMA = 1

Migration = Callable[[dict[str, Any]], dict[str, Any]]
# MIGRATIONS[n] upgrades a schema-n document to schema n + 1.
MIGRATIONS: dict[int, Migration] = {}


class ConfigError(ValueError):
    """The config document is invalid or was written by a newer version of the app."""


@dataclass(frozen=True, slots=True)
class Settings:
    start_with_windows: bool = False
    last_target: Target | None = None


@dataclass(frozen=True, slots=True)
class Config:
    """``names`` maps a device id to the display name chosen by the user."""

    names: Mapping[str, str] = field(default_factory=dict)
    groups: tuple[Group, ...] = ()
    scenes: tuple[Scene, ...] = ()
    settings: Settings = Settings()


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    """``backup`` is where an unreadable file was moved, if that happened."""

    config: Config
    backup: Path | None = None


def load_config(path: Path) -> LoadedConfig:
    """Read the config; never raises. A missing file gives the defaults."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return LoadedConfig(Config())
    except (OSError, ValueError) as error:
        log.error("cannot read the config file: %s", type(error).__name__)
        return LoadedConfig(Config(), _back_up(path))
    try:
        return LoadedConfig(config_from_dict(json.loads(text)))
    except ValueError as error:
        log.error("invalid config file, starting from the defaults: %s", error)
        return LoadedConfig(Config(), _back_up(path))


def save_config(path: Path, config: Config) -> None:
    """Write the config atomically. Raises ``OSError``."""
    write_atomic(path, json.dumps(config_to_dict(config), ensure_ascii=False, indent=2) + "\n")


def _back_up(path: Path) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    count = 1
    while backup.exists():
        count += 1
        backup = path.with_name(f"{path.stem}.corrupt-{stamp}-{count}{path.suffix}")
    try:
        os.replace(path, backup)
    except OSError as error:
        log.error("cannot back up the config file: %s", type(error).__name__)
        return None
    log.warning("config file moved to %s", backup.name)
    return backup


def migrate(
    data: dict[str, Any],
    migrations: Mapping[int, Migration] = MIGRATIONS,
    current: int = CURRENT_SCHEMA,
) -> dict[str, Any]:
    """Upgrade a config document to the ``current`` schema, one version at a time."""
    version = data.get("schema")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ConfigError(f"invalid schema version {version!r}")
    if version > current:
        raise ConfigError(f"schema {version} is newer than {current}")
    while version < current:
        data = migrations[version](data)
        version += 1
        data["schema"] = version
    return data


def config_to_dict(config: Config) -> dict[str, Any]:
    target = config.settings.last_target
    return {
        "schema": CURRENT_SCHEMA,
        "names": dict(config.names),
        "groups": [
            {"id": group.id, "name": group.name, "members": list(group.members)}
            for group in config.groups
        ],
        "scenes": [
            {
                "id": scene.id,
                "name": scene.name,
                "devices": {
                    device_id: state.to_dict() for device_id, state in scene.devices.items()
                },
            }
            for scene in config.scenes
        ],
        "settings": {
            "start_with_windows": config.settings.start_with_windows,
            "last_target": None if target is None else {"kind": target.kind, "key": target.key},
        },
    }


def config_from_dict(data: object) -> Config:
    """Validate and decode a config document (migrating it first). Raises ``ConfigError``."""
    try:
        document = migrate(_mapping(data, "config"))
        return Config(
            names={
                _text(device_id): _name(name)
                for device_id, name in _mapping(document.get("names", {}), "names").items()
            },
            groups=tuple(_group(g) for g in _list(document.get("groups", []), "groups")),
            scenes=tuple(_scene(s) for s in _list(document.get("scenes", []), "scenes")),
            settings=_settings(_mapping(document.get("settings", {}), "settings")),
        )
    except ConfigError:
        raise
    except (ValueError, KeyError) as error:
        raise ConfigError(f"invalid config: {error!r}") from error


def _group(data: object) -> Group:
    group = _mapping(data, "group")
    members = tuple(_text(m) for m in _list(group.get("members", []), "members"))
    return Group(_text(group["id"]), _name(group["name"]), members)


def _scene(data: object) -> Scene:
    scene = _mapping(data, "scene")
    devices = {
        _text(device_id): DeviceState.from_dict(state)
        for device_id, state in _mapping(scene.get("devices", {}), "scene devices").items()
    }
    return Scene(_text(scene["id"]), _name(scene["name"]), devices)


def _settings(data: dict[str, Any]) -> Settings:
    start = data.get("start_with_windows", False)
    if not isinstance(start, bool):
        raise ConfigError("start_with_windows must be a boolean")
    target = data.get("last_target")
    if target is not None:
        target = _mapping(target, "last_target")
        target = Target(TargetKind(target["kind"]), _text(target["key"]))
    return Settings(start_with_windows=start, last_target=target)


def _mapping(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{what} must be an object")
    return value


def _list(value: object, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{what} must be a list")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"expected a non-empty string, got {type(value).__name__}")
    return value


def _name(value: object) -> str:
    return clean_name(_text(value))
