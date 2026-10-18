"""App start-up: single instance, storage, control service, tray and flyout."""

import contextlib
import json
import threading
import uuid
from concurrent.futures import Future
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication, QMenu

import homedock.ui.app as app_module
from executors import ManualExecutor
from homedock.__main__ import main
from homedock.core import ControlService, GroupBook, Target
from homedock.devices import Capability, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.storage import AppPaths, open_app_data
from homedock.storage.logs import LOG_FILE
from homedock.ui import strings
from homedock.ui.app import HomeDock
from homedock.ui.single_instance import SingleInstance
from ui_helpers import settle


def all_files(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def tray_menus() -> list[QMenu]:
    return [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, QMenu) and any(a.text() == strings.QUIT for a in widget.actions())
    ]


def choose_quit() -> None:
    [menu] = tray_menus()
    next(a for a in menu.actions() if a.text() == strings.QUIT).trigger()


@contextlib.contextmanager
def safety_net(qapp, seconds: float = 5):
    """Quit a hanging event loop instead of hanging the suite; yields whether it fired."""
    fired: list[bool] = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (fired.append(True), qapp.quit()))
    timer.start(int(seconds * 1000))
    try:
        yield fired
    finally:
        timer.stop()


@pytest.fixture
def folders(qapp, tmp_path, monkeypatch):
    # Menus of earlier tests wait for a deferred delete: flush them so only ours is left.
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    appdata, cwd, home = tmp_path / "appdata", tmp_path / "cwd", tmp_path / "home"
    for folder in (appdata, cwd, home):
        folder.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(cwd)
    return appdata, cwd, home


# --- main -----------------------------------------------------------------------------------


def test_main_runs_the_tray_until_quit_is_chosen(qapp, folders):
    quit_chosen = []

    def quit_from_the_menu():
        choose_quit()
        quit_chosen.append(True)

    QTimer.singleShot(0, quit_from_the_menu)
    with safety_net(qapp):
        assert main() == 0
    assert quit_chosen == [True]


def test_main_writes_only_under_appdata_homedock(qapp, folders):
    appdata, cwd, home = folders
    QTimer.singleShot(0, qapp.quit)

    assert main() == 0

    assert all_files(appdata) == {"HomeDock/config.json", f"HomeDock/logs/{LOG_FILE}"}
    assert all_files(cwd) == set()
    assert all_files(home) == set()


def test_a_second_instance_exits_without_touching_anything(qapp, folders):
    appdata, _cwd, _home = folders
    menus = len(tray_menus())
    with SingleInstance.acquire(app_module.INSTANCE_NAME), safety_net(qapp) as fired:
        assert main() == 0
    assert not fired  # returned at once: no event loop was started

    assert all_files(appdata) == set()
    assert len(tray_menus()) == menus  # no second tray menu


def test_the_instance_lock_is_released_on_exit(qapp, folders):
    QTimer.singleShot(0, qapp.quit)
    main()

    with SingleInstance.acquire(app_module.INSTANCE_NAME) as again:
        assert again is not None


# --- HomeDock ---------------------------------------------------------------------------------


@pytest.fixture
def data(tmp_path):
    return open_app_data(AppPaths(tmp_path / f"HomeDock-{uuid.uuid4().hex}"))


@pytest.fixture
def executor():
    return ManualExecutor()


def make_home(data, executor, *devices) -> HomeDock:
    service = ControlService(devices, executor=executor, throttle=0)
    return HomeDock(data, service)


def test_the_tray_uses_the_names_and_scenes_of_the_config(qtbot, data, executor):
    from homedock.core import Scene
    from homedock.storage import Config

    data.save(Config(names={"b1": "Abajur"}, scenes=(Scene("s1", "Leitura", {}),)))
    bulb = FakeDevice("b1", "Wizard", DeviceType.RGB_BULB, frozenset(Capability))
    home = make_home(data, executor, bulb)
    home.tray.menu.aboutToShow.emit()

    assert home.tray.device_actions["b1"].text() == "Abajur"
    scenes = next(a for a in home.tray.menu.actions() if a.text() == strings.SCENES).menu()
    assert [a.text() for a in scenes.actions()] == ["Leitura"]
    home.close()


