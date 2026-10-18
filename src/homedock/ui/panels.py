"""Control panels by device type: the flyout shows the panel registered for its target.

A new device type brings its own panel and registers it in :func:`default_panels`; the
flyout never knows the concrete panels.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from homedock.core import ControlService, Target
from homedock.devices import DeviceType
from homedock.ui.bridge import ServiceBridge
from homedock.ui.bulb_panel import RgbBulbPanel


@dataclass(frozen=True, slots=True)
class PanelContext:
    """What a panel needs: the target it controls, the service and the UI-thread bridge."""

    service: ControlService
    bridge: ServiceBridge
    target: Target


PanelFactory = Callable[[PanelContext], QWidget]


class PanelRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, PanelFactory] = {}

    def register(self, device_type: str, factory: PanelFactory) -> None:
        self._factories[device_type] = factory

    def create(self, context: PanelContext) -> QWidget | None:
        """The panel for the target's device type, or ``None``: an empty target, a mixed
        group (devices of several types) or a type without a panel get the power button
        only."""
        types = {d.type for d in context.service.members(context.target)}
        if len(types) != 1:
            return None
        factory = self._factories.get(types.pop())
        return factory(context) if factory is not None else None


def default_panels() -> PanelRegistry:
    """The panels of every supported device type."""
    registry = PanelRegistry()
    registry.register(DeviceType.RGB_BULB, RgbBulbPanel)
    return registry
