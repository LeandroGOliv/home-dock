"""Panel registry: the flyout picks the control panel by the target's device type."""

from enum import StrEnum

import pytest
from PySide6.QtWidgets import QLabel

from executors import ManualExecutor
from homedock.core import ControlService, Group, GroupBook, Target
from homedock.devices import Capability, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.ui.bridge import ServiceBridge
from homedock.ui.panels import PanelContext, PanelRegistry


class Fan(StrEnum):
    FAN = "test_fan"


BULB = FakeDevice("b1", "Lâmpada 1", DeviceType.RGB_BULB, frozenset(Capability))
BULB_2 = FakeDevice("b2", "Lâmpada 2", DeviceType.RGB_BULB, frozenset(Capability))
FAN = FakeDevice("f1", "Ventilador", Fan.FAN, frozenset({Capability.POWER}))


@pytest.fixture
def service(qtbot):
    groups = GroupBook(
        [
            Group("bulbs", "Sala", ("b1", "b2")),
            Group("mixed", "Quarto", ("b1", "f1")),
            Group("empty", "Cozinha", ()),
        ]
    )
    service = ControlService([BULB, BULB_2, FAN], groups, executor=ManualExecutor())
    yield service
    service.shutdown()


@pytest.fixture
def context(service, qtbot):
    bridge = ServiceBridge(service)

    def make(target: Target) -> PanelContext:
        return PanelContext(service, bridge, target)

    yield make
    bridge.detach()


class BulbPanel(QLabel):
    def __init__(self, context: PanelContext) -> None:
        super().__init__("bulb panel")
        self.context = context


@pytest.fixture
def registry() -> PanelRegistry:
    registry = PanelRegistry()
    registry.register(DeviceType.RGB_BULB, BulbPanel)
    return registry


@pytest.mark.parametrize(
    "target",
    [Target.device("b1"), Target.group("bulbs"), Target.all_of(DeviceType.RGB_BULB)],
)
def test_a_target_of_one_type_gets_the_panel_of_that_type(registry, context, qtbot, target):
    panel = registry.create(context(target))
    qtbot.addWidget(panel)

    assert isinstance(panel, BulbPanel)
    assert panel.context.target == target


@pytest.mark.parametrize(
    "target",
    [Target.group("mixed"), Target.group("empty"), Target.device("f1"), Target.group("gone")],
)
def test_mixed_empty_or_unregistered_targets_get_no_panel(registry, context, target):
    assert registry.create(context(target)) is None
