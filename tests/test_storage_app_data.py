import json
import logging
import shutil
from pathlib import Path

import pytest

from homedock.__main__ import main
from homedock.storage import AppPaths, Config, ImportProblem, open_app_data, save_config
from homedock.storage.logs import LOG_FILE

EXAMPLE = Path(__file__).parents[1] / "devices.example.json"
EXAMPLE_ENTRY = json.loads(EXAMPLE.read_text(encoding="utf-8"))[0]


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def all_files(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def test_first_start_creates_the_config_and_the_log(tmp_path):
    paths = AppPaths(tmp_path / "HomeDock")

    data = open_app_data(paths)

    assert data.config == Config()
    assert data.devices.problem is ImportProblem.MISSING
    assert all_files(paths.root) == {"config.json", f"logs/{LOG_FILE}"}


def test_devices_are_imported_and_their_secrets_masked_in_the_log(tmp_path):
    paths = AppPaths(tmp_path / "HomeDock")
    paths.root.mkdir()
    shutil.copy(EXAMPLE, paths.devices_file)

    data = open_app_data(paths)
    [device] = data.devices.catalog.devices
    logging.getLogger("homedock.test").warning("key %s of %s", EXAMPLE_ENTRY["key"], device.id)

    log = (paths.logs_dir / LOG_FILE).read_text(encoding="utf-8")
    assert EXAMPLE_ENTRY["key"] not in log
    assert EXAMPLE_ENTRY["id"] not in log
    assert "imported 1 device(s)" in log


def test_an_existing_config_is_loaded_and_left_untouched(tmp_path):
    paths = AppPaths(tmp_path / "HomeDock")
    save_config(paths.config_file, Config(names={"dev-a": "Abajur"}))
    before = paths.config_file.read_bytes()

    data = open_app_data(paths)

    assert data.config.names == {"dev-a": "Abajur"}
    assert data.config_backup is None
    assert paths.config_file.read_bytes() == before


def test_a_corrupt_config_is_backed_up_and_replaced_by_the_defaults(tmp_path):
    paths = AppPaths(tmp_path / "HomeDock")
    paths.root.mkdir()
    paths.config_file.write_text("{oops", encoding="utf-8")

    data = open_app_data(paths)

    assert data.config == Config()
    assert data.config_backup is not None
    assert data.config_backup.read_text(encoding="utf-8") == "{oops"
    assert json.loads(paths.config_file.read_text(encoding="utf-8"))["schema"] == 1


def test_save_persists_and_keeps_the_new_config(tmp_path):
    paths = AppPaths(tmp_path / "HomeDock")
    data = open_app_data(paths)
    data.save(Config(names={"dev-a": "Abajur"}))
    assert data.config.names == {"dev-a": "Abajur"}
    assert open_app_data(paths).config.names == {"dev-a": "Abajur"}


def test_main_writes_only_under_appdata_homedock(tmp_path, monkeypatch, capsys):
    appdata, cwd, home = tmp_path / "appdata", tmp_path / "cwd", tmp_path / "home"
    for folder in (appdata, cwd, home):
        folder.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(cwd)

    assert main() == 0

    assert all_files(appdata) == {"HomeDock/config.json", f"HomeDock/logs/{LOG_FILE}"}
    assert all_files(cwd) == set()
    assert all_files(home) == set()
    assert "HomeDock" in capsys.readouterr().err
