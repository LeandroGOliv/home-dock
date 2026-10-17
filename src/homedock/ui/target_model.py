"""What the target selector shows: one entry per target, from the control service cache.

Generic: every device type gets an automatic group ("Todas as lâmpadas") and a section of
its own, worded by :func:`homedock.ui.strings.noun`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from homedock.core import ControlService, Group, Target
from homedock.devices import Capability, Device
from homedock.ui import strings


@dataclass(frozen=True, slots=True)
class TargetEntry:
    target: Target
    title: str
    subtitle: str  # under the title in the selector header
    detail: str  # right-hand side of the row in the list
    on: bool  # some reachable member is on
    can_power: bool  # some member can be switched on/off
    online: bool | None = None  # devices only: outcome of the last I/O, None before any


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    entries: tuple[TargetEntry, ...]


@dataclass(frozen=True, slots=True)
class TargetModel:
    sections: tuple[Section, ...] = ()

    def entries(self) -> list[TargetEntry]:
        return [entry for section in self.sections for entry in section.entries]

    def find(self, target: Target | None) -> TargetEntry | None:
        return next((e for e in self.entries() if e.target == target), None)

    def choose(self, preferred: Target | None) -> Target | None:
        """``preferred`` while it still exists, else the first target (if any)."""
        if self.find(preferred) is not None:
            return preferred
        entries = self.entries()
        return entries[0].target if entries else None


def build_model(service: ControlService, names: Mapping[str, str]) -> TargetModel:
    """``names`` maps a device id to the display name chosen by the user."""
    builder = _Builder(service, names)
    devices = service.devices
    types = list(dict.fromkeys(d.type for d in devices))
    groups = [
        *(builder.automatic(t) for t in types),
        *(builder.group(g) for g in service.groups.all()),
    ]
    sections = [Section(strings.GROUPS, tuple(groups))] if groups else []
    for device_type in types:
        entries = tuple(builder.device(d) for d in devices if d.type == device_type)
        sections.append(Section(strings.noun(device_type).plural, entries))
    return TargetModel(tuple(sections))


class _Builder:
    def __init__(self, service: ControlService, names: Mapping[str, str]) -> None:
        self._service = service
        self._names = names

    def name(self, device: Device) -> str:
        return self._names.get(device.id, device.name)

    def automatic(self, device_type: str) -> TargetEntry:
        target = Target.all_of(device_type)
        members = self._service.members(target)
        title = strings.noun(device_type).everything
        return self._group(target, title, str(len(members)), members)

    def group(self, group: Group) -> TargetEntry:
        target = Target.group(group.id)
        members = self._service.members(target)
        detail = ", ".join(self.name(d) for d in members) or strings.EMPTY_GROUP
        return self._group(target, group.name, detail, members)

    def _group(
        self, target: Target, title: str, detail: str, members: Sequence[Device]
    ) -> TargetEntry:
        known = [o for d in members if (o := self._service.is_online(d.id)) is not None]
        online = sum(known) if known else None
        subtitle = strings.group_summary(len(members), online, self._noun(members))
        return self._entry(target, title, subtitle, detail, members, None)

    def device(self, device: Device) -> TargetEntry:
        online = self._service.is_online(device.id)
        groups = [g.name for g in self._service.groups.groups_of(device.id)]
        subtitle = strings.device_summary(strings.noun(device.type), online)
        detail = strings.device_detail(groups, online)
        target = Target.device(device.id)
        return self._entry(target, self.name(device), subtitle, detail, [device], online)

    def _entry(
        self,
        target: Target,
        title: str,
        subtitle: str,
        detail: str,
        members: Sequence[Device],
        online: bool | None,
    ) -> TargetEntry:
        on = any(self._is_on(d) for d in members)
        can_power = any(Capability.POWER in d.capabilities for d in members)
        return TargetEntry(target, title, subtitle, detail, on, can_power, online)

    def _is_on(self, device: Device) -> bool:
        state = self._service.state(device.id)
        return bool(state and state.power) and self._service.is_online(device.id) is not False

    def _noun(self, members: Sequence[Device]) -> strings.Noun:
        """The members' noun when they share a type (an empty group: when every known
        device does), else the generic one."""
        types = {d.type for d in members or self._service.devices}
        return strings.noun(types.pop() if len(types) == 1 else None)
