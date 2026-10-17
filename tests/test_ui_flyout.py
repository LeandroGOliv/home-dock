"""Flyout: window behaviour, page stack, target selector and power button, with fake devices."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel

from executors import ManualExecutor
from homedock.core import ControlService, Group, GroupBook, Target
from homedock.devices import Capability, DeviceError, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.ui import strings, theme
from homedock.ui.flyout import REOPEN_GUARD, Flyout, ManagePage, PageStack
from homedock.ui.panels import PanelContext, PanelRegistry
from ui_helpers import settle

BULB = frozenset(Capability)
ALL_BULBS = Target.all_of(DeviceType.RGB_BULB)


def bulb(device_id: str, name: str | None = None, **kwargs) -> FakeDevice:
    return FakeDevice(device_id, name or device_id, DeviceType.RGB_BULB, BULB, **kwargs)


class FakeStore:
    """Stands in for the persisted "last target" setting."""

    def __init__(self, value: Target | None = None, fail: bool = False) -> None:
        self.value = value
        self.fail = fail

    def get(self) -> Target | None:
        return self.value

    def set(self, value: Target) -> None:
        if self.fail:
            raise PermissionError("read-only")
        self.value = value


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def executor() -> ManualExecutor:
    return ManualExecutor()


@pytest.fixture
def make_flyout(qtbot, executor):
    created = []

    def make(*devices, groups=(), names=None, store=None, panels=None, clock=None, pool=None):
        service = ControlService(devices, GroupBook(groups), executor=pool or executor, throttle=0)
        store = store or FakeStore()
        flyout = Flyout(
            service,
            names=lambda: names or {},
            last_target=store.get,
            set_last_target=store.set,
            panels=panels,
            clock=clock or FakeClock(),
        )
        qtbot.addWidget(flyout)
        created.append((flyout, service))
        return flyout

    yield make
    for flyout, service in created:
        flyout.shutdown()
        service.shutdown()


@pytest.fixture
def home(make_flyout):
    """The mockup: Sala (Lâmpada 1, 2), Quarto (Lâmpada 3, off)."""

    def make(**kwargs):
        devices = (
            bulb("b1", "Lâmpada 1", state=DeviceState(power=False)),
            bulb("b2", "Lâmpada 2", state=DeviceState(power=False)),
            bulb("b3", "Lâmpada 3", state=DeviceState(power=False)),
        )
        groups = [Group("g1", "Sala", ("b1", "b2")), Group("g2", "Quarto", ("b3",))]
        return make_flyout(*devices, groups=groups, **kwargs), devices

    return make


def header(flyout: Flyout) -> tuple[str, str]:
    button = flyout.main.target_button
    return button.text(), button.subtitle()


def choose(flyout: Flyout, target: Target, qtbot) -> None:
    """Open the list and click the row of ``target``, like the user does."""
    qtbot.mouseClick(flyout.main.target_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(flyout.main.target_list.rows[target], Qt.MouseButton.LeftButton)


def press_power(flyout: Flyout, qtbot) -> None:
    qtbot.mouseClick(flyout.main.power_button, Qt.MouseButton.LeftButton)


def run_one(executor: ManualExecutor) -> None:
    """Let a single queued worker task run: one device answers."""
    future, fn, args, kwargs = executor.tasks.popleft()
    future.set_running_or_notify_cancel()
    future.set_result(fn(*args, **kwargs))


def deactivate(flyout: Flyout) -> None:
    QApplication.sendEvent(flyout, QEvent(QEvent.Type.WindowDeactivate))


# --- window -----------------------------------------------------------------------------------


def test_the_flyout_is_a_frameless_tool_window_360_px_wide(make_flyout):
    flyout = make_flyout(bulb("b1"))
    flyout.open()

    flags = flyout.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.Tool
    assert flyout.width() == theme.WIDTH == 360


def test_the_flyout_toggles_between_shown_and_hidden(make_flyout):
    flyout = make_flyout(bulb("b1"))

    flyout.toggle()
    assert flyout.isVisible()

    flyout.toggle()
    assert not flyout.isVisible()


def test_the_flyout_opens_in_the_tray_corner_of_the_available_area(make_flyout):
    flyout = make_flyout(bulb("b1"))

    flyout.open()
    flyout.open()  # opening twice keeps it open

    assert flyout.isVisible()
    area = flyout.screen().availableGeometry()
    frame = flyout.frameGeometry()
    assert area.contains(frame)
    assert area.right() - frame.right() == theme.MARGIN
    assert area.bottom() - frame.bottom() == theme.MARGIN


def test_the_flyout_grows_upwards_when_the_target_list_opens(make_flyout, qtbot):
    flyout = make_flyout(bulb("b1"))
    flyout.open()
    closed = flyout.frameGeometry()

    qtbot.mouseClick(flyout.main.target_button, Qt.MouseButton.LeftButton)

    opened = flyout.frameGeometry()
    assert opened.height() > closed.height()
    assert opened.bottom() == closed.bottom()


def test_escape_hides_the_flyout(make_flyout, qtbot):
    flyout = make_flyout(bulb("b1"))
    flyout.open()

    qtbot.keyClick(flyout, Qt.Key.Key_Escape)

    assert not flyout.isVisible()


def test_losing_the_focus_hides_the_flyout(make_flyout):
    flyout = make_flyout(bulb("b1"))
    flyout.open()

    deactivate(flyout)

    assert not flyout.isVisible()


def test_the_tray_click_that_took_the_focus_away_does_not_reopen_it(make_flyout):
    clock = FakeClock()
    flyout = make_flyout(bulb("b1"), clock=clock)
    flyout.open()

    deactivate(flyout)  # the click on the tray icon...
    flyout.toggle()  # ...then reaches the tray
    assert not flyout.isVisible()

    clock.now += REOPEN_GUARD + 0.1
    flyout.toggle()
    assert flyout.isVisible()


def test_the_tray_menu_can_open_it_right_after_it_lost_the_focus(make_flyout):
    flyout = make_flyout(bulb("b1"))
    flyout.open()
    deactivate(flyout)

    flyout.open()  # "Abrir painel" always opens

    assert flyout.isVisible()


def test_reopening_shows_the_main_page_with_the_list_closed(make_flyout, qtbot):
    flyout = make_flyout(bulb("b1"))
    flyout.open()
    qtbot.mouseClick(flyout.main.target_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(flyout.main.target_list.manage_link, Qt.MouseButton.LeftButton)
    flyout.hide()

    flyout.open()

    assert flyout.pages.current() is flyout.main
    assert not flyout.main.target_button.isChecked()
    assert not flyout.main.target_list.isVisible()


# --- page stack -------------------------------------------------------------------------------


def test_manage_opens_its_page_and_back_returns(make_flyout, qtbot):
    flyout = make_flyout(bulb("b1"))
    flyout.open()
    qtbot.mouseClick(flyout.main.target_button, Qt.MouseButton.LeftButton)

    qtbot.mouseClick(flyout.main.target_list.manage_link, Qt.MouseButton.LeftButton)

    page = flyout.pages.current()
    assert isinstance(page, ManagePage)
    assert page.isVisible()
    assert not flyout.main.isVisible()

    qtbot.mouseClick(page.back_button, Qt.MouseButton.LeftButton)
    assert flyout.pages.current() is flyout.main
    assert flyout.main.isVisible()


def test_the_page_stack_shows_only_the_top_page_and_keeps_the_base(qtbot):
    base, first, second = QLabel("base"), QLabel("first"), QLabel("second")
    stack = PageStack(base)
    qtbot.addWidget(stack)
    stack.show()

    stack.push(first)
    stack.push(second)
    assert stack.depth() == 3
    assert [w.isVisible() for w in (base, first, second)] == [False, False, True]

    stack.pop()
    assert stack.current() is first
    assert first.isVisible()

    stack.reset()
    stack.pop()  # the base page is never popped
    assert stack.depth() == 1
    assert stack.current() is base
    assert base.isVisible()


# --- target selector --------------------------------------------------------------------------


def test_the_first_target_is_all_bulbs(home):
    flyout, _ = home()
    flyout.open()

    assert flyout.main.target == ALL_BULBS
    assert header(flyout) == ("Todas as lâmpadas", "Grupo · 3 lâmpadas")


def test_the_last_target_is_selected_again(home):
    flyout, _ = home(store=FakeStore(Target.group("g2")))
    flyout.open()

    assert flyout.main.target == Target.group("g2")
    assert header(flyout)[0] == "Quarto"


def test_a_deleted_last_target_falls_back_to_all_bulbs(home):
    flyout, _ = home(store=FakeStore(Target.group("deleted")))
    flyout.open()

    assert flyout.main.target == ALL_BULBS


def test_opening_reads_the_real_state_of_every_device(home, executor):
    flyout, devices = home()
    devices[0].state = DeviceState(power=True)
    devices[2].online = False

    flyout.open()
    settle(executor)

    rows = flyout.main.target_list.rows
    assert rows[Target.device("b1")].entry.on
    assert rows[Target.device("b3")].entry.detail == "Quarto · offline"
    assert header(flyout) == ("Todas as lâmpadas", "Grupo · 2 de 3 online")
    assert flyout.main.power_button.isChecked()


def test_opening_never_waits_for_the_devices(home, executor):
    flyout, devices = home()
    devices[0].state = DeviceState(power=True)

    flyout.open()  # the reads are only queued on the (manual) worker

    assert flyout.isVisible()
    assert executor.tasks
    assert not flyout.main.power_button.isChecked()


def test_every_opening_reads_the_devices_again(make_flyout, executor):
    class CountingDevice(FakeDevice):
        reads = 0

        def read_state(self) -> DeviceState:
            self.reads += 1
            return super().read_state()

    device = CountingDevice("b1", "Abajur", DeviceType.RGB_BULB, BULB)
    flyout = make_flyout(device)

    flyout.open()
    settle(executor)
    flyout.hide()
    flyout.open()
    settle(executor)

    assert device.reads == 2


def test_the_selector_lists_groups_and_devices(home, qtbot):
    flyout, _ = home()
    flyout.open()

    qtbot.mouseClick(flyout.main.target_button, Qt.MouseButton.LeftButton)

    assert flyout.main.target_list.isVisible()
    assert list(flyout.main.target_list.rows) == [
        ALL_BULBS,
        Target.group("g1"),
        Target.group("g2"),
        Target.device("b1"),
        Target.device("b2"),
        Target.device("b3"),
    ]
    assert flyout.main.target_list.rows[ALL_BULBS].is_selected()


def test_choosing_a_target_selects_it_closes_the_list_and_remembers_it(home, qtbot):
    store = FakeStore()
    flyout, _ = home(store=store)
    flyout.open()

    choose(flyout, Target.group("g1"), qtbot)

    assert flyout.main.target == Target.group("g1")
    assert header(flyout) == ("Sala", "Grupo · 2 lâmpadas")
    assert not flyout.main.target_list.isVisible()
    assert not flyout.main.target_button.isChecked()
    assert flyout.main.target_list.rows[Target.group("g1")].is_selected()
    assert store.value == Target.group("g1")


def test_choosing_a_target_reads_its_state(home, executor, qtbot):
    flyout, devices = home()
    flyout.open()
    settle(executor)
    devices[2].state = DeviceState(power=True)  # switched on elsewhere (e.g. the Tuya app)

    choose(flyout, Target.device("b3"), qtbot)
    settle(executor)

    assert flyout.main.power_button.isChecked()
    assert header(flyout) == ("Lâmpada 3", "Lâmpada · online")


def test_a_target_that_cannot_be_saved_is_still_selected(home, qtbot, caplog):
    flyout, _ = home(store=FakeStore(fail=True))
    flyout.open()

    with caplog.at_level(logging.ERROR):
        choose(flyout, Target.group("g2"), qtbot)

    assert flyout.main.target == Target.group("g2")
    assert "PermissionError" in caplog.text


def test_names_and_groups_changed_elsewhere_show_when_the_flyout_opens(make_flyout):
    names = {}
    flyout = make_flyout(bulb("b1", "Wizard"), names=names)
    flyout.open()
    flyout.hide()

    names["b1"] = "Abajur"
    flyout.main.service.groups.create("Sala", ["b1"])
    flyout.open()

    rows = flyout.main.target_list.rows
    assert rows[Target.device("b1")].entry.title == "Abajur"
    assert [r.entry.title for r in rows.values()] == ["Todas as lâmpadas", "Sala", "Abajur"]


def test_a_state_change_made_elsewhere_updates_the_flyout(home, executor):
    flyout, _ = home(store=FakeStore(Target.device("b1")))
    flyout.open()
    settle(executor)
    assert not flyout.main.power_button.isChecked()

    flyout.main.service.send(Target.device("b1"), DeviceState(power=True))
    settle(executor)

    assert flyout.main.power_button.isChecked()
    assert flyout.main.target_list.rows[Target.device("b1")].entry.on


def test_without_devices_the_selector_says_so_and_power_is_disabled(make_flyout):
    flyout = make_flyout()
    flyout.open()

    assert header(flyout) == (strings.NO_DEVICES, "")
    assert not flyout.main.power_button.isEnabled()


# --- power ------------------------------------------------------------------------------------


def test_power_switches_only_the_selected_group(home, executor, qtbot):
    flyout, devices = home(store=FakeStore(Target.group("g1")))
    flyout.open()
    settle(executor)

    press_power(flyout, qtbot)
    settle(executor)

    assert [d.state.power for d in devices] == [True, True, False]
    assert devices[2].applied == []
    assert flyout.main.power_button.isChecked()


def test_power_switches_only_the_selected_device(home, executor, qtbot):
    flyout, devices = home()
    flyout.open()
    settle(executor)
    choose(flyout, Target.device("b2"), qtbot)
    settle(executor)

    press_power(flyout, qtbot)
    settle(executor)

    assert [d.state.power for d in devices] == [False, True, False]
    assert devices[0].applied == devices[2].applied == []


def test_power_on_all_bulbs_reaches_every_bulb(home, executor, qtbot):
    flyout, devices = home()
    flyout.open()
    settle(executor)

    press_power(flyout, qtbot)
    settle(executor)

    assert [d.state.power for d in devices] == [True, True, True]


def test_power_turns_off_a_target_that_is_partly_on(home, executor, qtbot):
    flyout, devices = home(store=FakeStore(Target.group("g1")))
    devices[0].state = DeviceState(power=True)
    flyout.open()
    settle(executor)
    assert flyout.main.power_button.isChecked()

    press_power(flyout, qtbot)
    settle(executor)

    assert [d.state.power for d in devices] == [False, False, False]
    assert not flyout.main.power_button.isChecked()


def test_the_power_button_keeps_the_requested_state_while_members_answer(home, executor, qtbot):
    flyout, devices = home(store=FakeStore(Target.group("g1")))
    devices[0].state = devices[1].state = DeviceState(power=True)
    flyout.open()
    settle(executor)

    press_power(flyout, qtbot)
    run_one(executor)  # Lâmpada 1 is off, Lâmpada 2 still on
    QApplication.processEvents()
    assert not flyout.main.power_button.isChecked()

    settle(executor)
    assert not flyout.main.power_button.isChecked()
    assert [d.state.power for d in devices[:2]] == [False, False]


def test_a_pending_power_command_does_not_hold_the_button_of_another_target(home, executor, qtbot):
    flyout, devices = home(store=FakeStore(Target.device("b1")))
    flyout.open()
    settle(executor)

    press_power(flyout, qtbot)  # b1 on, still pending on the worker
    choose(flyout, Target.device("b2"), qtbot)

    assert not flyout.main.power_button.isChecked()  # b2 is off
    settle(executor)
    assert not flyout.main.power_button.isChecked()
    assert [d.state.power for d in devices] == [True, False, False]


def test_power_commands_run_on_workers_not_on_the_ui_thread(home, executor, qtbot):
    flyout, devices = home()
    flyout.open()
    settle(executor)

    press_power(flyout, qtbot)

    assert devices[0].applied == []
    settle(executor)
    assert devices[0].applied == [DeviceState(power=True)]


def test_a_failed_power_command_shows_the_real_state_again(home, executor, qtbot):
    flyout, devices = home(store=FakeStore(Target.device("b1")))
    devices[0].online = False
    flyout.open()
    settle(executor)

    press_power(flyout, qtbot)  # no state event will follow: only the command's outcome
    assert flyout.main.power_button.isChecked()
    settle(executor)

    assert not flyout.main.power_button.isChecked()
    assert header(flyout) == ("Lâmpada 1", "Lâmpada · offline")


def test_power_is_disabled_for_a_target_without_power(make_flyout):
    flyout = make_flyout(bulb("b1"), groups=[Group("g1", "Cozinha", ())])
    flyout.open()
    assert flyout.main.power_button.isEnabled()

    flyout.main.select(Target.group("g1"))

    assert not flyout.main.power_button.isEnabled()


# --- panels -----------------------------------------------------------------------------------


class BulbPanel(QLabel):
    def __init__(self, context: PanelContext) -> None:
        super().__init__(f"panel for {context.target.key}")
        self.context = context


@pytest.fixture
def panels() -> PanelRegistry:
    registry = PanelRegistry()
    registry.register(DeviceType.RGB_BULB, BulbPanel)
    return registry


def test_the_panel_of_the_target_type_is_shown_below_the_selector(home, panels, qtbot):
    flyout, _ = home(panels=panels)
    flyout.open()

    panel = flyout.main.panel
    assert isinstance(panel, BulbPanel)
    assert panel.context.target == ALL_BULBS
    assert panel.isVisible()


def test_the_panel_follows_the_selected_target(home, panels, qtbot):
    flyout, _ = home(panels=panels)
    flyout.open()

    choose(flyout, Target.device("b2"), qtbot)

    assert flyout.main.panel.context.target == Target.device("b2")
    assert flyout.main.panel.isVisible()


def test_the_list_takes_the_place_of_the_panel_while_open(home, panels, qtbot):
    flyout, _ = home(panels=panels)
    flyout.open()

    qtbot.mouseClick(flyout.main.target_button, Qt.MouseButton.LeftButton)
    assert not flyout.main.panel.isVisible()

    qtbot.mouseClick(flyout.main.target_button, Qt.MouseButton.LeftButton)
    assert flyout.main.panel.isVisible()


def test_reopening_rebuilds_the_panel_when_the_members_changed(make_flyout, panels):
    flyout = make_flyout(bulb("b1"), groups=[Group("g1", "Sala", ())], panels=panels)
    flyout.main.select(Target.group("g1"))
    flyout.open()
    assert flyout.main.panel is None  # an empty group has no panel

    flyout.hide()
    flyout.main.service.groups.set_members("g1", ["b1"])
    flyout.open()

    assert isinstance(flyout.main.panel, BulbPanel)


def test_without_a_registered_panel_only_the_selector_is_shown(home):
    flyout, _ = home()
    flyout.open()

    assert flyout.main.panel is None


# --- responsiveness ---------------------------------------------------------------------------


class HangingDevice(FakeDevice):
    """Blocks in every I/O call until released, then fails like an unreachable bulb."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def read_state(self) -> DeviceState:
        return self._hang()

    def apply(self, changes: DeviceState) -> DeviceState:
        return self._hang()

    def _hang(self) -> DeviceState:
        self.started.set()
        self.release.wait(timeout=30)  # a blocked UI thread would sit out the whole wait
        self.finished.set()
        raise DeviceError("timed out")


