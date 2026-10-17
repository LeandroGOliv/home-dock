"""Tray icon and context menu, driven through a control service with fake devices."""

import threading
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum

import pytest
from PySide6.QtWidgets import QSystemTrayIcon

from executors import ManualExecutor
from homedock.core import ControlService, Scene, Target
from homedock.devices import Capability, DeviceError, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.ui import strings
from homedock.ui.tray import TrayController

BULB = frozenset(Capability)


class OtherType(StrEnum):
    SENSOR = "test_sensor"


def bulb(device_id: str, name: str | None = None, **kwargs) -> FakeDevice:
    return FakeDevice(device_id, name or device_id, DeviceType.RGB_BULB, BULB, **kwargs)


class FakeFlyout:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def toggle(self) -> None:
        self.calls.append("toggle")

    def open(self) -> None:
        self.calls.append("open")


class FakeSettings:
    """Stands in for the persisted "start with Windows" preference."""

    def __init__(self, value: bool = False, fail: bool = False) -> None:
        self.value = value
        self.fail = fail

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        if self.fail:
            raise PermissionError("read-only")
        self.value = value


@pytest.fixture
def executor() -> ManualExecutor:
    return ManualExecutor()


@pytest.fixture
def make_tray(qtbot, executor):
    created = []

    def make(*devices, scenes=(), names=None, settings=None, flyout=None, pool=None):
        service = ControlService(devices, executor=pool or executor, throttle=0)
        settings = settings or FakeSettings()
        tray = TrayController(
            service,
            flyout or FakeFlyout(),
            names=lambda: names or {},
            scenes=lambda: list(scenes),
            start_with_windows=settings.get,
            set_start_with_windows=settings.set,
        )
        created.append((tray, service))
        return tray

    yield make
    for tray, service in created:
        tray.close()
        service.shutdown()


def open_menu(tray: TrayController, executor: ManualExecutor | None = None) -> None:
    tray.menu.aboutToShow.emit()
    if executor is not None:
        executor.run_all()


def labels(tray: TrayController) -> list[str]:
    return [a.text() for a in tray.menu.actions() if not a.isSeparator()]


def action(tray: TrayController, text: str):
    return next(a for a in tray.menu.actions() if a.text() == text)


def device_action(tray: TrayController, device_id: str):
    return tray.device_actions[device_id]


# --- structure ----------------------------------------------------------------------------


def test_menu_lists_the_items_in_the_expected_order(make_tray):
    tray = make_tray(bulb("b1", "Lâmpada 1"), bulb("b2", "Lâmpada 2"))

    assert labels(tray) == [
        "Abrir painel",
        "Ligar todos",
        "Desligar todos",
        "Lâmpada 1",
        "Lâmpada 2",
        "Cenas",
        "Iniciar com o Windows",
        "Sair",
    ]
    assert action(tray, strings.SCENES).menu() is not None
    assert action(tray, strings.START_WITH_WINDOWS).isCheckable()


def test_devices_show_the_display_name_chosen_by_the_user(make_tray):
    tray = make_tray(bulb("b1", "Wizard name"), names={"b1": "Abajur"})

    assert device_action(tray, "b1").text() == "Abajur"


def test_a_renamed_device_shows_its_new_name_when_the_menu_opens(make_tray):
    names = {"b1": "Abajur"}
    tray = make_tray(bulb("b1"), names=names)

    names["b1"] = "Luminária"
    open_menu(tray)

    assert device_action(tray, "b1").text() == "Luminária"


def test_ampersands_in_names_are_shown_literally_not_as_shortcuts(make_tray):
    scene = Scene("s1", "Filme & pipoca", {})
    tray = make_tray(bulb("b1", "Sala & Cozinha"), scenes=[scene])
    open_menu(tray)

    assert device_action(tray, "b1").text() == "Sala && Cozinha"
    [item] = action(tray, strings.SCENES).menu().actions()
    assert item.text() == "Filme && pipoca"


def test_devices_without_power_are_not_listed(make_tray):
    sensor = FakeDevice("s1", "Sensor", OtherType.SENSOR, frozenset())
    tray = make_tray(bulb("b1"), sensor)

    assert set(tray.device_actions) == {"b1"}


