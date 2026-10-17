"""Targets: what the flyout controls — a device, a user group or all devices of a type."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from homedock.core.groups import GroupBook
from homedock.devices import Device


class TargetKind(StrEnum):
    DEVICE = "device"
    GROUP = "group"
    ALL = "all"  # automatic group: every device of one type ("Todas as lâmpadas")


@dataclass(frozen=True, slots=True)
class Target:
    """``key`` is a device id, a group id or a device type, depending on ``kind``."""

    kind: TargetKind
    key: str

    @classmethod
    def device(cls, device_id: str) -> Target:
        return cls(TargetKind.DEVICE, device_id)

    @classmethod
    def group(cls, group_id: str) -> Target:
        return cls(TargetKind.GROUP, group_id)

    @classmethod
    def all_of(cls, device_type: str) -> Target:
        return cls(TargetKind.ALL, str(device_type))


def resolve(target: Target, devices: Sequence[Device], groups: GroupBook) -> list[Device]:
    """The known devices of ``target``; a stale target (deleted group/device) is empty."""
    match target.kind:
        case TargetKind.DEVICE:
            return [d for d in devices if d.id == target.key]
        case TargetKind.GROUP:
            try:
                members = groups.get(target.key).members
            except KeyError:
                return []
            by_id = {d.id: d for d in devices}
            return [by_id[m] for m in members if m in by_id]
        case TargetKind.ALL:
            return [d for d in devices if d.type == target.key]


def available_targets(devices: Sequence[Device], groups: GroupBook) -> list[Target]:
    """Automatic groups (one per device type present), then user groups, then devices."""
    types = dict.fromkeys(d.type for d in devices)
    return [
        *(Target.all_of(t) for t in types),
        *(Target.group(g.id) for g in groups.all()),
        *(Target.device(d.id) for d in devices),
    ]
