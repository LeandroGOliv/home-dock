import json

import pytest

from homedock.core import Group, Scene, Target
from homedock.devices import Color, DeviceState, DeviceType, WorkMode
from homedock.storage.config import (
    CURRENT_SCHEMA,
    Config,
    ConfigError,
    Settings,
    config_from_dict,
    config_to_dict,
    load_config,
    migrate,
    save_config,
)

CONFIG = Config(
    names={"dev-a": "Abajur", "dev-b": "Lâmpada da sala"},
    groups=(Group("g-1", "Sala", ("dev-a", "dev-b")), Group("g-2", "Quarto")),
    scenes=(
        Scene(
            "s-1",
            "Leitura",
            {
                "dev-a": DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=80),
                "dev-b": DeviceState(power=True, color_hsv=Color(300, 50), brightness=40),
            },
        ),
    ),
    settings=Settings(start_with_windows=True, last_target=Target.group("g-1")),
)


def test_the_default_config_is_empty():
    config = Config()
    assert (config.names, config.groups, config.scenes) == ({}, (), ())
    assert config.settings == Settings(start_with_windows=False, last_target=None)


def test_the_file_format_is_versioned_json():
    data = config_to_dict(CONFIG)
    assert data == {
        "schema": CURRENT_SCHEMA,
        "names": {"dev-a": "Abajur", "dev-b": "Lâmpada da sala"},
        "groups": [
            {"id": "g-1", "name": "Sala", "members": ["dev-a", "dev-b"]},
            {"id": "g-2", "name": "Quarto", "members": []},
        ],
        "scenes": [
            {
                "id": "s-1",
                "name": "Leitura",
                "devices": {
                    "dev-a": {"power": True, "work_mode": "white", "brightness": 80},
                    "dev-b": {
                        "power": True,
                        "brightness": 40,
                        "color_hsv": {"hue": 300, "saturation": 50},
                    },
                },
            }
        ],
        "settings": {
            "start_with_windows": True,
            "last_target": {"kind": "group", "key": "g-1"},
        },
    }
    assert CURRENT_SCHEMA == 1


@pytest.mark.parametrize(
    "config",
    [
        Config(),
        CONFIG,
        Config(settings=Settings(last_target=Target.all_of(DeviceType.RGB_BULB))),
    ],
)
def test_dict_round_trip(config):
    assert config_from_dict(json.loads(json.dumps(config_to_dict(config)))) == config


def test_missing_sections_take_their_defaults():
    assert config_from_dict({"schema": 1}) == Config()


def test_unknown_keys_are_ignored():
    assert config_from_dict({"schema": 1, "future": {"x": 1}}) == Config()


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"schema": "1"},
        {"schema": True},
        {"schema": 0},
        {"schema": CURRENT_SCHEMA + 1},
        {"schema": 1, "names": ["Abajur"]},
        {"schema": 1, "names": {"dev-a": 3}},
        {"schema": 1, "names": {"dev-a": "  "}},
        {"schema": 1, "groups": {"id": "g-1"}},
        {"schema": 1, "groups": [{"id": "g-1", "members": []}]},
        {"schema": 1, "groups": [{"id": "g-1", "name": "Sala", "members": "dev-a"}]},
        {"schema": 1, "groups": [{"id": 7, "name": "Sala", "members": []}]},
        {"schema": 1, "scenes": [{"id": "s-1", "name": "Leitura", "devices": []}]},
        {"schema": 1, "scenes": [{"id": "s-1", "name": "L", "devices": {"d": {"power": 1}}}]},
        {"schema": 1, "settings": {"start_with_windows": "yes"}},
        {"schema": 1, "settings": {"last_target": {"kind": "room", "key": "x"}}},
        {"schema": 1, "settings": {"last_target": "g-1"}},
    ],
)
def test_invalid_data_raises_config_error(data):
    with pytest.raises(ConfigError):
        config_from_dict(data)


def test_migrate_applies_each_step_up_to_the_current_schema():
    migrations = {
        1: lambda d: {**d, "names": {}},
        2: lambda d: {**d, "names": {**d["names"], "dev-a": "Abajur"}},
    }
    data = migrate({"schema": 1}, migrations=migrations, current=3)
    assert data == {"schema": 3, "names": {"dev-a": "Abajur"}}


def test_migrate_leaves_a_current_file_untouched():
    assert migrate({"schema": 2, "x": 1}, migrations={}, current=2) == {"schema": 2, "x": 1}


def test_migrate_rejects_a_newer_schema():
    with pytest.raises(ConfigError):
        migrate({"schema": 3}, migrations={}, current=2)


def test_save_then_load(tmp_path):
    path = tmp_path / "config.json"
    save_config(path, CONFIG)
    loaded = load_config(path)
    assert loaded.config == CONFIG
    assert loaded.backup is None
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == CURRENT_SCHEMA


def test_the_file_is_readable_utf8(tmp_path):
    path = tmp_path / "config.json"
    save_config(path, CONFIG)
    assert "Lâmpada da sala" in path.read_text(encoding="utf-8")


def test_a_missing_file_loads_the_defaults(tmp_path):
    loaded = load_config(tmp_path / "config.json")
    assert loaded.config == Config()
    assert loaded.backup is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "content",
    ["", "{not json", "[]", '{"schema": 1, "groups": 5}', '{"schema": 99}', "\udcff"],
)
def test_a_corrupt_file_is_backed_up_and_the_defaults_are_used(tmp_path, content):
    path = tmp_path / "config.json"
    path.write_bytes(content.encode("utf-8", errors="surrogateescape"))

    loaded = load_config(path)

    assert loaded.config == Config()
    assert loaded.backup is not None
    assert loaded.backup.parent == tmp_path
    assert loaded.backup.name.startswith("config.corrupt-")
    assert loaded.backup.suffix == ".json"
    assert loaded.backup.read_bytes() == content.encode("utf-8", errors="surrogateescape")
    assert not path.exists()


def test_each_corrupt_file_gets_its_own_backup(tmp_path):
    path = tmp_path / "config.json"
    backups = set()
    for content in ("{", "[", "?"):
        path.write_text(content, encoding="utf-8")
        backups.add(load_config(path).backup)
    assert len(backups) == 3
    assert sorted(b.read_text(encoding="utf-8") for b in backups) == ["?", "[", "{"]


def test_a_corrupt_file_that_cannot_be_backed_up_still_loads_the_defaults(tmp_path, monkeypatch):
    import homedock.storage.config as config_module

    path = tmp_path / "config.json"
    path.write_text("{", encoding="utf-8")

    def fail(*_args):
        raise OSError("locked")

    monkeypatch.setattr(config_module.os, "replace", fail)
    loaded = load_config(path)
    assert loaded.config == Config()
    assert loaded.backup is None