def test_without_devices_the_menu_says_so(make_tray):
    tray = make_tray()

    placeholder = action(tray, strings.NO_DEVICES)
    assert not placeholder.isEnabled()
    assert not action(tray, strings.TURN_ALL_ON).isEnabled()
    assert not action(tray, strings.TURN_ALL_OFF).isEnabled()


def test_the_tray_icon_has_an_icon_and_a_tooltip(make_tray):
    tray = make_tray(bulb("b1"))

    assert not tray.tray.icon().isNull()
    assert tray.tray.toolTip() == strings.APP_NAME
    assert tray.tray.contextMenu() is tray.menu


# --- device state ---------------------------------------------------------------------------


def test_opening_the_menu_reads_the_real_state_of_every_device(make_tray, executor):
    on = bulb("b1", state=DeviceState(power=True))
    off = bulb("b2", state=DeviceState(power=False))
    tray = make_tray(on, off)

    open_menu(tray, executor)

    assert device_action(tray, "b1").isChecked()
    assert not device_action(tray, "b2").isChecked()


def test_the_menu_never_waits_for_the_devices(make_tray, executor):
    device = bulb("b1", state=DeviceState(power=True))
    tray = make_tray(device)

    open_menu(tray)  # the read is only queued on the (manual) worker

    assert executor.tasks
    assert not device_action(tray, "b1").isChecked()


def test_an_offline_device_is_labelled_offline_and_back_online_when_it_answers(make_tray, executor):
    device = bulb("b1", "Abajur", online=False)
    tray = make_tray(device)

    open_menu(tray, executor)
    assert device_action(tray, "b1").text() == "Abajur · offline"

    device.online = True
    open_menu(tray, executor)
    assert device_action(tray, "b1").text() == "Abajur"


def test_a_state_change_made_elsewhere_updates_the_menu(make_tray, executor):
    device = bulb("b1", state=DeviceState(power=False))
    tray = make_tray(device)
    open_menu(tray, executor)

    tray.service.send(Target.device("b1"), DeviceState(power=True))
    executor.run_all()

    assert device_action(tray, "b1").isChecked()


# --- commands -------------------------------------------------------------------------------


def test_turn_all_on_reaches_every_device(make_tray, executor):
    devices = [bulb("b1", state=DeviceState(power=False)), bulb("b2", state=DeviceState())]
    tray = make_tray(*devices)

    action(tray, strings.TURN_ALL_ON).trigger()
    executor.run_all()

    assert [d.state.power for d in devices] == [True, True]
    assert all(device_action(tray, d.id).isChecked() for d in devices)


def test_turn_all_off_reaches_every_device(make_tray, executor):
    devices = [bulb("b1", state=DeviceState(power=True)), bulb("b2", state=DeviceState(power=True))]
    tray = make_tray(*devices)

    action(tray, strings.TURN_ALL_OFF).trigger()
    executor.run_all()

    assert [d.state.power for d in devices] == [False, False]


def test_turn_all_on_covers_every_device_type_with_power(make_tray, executor):
    class Fan(StrEnum):
        FAN = "test_fan"

    fan = FakeDevice("f1", "Fan", Fan.FAN, frozenset({Capability.POWER}))
    tray = make_tray(bulb("b1"), fan)

    action(tray, strings.TURN_ALL_ON).trigger()
    executor.run_all()

    assert fan.state.power is True


def test_commands_run_on_workers_not_on_the_ui_thread(make_tray, executor):
    device = bulb("b1")
    tray = make_tray(device)

    action(tray, strings.TURN_ALL_ON).trigger()

    assert device.applied == []
    executor.run_all()
    assert device.applied == [DeviceState(power=True)]


def test_a_device_item_toggles_only_that_device(make_tray, executor):
    first = bulb("b1", state=DeviceState(power=False))
    second = bulb("b2", state=DeviceState(power=False))
    tray = make_tray(first, second)
    open_menu(tray, executor)

    device_action(tray, "b1").trigger()
    executor.run_all()

    assert first.state.power is True
    assert second.applied == []
    assert device_action(tray, "b1").isChecked()

    device_action(tray, "b1").trigger()
    executor.run_all()
    assert first.state.power is False


def test_a_failed_toggle_shows_the_real_state_again(make_tray, executor):
    device = bulb("b1", "Abajur", state=DeviceState(power=False))
    tray = make_tray(device)
    open_menu(tray, executor)
    device.online = False

    device_action(tray, "b1").trigger()
    executor.run_all()

    assert not device_action(tray, "b1").isChecked()
    assert device_action(tray, "b1").text() == "Abajur · offline"