def test_opening_and_closing_never_hang_on_an_offline_bulb(make_flyout, qtbot):
    pool = ThreadPoolExecutor(max_workers=2)
    device = HangingDevice("b1", "Abajur", DeviceType.RGB_BULB, BULB)
    flyout = make_flyout(device, pool=pool, store=FakeStore(Target.device("b1")))
    try:
        flyout.open()
        assert device.started.wait(timeout=5)

        # The bulb is still hanging, yet the flyout keeps working.
        flyout.toggle()
        assert not flyout.isVisible()
        flyout.open()
        assert flyout.isVisible()
        press_power(flyout, qtbot)
        choose(flyout, ALL_BULBS, qtbot)
        assert not device.finished.is_set()

        device.release.set()
        qtbot.waitUntil(lambda: header(flyout)[1] == "Grupo · 0 de 1 online")
        qtbot.waitUntil(lambda: not flyout.main.power_button.isChecked())
    finally:
        device.release.set()
        flyout.main.service.shutdown()
        pool.shutdown(wait=True)


def test_answers_arriving_after_shutdown_are_ignored(make_flyout, executor):
    flyout = make_flyout(bulb("b1", state=DeviceState(power=True)))
    flyout.open()  # reads are pending on the (manual) worker

    flyout.shutdown()
    executor.run_all()  # the device answers after the app closed the flyout
    QApplication.processEvents()

    assert not flyout.isVisible()
    assert not flyout.main.power_button.isChecked()
