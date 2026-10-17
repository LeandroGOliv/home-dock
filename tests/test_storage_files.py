import os
from pathlib import Path

import pytest

from homedock.storage.files import AppPaths, write_atomic


def test_paths_live_under_appdata_homedock(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    paths = AppPaths.default()
    assert paths.root == tmp_path / "HomeDock"
    for path in (paths.devices_file, paths.config_file, paths.logs_dir):
        assert paths.root in path.parents


def test_paths_without_appdata_fall_back_to_the_roaming_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert AppPaths.default().root == tmp_path / "AppData" / "Roaming" / "HomeDock"


def test_file_names():
    paths = AppPaths(Path("root"))
    assert paths.devices_file == Path("root", "devices.json")
    assert paths.config_file == Path("root", "config.json")
    assert paths.logs_dir == Path("root", "logs")


def test_write_atomic_creates_the_folder_and_writes_utf8(tmp_path):
    target = tmp_path / "HomeDock" / "config.json"
    write_atomic(target, "Lâmpadas\n")
    assert target.read_bytes() == "Lâmpadas\n".encode()
    assert os.listdir(target.parent) == ["config.json"]


def test_write_atomic_replaces_an_existing_file(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("old", encoding="utf-8")
    write_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_file(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text("old", encoding="utf-8")

    def fail(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        write_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert os.listdir(tmp_path) == ["config.json"]