# --- scenes ---------------------------------------------------------------------------------


def test_the_scenes_submenu_lists_and_applies_the_saved_scenes(make_tray, executor):
    device = bulb("b1", state=DeviceState(power=False))
    reading = Scene("s1", "Leitura", {"b1": DeviceState(power=True, brightness=80)})
    tray = make_tray(device, scenes=[reading, Scene("s2", "Filme", {})])
    open_menu(tray)

    submenu = action(tray, strings.SCENES).menu()
    assert [a.text() for a in submenu.actions()] == ["Leitura", "Filme"]

    submenu.actions()[0].trigger()
    executor.run_all()

    assert device.state.power is True
    assert device.state.brightness == 80


def test_the_scenes_submenu_follows_the_saved_scenes(make_tray):
    scenes = [Scene("s1", "Leitura", {})]
    tray = make_tray(bulb("b1"), scenes=scenes)
    open_menu(tray)

    scenes.append(Scene("s2", "Filme", {}))
    open_menu(tray)

    submenu = action(tray, strings.SCENES).menu()
    assert [a.text() for a in submenu.actions()] == ["Leitura", "Filme"]


def test_without_scenes_the_submenu_says_so(make_tray):
    tray = make_tray(bulb("b1"))
    open_menu(tray)

    [placeholder] = action(tray, strings.SCENES).menu().actions()
    assert placeholder.text() == strings.NO_SCENES
    assert not placeholder.isEnabled()


# --- settings, flyout, quit -----------------------------------------------------------------


def test_start_with_windows_shows_and_saves_the_preference(make_tray):
    settings = FakeSettings(value=True)
    tray = make_tray(bulb("b1"), settings=settings)
    item = action(tray, strings.START_WITH_WINDOWS)
    assert item.isChecked()

    item.trigger()

    assert settings.value is False
    assert not item.isChecked()


def test_start_with_windows_reverts_when_saving_fails(make_tray):
    settings = FakeSettings(value=False, fail=True)
    tray = make_tray(bulb("b1"), settings=settings)
    item = action(tray, strings.START_WITH_WINDOWS)

    item.trigger()

    assert not item.isChecked()


def test_left_click_toggles_the_flyout(make_tray):
    flyout = FakeFlyout()
    tray = make_tray(bulb("b1"), flyout=flyout)

    tray.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    tray.tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)

    assert flyout.calls == ["toggle"]


def test_open_panel_opens_the_flyout(make_tray):
    flyout = FakeFlyout()
    tray = make_tray(bulb("b1"), flyout=flyout)

    action(tray, strings.OPEN_PANEL).trigger()

    assert flyout.calls == ["open"]


def test_quit_asks_the_app_to_quit(make_tray, qtbot):
    tray = make_tray(bulb("b1"))

    with qtbot.waitSignal(tray.quit_requested):
        action(tray, strings.QUIT).trigger()


# --- responsiveness ---------------------------------------------------------------------------


class HangingDevice(FakeDevice):
    """Blocks in every I/O call until released, then fails like an unreachable bulb."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.started = threading.Event()
        self.release = threading.Event()

    def read_state(self) -> DeviceState:
        return self._hang()

    def apply(self, changes: DeviceState) -> DeviceState:
        return self._hang()

    def _hang(self) -> DeviceState:
        self.started.set()
        self.release.wait(timeout=10)
        raise DeviceError("timed out")


def test_the_ui_stays_responsive_while_a_bulb_does_not_answer(make_tray, qtbot):
    pool = ThreadPoolExecutor(max_workers=2)
    device = HangingDevice("b1", "Abajur", DeviceType.RGB_BULB, BULB)
    tray = make_tray(device, pool=pool)
    try:
        open_menu(tray)
        assert device.started.wait(timeout=5)

        # The bulb is still hanging, yet the menu keeps working.
        action(tray, strings.TURN_ALL_ON).trigger()
        device_action(tray, "b1").trigger()
        assert not device.release.is_set()

        device.release.set()
        qtbot.waitUntil(lambda: device_action(tray, "b1").text() == "Abajur · offline")
        qtbot.waitUntil(lambda: not device_action(tray, "b1").isChecked())
    finally:
        device.release.set()
        tray.service.shutdown()
        pool.shutdown(wait=True)
