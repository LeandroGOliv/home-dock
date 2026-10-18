import json
import logging
import shutil
from pathlib import Path

from homedock.devices import DeviceError, FoundDevice
from homedock.storage import AppPaths, Config, ImportProblem, open_app_data, save_config
from homedock.storage.logs import LOG_FILE

EXAMPLE = Path(__file__).parents[1] / "devices.example.json"
EXAMPLE_ENTRY = json.loads(EXAMPLE.read_text(encoding="utf-8"))[0]


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


def test_an_invalid_config_never_logs_the_device_ids_it_contains(tmp_path):
    paths = AppPaths(tmp_path / "HomeDock")
    paths.root.mkdir()
    config = {"schema": 1, "scenes": [{"id": "s", "name": "L", "devices": {"d": {"power": "x"}}}]}
    config["scenes"][0]["devices"]["d"]["power"] = EXAMPLE_ENTRY["id"]
    paths.config_file.write_text(json.dumps(config), encoding="utf-8")

    open_app_data(paths)

    log = (paths.logs_dir / LOG_FILE).read_text(encoding="utf-8")
    assert "invalid config file" in log
    assert EXAMPLE_ENTRY["id"] not in log


def test_an_unwritable_config_does_not_stop_the_start_up(tmp_path, monkeypatch):
    import homedock.storage.app_data as app_data_module

    def fail(*_args):
        raise PermissionError("read-only")

    monkeypatch.setattr(app_data_module, "save_config", fail)
    paths = AppPaths(tmp_path / "HomeDock")

    data = open_app_data(paths)

    assert data.config == Config()
    assert "cannot write the config file" in (paths.logs_dir / LOG_FILE).read_text("utf-8")


def test_library_logs_are_masked_too(tmp_path):
    paths = AppPaths(tmp_path / "HomeDock")
    open_app_data(paths)
    logging.getLogger("some.library").warning("connected to 192.0.2.55.")
    log = (paths.logs_dir / LOG_FILE).read_text(encoding="utf-8")
    assert "192.0.2.55" not in log
    assert "19…55." in log


# --- reloading the devices ("Procurar lâmpadas novas") --------------------------------------

NEW_IP = "192.0.2.77"


def opened_with_example(tmp_path: Path, **changes):
    paths = AppPaths(tmp_path / "HomeDock")
    paths.root.mkdir()
    paths.devices_file.write_text(json.dumps([{**EXAMPLE_ENTRY, **changes}]), encoding="utf-8")
    return open_app_data(paths)


def test_reloading_writes_the_ips_found_and_imports_the_file_again(tmp_path):
    data = opened_with_example(tmp_path, ip="")
    stranger = FoundDevice("bf00000000000000new1", "192.0.2.78")

    result = data.reload_devices(lambda: [FoundDevice(EXAMPLE_ENTRY["id"], NEW_IP), stranger])

    assert result.updated_ips == 1
    assert result.not_imported == 1
    assert not result.scan_failed and not result.write_failed
    assert result.devices.problem is None
    assert data.devices is result.devices
    assert json.loads(data.paths.devices_file.read_text(encoding="utf-8"))[0]["ip"] == NEW_IP


def test_a_failed_scan_still_reimports_the_file(tmp_path):
    data = opened_with_example(tmp_path)
    data.paths.devices_file.write_text(json.dumps([EXAMPLE_ENTRY, EXAMPLE_ENTRY]), "utf-8")

    def scan():
        raise DeviceError("network scan failed (OSError)")

    result = data.reload_devices(scan)

    assert result.scan_failed
    assert len(result.devices.catalog.devices) == 2


def test_an_unreadable_file_keeps_the_devices_imported_before(tmp_path):
    data = opened_with_example(tmp_path)
    before = data.devices
    data.paths.devices_file.write_text("{oops", encoding="utf-8")

    result = data.reload_devices(list)

    assert result.devices.problem is ImportProblem.UNREADABLE
    assert data.devices is before


def test_a_file_that_cannot_be_written_is_reported(tmp_path, monkeypatch):
    data = opened_with_example(tmp_path, ip="")

    def refuse(*_args, **_kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr("homedock.storage.devices.write_atomic", refuse)
    result = data.reload_devices(lambda: [FoundDevice(EXAMPLE_ENTRY["id"], NEW_IP)])

    assert result.write_failed
    assert result.updated_ips == 0
    assert result.devices.problem is None


def test_the_ids_and_ips_found_are_masked_in_the_log(tmp_path):
    data = opened_with_example(tmp_path)
    stranger = FoundDevice("bf00000000000000new1", NEW_IP)
    data.reload_devices(lambda: [stranger])
    logging.getLogger("homedock.test").warning("found %s", stranger.id)

    log = (data.paths.logs_dir / LOG_FILE).read_text(encoding="utf-8")
    assert stranger.id not in log
    assert NEW_IP not in log
