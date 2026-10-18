"""RGB bulb panel: Branco | Cor, the dials and the sliders send the right command per mode,
drags do not flood the bulbs and the panel follows the real state of its target."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

from executors import ManualExecutor
from homedock.core import ControlService, Group, GroupBook, Target
from homedock.devices import Capability, Color, DeviceState, DeviceType, WorkMode
from homedock.devices.fake import FakeDevice
from homedock.ui.bridge import ServiceBridge
from homedock.ui.bulb_panel import RgbBulbPanel, shown_state
from homedock.ui.dial_math import hue_to_angle, temperature_to_angle
from homedock.ui.panels import PanelContext, default_panels
from test_rgb_bulb import COLOUR_DPS, WHITE_DPS, make_bulb
from ui_helpers import dial_point, settle, slider_point

BULB = frozenset(Capability)
WHITE = DeviceState(
    power=True,
    work_mode=WorkMode.WHITE,
    brightness=40,
    color_temperature=30,
    color_hsv=Color(200, 60),
)
COLOUR = WHITE.merged(DeviceState(work_mode=WorkMode.COLOR, brightness=70))


def bulb(device_id: str, state: DeviceState = WHITE, **kwargs) -> FakeDevice:
    return FakeDevice(device_id, device_id, DeviceType.RGB_BULB, BULB, state=state, **kwargs)


@pytest.fixture
def executor() -> ManualExecutor:
    return ManualExecutor()


@pytest.fixture
def make_panel(qtbot, executor):
    """A shown panel for ``target`` over ``devices``, after the first read of their state
    (owned by ``parent`` when the test deletes the panel itself)."""
    created = []

    def make(*devices, target=None, groups=(), read=True, parent=None):
        service = ControlService(devices, GroupBook(groups), executor=executor, throttle=0)
        bridge = ServiceBridge(service)
        target = target or Target.device(devices[0].id)
        if read:
            service.refresh(target)
            settle(executor)
        panel = RgbBulbPanel(PanelContext(service, bridge, target), parent)
        if parent is None:
            qtbot.addWidget(panel)
        panel.setFixedWidth(318)  # the flyout's content width
        panel.show()
        created.append((service, bridge))
        return panel

    yield make
    for service, bridge in created:
        bridge.detach()
        service.shutdown()


def click_slider(qtbot, slider, value: int) -> None:
    qtbot.mouseClick(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, value))


def choose_color(qtbot, panel: RgbBulbPanel) -> None:
    qtbot.mouseClick(panel.modes.buttons[1], Qt.MouseButton.LeftButton)


# --- registry ---------------------------------------------------------------------------------


def test_bulb_targets_get_the_rgb_bulb_panel(qtbot, executor):
    devices = [bulb("b1"), bulb("b2")]
    service = ControlService(devices, GroupBook([Group("g1", "Sala", ("b1", "b2"))]))
    bridge = ServiceBridge(service)
    try:
        for target in (Target.device("b1"), Target.group("g1"), Target.all_of("rgb_bulb")):
            panel = default_panels().create(PanelContext(service, bridge, target))
            qtbot.addWidget(panel)
            assert isinstance(panel, RgbBulbPanel)
    finally:
        bridge.detach()
        service.shutdown()


# --- showing the state ------------------------------------------------------------------------


def test_a_bulb_in_white_mode_shows_the_arc_and_the_brightness(make_panel):
    panel = make_panel(bulb("b1", WHITE))

    assert panel.modes.current() is WorkMode.WHITE
    assert panel.arc.isVisible()
    assert not panel.ring.isVisible()
    assert not panel.saturation.isVisible()
    assert panel.arc.value() == 30
    assert panel.brightness.value() == 40


def test_a_bulb_in_colour_mode_shows_the_ring_brightness_and_saturation(make_panel):
    panel = make_panel(bulb("b1", COLOUR))

    assert panel.modes.current() is WorkMode.COLOR
    assert panel.ring.isVisible()
    assert not panel.arc.isVisible()
    assert panel.saturation.isVisible()
    assert (panel.ring.value(), panel.ring.saturation()) == (200, 60)
    assert panel.saturation.value() == 60
    assert panel.brightness.value() == 70


def test_saturation_sits_right_below_brightness(make_panel):
    panel = make_panel(bulb("b1", COLOUR))

    assert panel.saturation.y() > panel.brightness.y() + panel.brightness.height() - 1


def test_switching_modes_keeps_the_panel_height(make_panel, qtbot):
    panel = make_panel(bulb("b1", WHITE))
    white = panel.sizeHint().height()

    choose_color(qtbot, panel)

    assert panel.sizeHint().height() == white  # the flyout does not jump


def test_the_panel_updates_when_the_state_changes_elsewhere(make_panel, executor):
    device = bulb("b1", WHITE)
    panel = make_panel(device)
    service = panel.service

    device.state = COLOUR.merged(DeviceState(brightness=20, color_hsv=Color(120, 90)))
    service.refresh(Target.device("b1"))  # e.g. the flyout reopened after the Tuya app
    settle(executor)

    assert panel.modes.current() is WorkMode.COLOR
    assert panel.ring.isVisible()
    assert (panel.ring.value(), panel.saturation.value(), panel.brightness.value()) == (120, 90, 20)


def test_before_any_answer_the_panel_shows_defaults_then_the_real_state(make_panel, executor):
    panel = make_panel(bulb("b1", COLOUR), read=False)
    assert panel.modes.current() is WorkMode.WHITE

    panel.service.refresh(Target.device("b1"))
    settle(executor)

    assert panel.modes.current() is WorkMode.COLOR


def test_a_group_shows_the_state_of_its_first_online_member(make_panel, executor):
    devices = (bulb("b1", WHITE), bulb("b2", COLOUR), bulb("b3", WHITE))
    sala = [Group("g1", "Sala", ("b1", "b2", "b3"))]
    panel = make_panel(*devices, target=Target.group("g1"), groups=sala)
    assert panel.modes.current() is WorkMode.WHITE  # Lâmpada 1 is shown

    devices[0].online = False  # its last known state stays in the cache
    panel.service.refresh(Target.group("g1"))
    settle(executor)

    assert panel.modes.current() is WorkMode.COLOR
    assert panel.brightness.value() == 70


def test_the_panel_moves_on_when_the_shown_member_goes_offline(make_panel, executor):
    devices = (bulb("b1", WHITE), bulb("b2", COLOUR))
    sala = [Group("g1", "Sala", ("b1", "b2"))]
    panel = make_panel(*devices, target=Target.group("g1"), groups=sala)

    devices[0].online = False
    panel.service.refresh(Target.device("b1"))  # no state change: only "offline" arrives
    settle(executor)

    assert panel.modes.current() is WorkMode.COLOR


def test_shown_state_falls_back_to_the_last_known_state_when_nobody_answers(executor):
    device = bulb("b1", COLOUR)
    service = ControlService([device], executor=executor)
    target = Target.device("b1")
    assert shown_state(service, target) is None

    service.refresh(target)
    executor.run_all()
    device.online = False
    service.refresh(target)
    executor.run_all()

    assert service.is_online("b1") is False
    assert shown_state(service, target) == COLOUR
    service.shutdown()


# --- commands per mode ------------------------------------------------------------------------


def test_the_arc_sends_the_colour_temperature(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)

    angle = temperature_to_angle(80)
    qtbot.mouseClick(panel.arc, Qt.MouseButton.LeftButton, pos=dial_point(panel.arc, angle))
    settle(executor)

    assert device.applied == [DeviceState(color_temperature=panel.arc.value())]
    assert abs(panel.arc.value() - 80) <= 1


def test_brightness_sends_only_the_brightness_in_white_mode(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)

    click_slider(qtbot, panel.brightness.slider, 75)
    settle(executor)

    assert device.applied == [DeviceState(brightness=75)]
    assert panel.brightness.amount.text() == "75%"


def test_choosing_colour_switches_the_bulb_and_shows_the_ring_at_once(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)

    choose_color(qtbot, panel)
    assert panel.ring.isVisible()  # before the bulb answers
    assert panel.saturation.isVisible()
    settle(executor)

    assert device.applied == [DeviceState(work_mode=WorkMode.COLOR)]
    assert panel.modes.current() is WorkMode.COLOR


def test_choosing_white_switches_the_bulb_back(make_panel, executor, qtbot):
    device = bulb("b1", COLOUR)
    panel = make_panel(device)

    qtbot.mouseClick(panel.modes.buttons[0], Qt.MouseButton.LeftButton)
    settle(executor)

    assert device.applied == [DeviceState(work_mode=WorkMode.WHITE)]
    assert panel.arc.isVisible()


def test_the_ring_sends_the_hue_with_the_shown_saturation(make_panel, executor, qtbot):
    device = bulb("b1", COLOUR)
    panel = make_panel(device)

    point = dial_point(panel.ring, hue_to_angle(120))
    qtbot.mouseClick(panel.ring, Qt.MouseButton.LeftButton, pos=point)
    settle(executor)

    assert device.applied == [DeviceState(color_hsv=Color(panel.ring.value(), 60))]
    assert abs(panel.ring.value() - 120) <= 1


def test_saturation_sends_the_shown_hue_and_tints_the_ring(make_panel, executor, qtbot):
    device = bulb("b1", COLOUR)
    panel = make_panel(device)

    click_slider(qtbot, panel.saturation.slider, 25)
    assert panel.ring.saturation() == 25
    settle(executor)

    assert device.applied == [DeviceState(color_hsv=Color(200, 25))]


def test_brightness_sends_only_the_brightness_in_colour_mode(make_panel, executor, qtbot):
    device = bulb("b1", COLOUR)
    panel = make_panel(device)

    click_slider(qtbot, panel.brightness.slider, 30)
    settle(executor)

    assert device.applied == [DeviceState(brightness=30)]


def test_the_brightness_slider_never_goes_below_one_percent(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)

    qtbot.keyClick(panel.brightness.slider, Qt.Key.Key_Home)
    settle(executor)

    assert device.applied == [DeviceState(brightness=1)]


def test_a_group_command_reaches_every_member(make_panel, executor, qtbot):
    devices = (bulb("b1", WHITE), bulb("b2", COLOUR), bulb("b3", WHITE))
    panel = make_panel(
        *devices, target=Target.group("g1"), groups=[Group("g1", "Sala", ("b1", "b2"))]
    )

    click_slider(qtbot, panel.brightness.slider, 55)
    settle(executor)

    assert [d.applied for d in devices] == [[DeviceState(brightness=55)]] * 2 + [[]]


@pytest.mark.parametrize(
    ("missing", "disabled"),
    [
        (Capability.COLOR_TEMPERATURE, {"arc"}),
        (Capability.COLOR_HSV, {"ring", "saturation"}),
        (Capability.WORK_MODE, {"modes"}),
        (Capability.BRIGHTNESS, {"brightness"}),
    ],
)
def test_controls_without_their_capability_are_disabled(make_panel, missing, disabled):
    device = FakeDevice("b1", "b1", DeviceType.RGB_BULB, BULB - {missing}, state=WHITE)
    panel = make_panel(device)

    controls = ("modes", "arc", "ring", "saturation", "brightness")
    assert {c for c in controls if not getattr(panel, c).isEnabled()} == disabled


def test_a_disabled_control_sends_nothing(make_panel, executor, qtbot):
    device = FakeDevice("b1", "b1", DeviceType.RGB_BULB, BULB - {Capability.BRIGHTNESS})
    panel = make_panel(device)

    click_slider(qtbot, panel.brightness.slider, 30)
    settle(executor)

    assert device.applied == []


# --- through the real driver ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dps", "expected"),
    [
        (WHITE_DPS, {"22": 300}),  # white mode: the white brightness
        (COLOUR_DPS, {"24": "00f003e8012c"}),  # colour mode: only the V of the colour
    ],
)
def test_the_same_brightness_slider_drives_each_mode_through_the_driver(
    make_panel, executor, qtbot, dps, expected
):
    device, link = make_bulb(dps)
    panel = make_panel(device)

    click_slider(qtbot, panel.brightness.slider, 30)
    settle(executor)

    assert link.writes == [expected]


def test_each_control_writes_only_the_dps_of_its_mode_through_the_driver(
    make_panel, executor, qtbot
):
    # Writing the white brightness or temperature in colour mode would switch the bulb to
    # white, and the colour in white mode to colour.
    device, link = make_bulb(WHITE_DPS)  # blue stored at V 500
    panel = make_panel(device)

    qtbot.mouseClick(panel.arc, Qt.MouseButton.LeftButton, pos=dial_point(panel.arc, 90))
    settle(executor)
    assert link.writes.pop() == {"23": panel.arc.value() * 10}

    choose_color(qtbot, panel)
    settle(executor)
    assert link.writes.pop() == {"21": "colour"}

    qtbot.mouseClick(panel.ring, Qt.MouseButton.LeftButton, pos=dial_point(panel.ring, 90))
    settle(executor)
    hue = panel.ring.value()
    assert link.writes.pop() == {"24": f"{hue:04x}03e801f4"}  # the hue; S and V kept

    click_slider(qtbot, panel.saturation.slider, 25)
    settle(executor)
    assert link.writes == [{"24": f"{hue:04x}00fa01f4"}]  # the saturation; V kept


# --- drags ------------------------------------------------------------------------------------


def test_a_continuous_drag_does_not_flood_the_bulb(make_panel, executor, qtbot):
    device = bulb("b1", COLOUR)
    panel = make_panel(device)
    ring = panel.ring

    qtbot.mousePress(ring, Qt.MouseButton.LeftButton, pos=dial_point(ring, hue_to_angle(10)))
    for hue in range(20, 200, 5):
        qtbot.mouseMove(ring, dial_point(ring, hue_to_angle(hue)))
    qtbot.mouseRelease(ring, Qt.MouseButton.LeftButton, pos=dial_point(ring, hue_to_angle(200)))
    settle(executor)

    assert device.applied == [DeviceState(color_hsv=Color(ring.value(), 60))]


def test_a_continuous_drag_sends_each_group_member_only_the_latest_value(
    make_panel, executor, qtbot
):
    devices = (bulb("b1", COLOUR), bulb("b2", COLOUR), bulb("b3", COLOUR))
    sala = [Group("g1", "Sala", ("b1", "b2", "b3"))]
    panel = make_panel(*devices, target=Target.group("g1"), groups=sala)
    slider = panel.saturation.slider

    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 90))
    for value in range(89, 10, -1):
        qtbot.mouseMove(slider, slider_point(slider, value))
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 10))
    settle(executor)

    assert [d.applied for d in devices] == [[DeviceState(color_hsv=Color(200, 10))]] * 3


def test_a_drag_while_a_write_runs_sends_only_the_latest_value_next(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)
    slider = panel.brightness.slider

    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 20))
    executor.run_all()  # the first write goes out
    for value in range(21, 60):
        qtbot.mouseMove(slider, slider_point(slider, value))
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=slider_point(slider, 60))
    settle(executor)

    assert device.applied == [DeviceState(brightness=20), DeviceState(brightness=60)]


@pytest.mark.parametrize(
    ("dial", "state", "sent"),
    [
        ("ring", COLOUR, lambda value: DeviceState(color_hsv=Color(value, 60))),
        ("arc", WHITE, lambda value: DeviceState(color_temperature=value)),
    ],
)
def test_a_dial_drag_is_sent_live_not_only_on_release(
    make_panel, executor, qtbot, dial, state, sent
):
    device = bulb("b1", state)
    panel = make_panel(device)
    widget = getattr(panel, dial)

    qtbot.mousePress(
        widget, Qt.MouseButton.LeftButton, pos=dial_point(widget, 240)
    )  # off the marker
    first = widget.value()
    executor.run_all()  # the press is written while the button is still held
    qtbot.mouseMove(widget, dial_point(widget, 60))
    qtbot.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=dial_point(widget, 60))
    settle(executor)

    assert device.applied == [sent(first), sent(widget.value())]


def test_late_answers_do_not_move_the_controls_back(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)
    slider = panel.brightness.slider

    click_slider(qtbot, slider, 30)
    executor.run_all()  # 30 is written; its answer is still on the way to the UI
    click_slider(qtbot, slider, 60)
    QApplication.processEvents()  # the answer for 30 arrives
    assert panel.brightness.value() == 60

    settle(executor)
    assert panel.brightness.value() == 60
    assert device.state.brightness == 60


def test_a_failed_command_shows_the_real_state_again(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)
    device.online = False

    click_slider(qtbot, panel.brightness.slider, 90)
    assert panel.brightness.value() == 90
    settle(executor)

    assert panel.brightness.value() == 40
    assert panel.brightness.amount.text() == "40%"


def test_a_failed_mode_switch_shows_the_real_mode_again(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)
    device.online = False

    choose_color(qtbot, panel)
    settle(executor)

    assert panel.modes.current() is WorkMode.WHITE
    assert panel.arc.isVisible()


def test_commands_run_on_workers_not_on_the_ui_thread(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    panel = make_panel(device)

    click_slider(qtbot, panel.brightness.slider, 75)

    assert device.applied == []
    settle(executor)
    assert device.applied == [DeviceState(brightness=75)]


def test_an_answer_after_the_panel_was_deleted_is_ignored(make_panel, executor, qtbot):
    device = bulb("b1", WHITE)
    window = QWidget()
    qtbot.addWidget(window)
    panel = make_panel(device, parent=window)
    click_slider(qtbot, panel.brightness.slider, 75)

    panel.deleteLater()  # e.g. another target was chosen
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    settle(executor)  # must not touch the deleted widgets

    assert device.state.brightness == 75
