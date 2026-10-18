"""In-memory device for tests and development; never touches the network."""

from __future__ import annotations

from dataclasses import dataclass, field

from homedock.devices.base import Capability, DeviceError, DeviceState, DeviceType


@dataclass
class FakeDevice:
    id: str
    name: str
    type: DeviceType
    capabilities: frozenset[Capability]
    state: DeviceState = field(default_factory=DeviceState)
    online: bool = True
    applied: list[DeviceState] = field(default_factory=list)
    closed: bool = False

    def read_state(self) -> DeviceState:
        self._check_online()
        return self.state

    def apply(self, changes: DeviceState) -> DeviceState:
        self._check_online()
        supported = changes.restricted_to(self.capabilities)
        self.applied.append(supported)
        self.state = self.state.merged(supported)
        return self.state

    def close(self) -> None:
        self.closed = True

    def _check_online(self) -> None:
        if not self.online:
            raise DeviceError(f"{self.name} is offline")
