from enum import StrEnum

from homedock.core.groups import GroupBook
from homedock.core.targets import Target, TargetKind, available_targets, resolve
from homedock.devices import Capability, DeviceType
from homedock.devices.fake import FakeDevice


class OtherType(StrEnum):
    """A second device type, standing in for a future one (e.g. an air conditioner)."""

    AC = "test_ac"


def bulb(device_id: str) -> FakeDevice:
    return FakeDevice(device_id, device_id, DeviceType.RGB_BULB, frozenset(Capability))


def other(device_id: str) -> FakeDevice:
    return FakeDevice(device_id, device_id, OtherType.AC, frozenset({Capability.POWER}))


def test_target_constructors():
    assert Target.device("dev-a") == Target(TargetKind.DEVICE, "dev-a")
    assert Target.group("g-1") == Target(TargetKind.GROUP, "g-1")
    assert Target.all_of(DeviceType.RGB_BULB) == Target(TargetKind.ALL, "rgb_bulb")


def test_resolve_a_single_device():
    devices = [bulb("dev-a"), bulb("dev-b")]
    assert resolve(Target.device("dev-b"), devices, GroupBook()) == [devices[1]]


def test_resolve_a_group_follows_the_group_order_and_skips_unknown_members():
    devices = [bulb("dev-a"), bulb("dev-b"), other("ac-1")]
    groups = GroupBook()
    sala = groups.create("Sala", ["ac-1", "removed", "dev-a"])
    assert resolve(Target.group(sala.id), devices, groups) == [devices[2], devices[0]]


def test_resolve_all_of_a_type_is_per_device_type():
    devices = [bulb("dev-a"), other("ac-1"), bulb("dev-b")]
    resolved = resolve(Target.all_of(DeviceType.RGB_BULB), devices, GroupBook())
    assert resolved == [devices[0], devices[2]]


def test_stale_targets_resolve_to_nothing():
    devices = [bulb("dev-a")]
    assert resolve(Target.device("gone"), devices, GroupBook()) == []
    assert resolve(Target.group("gone"), devices, GroupBook()) == []


def test_available_targets_lists_automatic_groups_then_user_groups_then_devices():
    devices = [bulb("dev-a"), other("ac-1"), bulb("dev-b")]
    groups = GroupBook()
    sala = groups.create("Sala", ["dev-a"])
    assert available_targets(devices, groups) == [
        Target.all_of(DeviceType.RGB_BULB),
        Target.all_of(OtherType.AC),
        Target.group(sala.id),
        Target.device("dev-a"),
        Target.device("ac-1"),
        Target.device("dev-b"),
    ]


def test_no_automatic_group_without_devices_of_that_type():
    assert available_targets([], GroupBook()) == []
