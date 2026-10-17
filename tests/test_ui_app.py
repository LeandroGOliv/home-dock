"""App start-up: single instance, storage, control service, tray and placeholder flyout."""

import contextlib
import json
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu

import homedock.ui.app as app_module
from executors import ManualExecutor
from homedock.__main__ import main
from homedock.core import ControlService, Target
from homedock.devices import Capability, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.storage import AppPaths, open_app_data
from homedock.storage.logs import LOG_FILE
from homedock.ui import strings
from homedock.ui.app import HomeDock
from homedock.ui.flyout import MARGIN, PlaceholderFlyout
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


# --- placeholder flyout -----------------------------------------------------------------------


def test_the_flyout_toggles_between_shown_and_hidden(qtbot):
    flyout = PlaceholderFlyout()
    qtbot.addWidget(flyout)

    flyout.toggle()
    assert flyout.isVisible()

    flyout.toggle()
    assert not flyout.isVisible()


def test_the_flyout_opens_inside_the_available_screen_area(qtbot):
    flyout = PlaceholderFlyout()
    qtbot.addWidget(flyout)

    flyout.open()
    flyout.open()  # opening twice keeps it open

    assert flyout.isVisible()
    area = flyout.screen().availableGeometry()
    frame = flyout.frameGeometry()
    assert area.contains(frame)
    assert area.right() - frame.right() == MARGIN  # bottom-right corner, above the taskbar
    assert area.bottom() - frame.bottom() == MARGIN
    assert flyout.width() == 360


def test_escape_hides_the_flyout(qtbot):
    flyout = PlaceholderFlyout()
    qtbot.addWidget(flyout)
    flyout.open()

    qtbot.keyClick(flyout, Qt.Key.Key_Escape)

    assert not flyout.isVisible()