def test_start_with_windows_is_saved_in_the_config_file(qtbot, data, executor):
    home = make_home(data, executor)
    item = next(a for a in home.tray.menu.actions() if a.text() == strings.START_WITH_WINDOWS)

    item.trigger()

    saved = json.loads(data.paths.config_file.read_text(encoding="utf-8"))
    assert saved["settings"]["start_with_windows"] is True
    assert data.config.settings.start_with_windows is True
    home.close()


def test_start_with_windows_reverts_when_the_config_cannot_be_written(
    qtbot, data, executor, monkeypatch
):
    home = make_home(data, executor)
    item = next(a for a in home.tray.menu.actions() if a.text() == strings.START_WITH_WINDOWS)

    def fail(_config):
        raise PermissionError("read-only")

    monkeypatch.setattr(data, "save", fail)
    item.trigger()

    assert not item.isChecked()
    assert data.config.settings.start_with_windows is False
    home.close()


def test_showing_the_tray_reads_the_state_of_the_devices(qtbot, data, executor):
    bulb = FakeDevice(
        "b1", "Abajur", DeviceType.RGB_BULB, frozenset(Capability), state=DeviceState(power=True)
    )
    home = make_home(data, executor, bulb)

    home.show()
    settle(executor)

    assert home.tray.device_actions["b1"].isChecked()
    home.close()


def test_closing_shuts_the_control_service_down(qtbot, data, executor):
    bulb = FakeDevice("b1", "Abajur", DeviceType.RGB_BULB, frozenset(Capability))
    home = make_home(data, executor, bulb)

    home.close()

    result = home.service.send(Target.device("b1"), DeviceState(power=True)).result(timeout=1)
    assert result.failed == ("b1",)
    assert bulb.applied == []


def test_the_flyout_remembers_the_selected_target_in_the_config_file(qtbot, data, executor):
    bulb = FakeDevice("b1", "Abajur", DeviceType.RGB_BULB, frozenset(Capability))
    home = make_home(data, executor, bulb)
    home.flyout.open()

    home.flyout.main.select(Target.device("b1"))

    saved = json.loads(data.paths.config_file.read_text(encoding="utf-8"))
    assert saved["settings"]["last_target"] == {"kind": "device", "key": "b1"}
    home.close()

    again = make_home(data, executor, bulb)
    again.flyout.open()
    assert again.flyout.main.target == Target.device("b1")
    again.close()


def test_the_flyout_shows_the_names_and_groups_of_the_config(qtbot, data, executor):
    from homedock.core import Group
    from homedock.storage import Config

    data.save(Config(names={"b1": "Abajur"}, groups=(Group("g1", "Sala", ("b1",)),)))
    bulb = FakeDevice("b1", "Wizard", DeviceType.RGB_BULB, frozenset(Capability))
    service = ControlService([bulb], GroupBook(data.config.groups), executor=executor, throttle=0)
    home = HomeDock(data, service)
    home.flyout.open()

    rows = home.flyout.main.target_list.rows
    assert rows[Target.group("g1")].entry.detail == "Abajur"
    assert rows[Target.device("b1")].entry.title == "Abajur"
    home.close()


def tray_scenes(home) -> list[str]:
    home.tray.menu.aboutToShow.emit()
    scenes = next(a for a in home.tray.menu.actions() if a.text() == strings.SCENES).menu()
    return [a.text() for a in scenes.actions()]


def test_scenes_saved_in_the_flyout_persist_and_show_in_the_tray(qtbot, data, executor):
    from homedock.devices import Color, WorkMode

    state = DeviceState(
        power=True,
        work_mode=WorkMode.COLOR,
        brightness=40,
        color_hsv=Color(240, 90),
        color_temperature=30,
    )
    bulb = FakeDevice("b1", "Abajur", DeviceType.RGB_BULB, frozenset(Capability), state=state)
    home = make_home(data, executor, bulb)
    home.flyout.open()
    section = home.flyout.main.scenes

    section.save_link.click()
    section.editor.field.setText("Leitura")
    section.editor.save_button.click()
    settle(executor)

    assert tray_scenes(home) == ["Leitura"]
    home.close()

    again = open_app_data(data.paths)  # the next start
    [saved] = again.config.scenes
    assert saved.name == "Leitura"
    assert saved.devices == {"b1": state}


def test_left_click_on_the_tray_icon_opens_the_flyout(qtbot, data, executor):
    from PySide6.QtWidgets import QSystemTrayIcon

    home = make_home(data, executor)

    home.tray.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    assert home.flyout.isVisible()
    home.close()
    assert not home.flyout.isVisible()


def test_scenes_renamed_or_deleted_in_the_flyout_persist_and_leave_the_tray(qtbot, data, executor):
    from homedock.core import Scene
    from homedock.storage import Config

    data.save(Config(scenes=(Scene("s1", "Leitura", {}), Scene("s2", "Filme", {}))))
    home = make_home(data, executor)
    home.flyout.open()
    section = home.flyout.main.scenes

    section._start_rename(section.strip.scenes()[0])
    section.editor.field.setText("Ler")
    section.editor.save_button.click()
    section._delete(section.strip.scenes()[1])

    assert tray_scenes(home) == ["Ler"]
    home.close()
    assert [s.name for s in open_app_data(data.paths).config.scenes] == ["Ler"]


# --- manage pages -----------------------------------------------------------------------------


EXAMPLE = Path(__file__).parents[1] / "devices.example.json"
EXAMPLE_ENTRY = json.loads(EXAMPLE.read_text(encoding="utf-8"))[0]


def test_renaming_a_bulb_saves_the_config_and_never_touches_devices_json(qtbot, data, executor):
    data.paths.devices_file.write_text(json.dumps([EXAMPLE_ENTRY]), encoding="utf-8")
    before = data.paths.devices_file.read_bytes()
    bulb = FakeDevice("b1", "Wizard", DeviceType.RGB_BULB, frozenset(Capability))
    home = make_home(data, executor, bulb)
    home.flyout.open()
    home.flyout.main.manage_requested.emit()
    row = home.flyout.pages.current().device_rows["b1"]

    row.rename_button.click()
    row.editor.field.setText("Abajur")
    row.editor.save_button.click()
    home.close()

    assert open_app_data(data.paths).config.names == {"b1": "Abajur"}
    assert data.paths.devices_file.read_bytes() == before


def test_groups_edited_in_the_flyout_persist(qtbot, data, executor):
    bulb = FakeDevice("b1", "Abajur", DeviceType.RGB_BULB, frozenset(Capability))
    home = make_home(data, executor, bulb)
    home.flyout.open()
    home.flyout.main.manage_requested.emit()
    home.flyout.pages.current().new_group_link.click()
    page = home.flyout.pages.current()
    page.name_field.setText("Sala")
    page.member_rows[0].setChecked(True)
    page.save_button.click()
    home.close()

    [group] = open_app_data(data.paths).config.groups
    assert (group.name, group.members) == ("Sala", ("b1",))


def test_reloading_the_devices_writes_the_ips_and_controls_the_new_devices(qtbot, tmp_path):
    from homedock.devices import FoundDevice

    paths = AppPaths(tmp_path / "HomeDock")
    paths.root.mkdir()
    paths.devices_file.write_text(json.dumps([{**EXAMPLE_ENTRY, "ip": ""}]), encoding="utf-8")
    data = open_app_data(paths)
    found = [FoundDevice(EXAMPLE_ENTRY["id"], "192.0.2.50", "3.4")]
    ran = []

    def in_background(work):
        ran.append(work)
        return Future()  # the test runs the work itself, as the worker would

    home = HomeDock(data, scan=lambda: found, in_background=in_background)
    old = home.service.devices
    home.flyout.open()
    home.flyout.main.manage_requested.emit()
    home.flyout.pages.current().find_button.click()
    [work] = ran
    result = work()
    home.close()

    assert result.updated_ips == 1
    assert json.loads(paths.devices_file.read_text(encoding="utf-8"))[0]["ip"] == "192.0.2.50"
    [device] = home.service.devices
    assert device.id == EXAMPLE_ENTRY["id"] and device is not old[0]


def test_run_in_thread_runs_the_work_off_the_calling_thread():
    caller = threading.current_thread()
    future = app_module.run_in_thread(threading.current_thread)
    worker = future.result(timeout=5)
    assert worker is not caller
    assert worker.daemon
    failing = app_module.run_in_thread(lambda: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        failing.result(timeout=5)
