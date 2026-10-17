"""What the target selector shows, built from the control service cache."""

from enum import StrEnum

import pytest

from executors import ManualExecutor
from homedock.core import ControlService, Group, GroupBook, Target
from homedock.devices import Capability, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.ui.target_model import build_model

BULB = frozenset(Capability)


class Fan(StrEnum):
    FAN = "test_fan"


def bulb(device_id: str, name: str, **kwargs) -> FakeDevice:
    return FakeDevice(device_id, name, DeviceType.RGB_BULB, BULB, **kwargs)


@pytest.fixture
def executor() -> ManualExecutor:
    return ManualExecutor()


@pytest.fixture
def make_service(executor):
    created = []

    def make(*devices, groups=()):
        service = ControlService(devices, GroupBook(groups), executor=executor, throttle=0)
        created.append(service)
        return service

    yield make
    for service in created:
        service.shutdown()


def read_all(service: ControlService, executor: ManualExecutor) -> None:
    for device_type in dict.fromkeys(d.type for d in service.devices):
        service.refresh(Target.all_of(device_type))
    executor.run_all()


@pytest.fixture
def home(make_service, executor):
    """The mockup: Sala (Lâmpada 1, 2), Quarto (Lâmpada 3, offline)."""
    service = make_service(
        bulb("b1", "Lâmpada 1", state=DeviceState(power=True)),
        bulb("b2", "Lâmpada 2", state=DeviceState(power=True)),
        bulb("b3", "Lâmpada 3", online=False),
        groups=[Group("g1", "Sala", ("b1", "b2")), Group("g2", "Quarto", ("b3",))],
    )
    read_all(service, executor)
    return service


def titles(section) -> list[str]:
    return [e.title for e in section.entries]


def test_groups_come_first_then_one_section_per_device_type(home):
    model = build_model(home, {})

    groups, bulbs = model.sections
    assert groups.title == "Grupos"
    assert titles(groups) == ["Todas as lâmpadas", "Sala", "Quarto"]
    assert bulbs.title == "Lâmpadas"
    assert titles(bulbs) == ["Lâmpada 1", "Lâmpada 2", "Lâmpada 3"]


def test_the_automatic_group_shows_how_many_devices_it_has(home):
    entry = build_model(home, {}).find(Target.all_of(DeviceType.RGB_BULB))

    assert entry.detail == "3"
    assert entry.subtitle == "Grupo · 2 de 3 online"


def test_a_user_group_lists_its_members_by_display_name(home):
    entry = build_model(home, {"b1": "Abajur"}).find(Target.group("g1"))

    assert entry.detail == "Abajur, Lâmpada 2"
    assert entry.subtitle == "Grupo · 2 de 2 online"


def test_a_group_counts_its_members_until_their_status_is_known(make_service):
    service = make_service(
        bulb("b1", "Lâmpada 1"), bulb("b2", "Lâmpada 2"), groups=[Group("g1", "Sala", ("b1", "b2"))]
    )

    assert build_model(service, {}).find(Target.group("g1")).subtitle == "Grupo · 2 lâmpadas"


def test_a_group_of_one_uses_the_singular(make_service):
    service = make_service(bulb("b1", "Lâmpada 1"), groups=[Group("g1", "Quarto", ("b1",))])

    assert build_model(service, {}).find(Target.group("g1")).subtitle == "Grupo · 1 lâmpada"


def test_an_empty_group_says_so(make_service):
    service = make_service(bulb("b1", "Lâmpada 1"), groups=[Group("g1", "Cozinha", ())])

    entry = build_model(service, {}).find(Target.group("g1"))

    assert entry.detail == "Vazio"
    assert entry.subtitle == "Grupo · 0 lâmpadas"
    assert not entry.can_power


def test_a_device_shows_its_groups_and_whether_it_is_online(home):
    model = build_model(home, {})

    first = model.find(Target.device("b1"))
    assert first.detail == "Sala"
    assert first.subtitle == "Lâmpada · online"
    assert first.online is True

    offline = model.find(Target.device("b3"))
    assert offline.detail == "Quarto · offline"
    assert offline.subtitle == "Lâmpada · offline"
    assert offline.online is False


def test_a_device_in_no_group_shows_only_its_status(make_service, executor):
    service = make_service(bulb("b1", "Lâmpada 1"), bulb("b2", "Lâmpada 2", online=False))
    model = build_model(service, {})
    assert model.find(Target.device("b1")).detail == ""
    assert model.find(Target.device("b1")).subtitle == "Lâmpada"

    read_all(service, executor)
    model = build_model(service, {})
    assert model.find(Target.device("b1")).detail == ""
    assert model.find(Target.device("b2")).detail == "offline"


def test_a_device_belonging_to_many_groups_lists_them_all(make_service):
    service = make_service(
        bulb("b1", "Lâmpada 1"),
        groups=[Group("g1", "Sala", ("b1",)), Group("g2", "Térreo", ("b1",))],
    )

    assert build_model(service, {}).find(Target.device("b1")).detail == "Sala, Térreo"


def test_on_means_some_reachable_member_is_on(make_service, executor):
    service = make_service(
        bulb("b1", "Lâmpada 1", state=DeviceState(power=True)),
        bulb("b2", "Lâmpada 2", state=DeviceState(power=False)),
        groups=[Group("g1", "Sala", ("b1", "b2")), Group("g2", "Quarto", ("b2",))],
    )
    assert not build_model(service, {}).find(Target.group("g1")).on  # nothing read yet

    read_all(service, executor)
    model = build_model(service, {})

    assert model.find(Target.group("g1")).on
    assert not model.find(Target.group("g2")).on
    assert model.find(Target.device("b1")).on
    assert not model.find(Target.device("b2")).on


def test_a_device_that_went_offline_is_not_shown_as_on(make_service, executor):
    device = bulb("b1", "Lâmpada 1", state=DeviceState(power=True))
    service = make_service(device)
    read_all(service, executor)

    device.online = False
    read_all(service, executor)

    assert not build_model(service, {}).find(Target.device("b1")).on


def test_device_types_get_their_own_section_and_automatic_group(make_service):
    fan = FakeDevice("f1", "Ventilador", Fan.FAN, frozenset({Capability.POWER}))
    service = make_service(bulb("b1", "Lâmpada 1"), fan)

    groups, bulbs, fans = build_model(service, {}).sections

    assert titles(groups) == ["Todas as lâmpadas", "Todos os dispositivos"]
    assert titles(bulbs) == ["Lâmpada 1"]
    assert fans.title == "Dispositivos"
    assert titles(fans) == ["Ventilador"]


def test_a_mixed_group_counts_devices_generically(make_service):
    fan = FakeDevice("f1", "Ventilador", Fan.FAN, frozenset({Capability.POWER}))
    service = make_service(bulb("b1", "Lâmpada 1"), fan, groups=[Group("g1", "Sala", ("b1", "f1"))])

    assert build_model(service, {}).find(Target.group("g1")).subtitle == "Grupo · 2 dispositivos"


def test_targets_without_power_cannot_be_switched(make_service):
    sensor = FakeDevice("s1", "Sensor", Fan.FAN, frozenset({Capability.BRIGHTNESS}))
    service = make_service(bulb("b1", "Lâmpada 1"), sensor)
    model = build_model(service, {})

    assert model.find(Target.device("b1")).can_power
    assert not model.find(Target.device("s1")).can_power


def test_choose_keeps_a_known_target_and_falls_back_to_the_first(home):
    model = build_model(home, {})

    assert model.choose(Target.group("g2")) == Target.group("g2")
    assert model.choose(Target.group("deleted")) == Target.all_of(DeviceType.RGB_BULB)
    assert model.choose(None) == Target.all_of(DeviceType.RGB_BULB)


def test_without_devices_there_is_nothing_to_choose(make_service):
    model = build_model(make_service(), {})

    assert model.sections == ()
    assert model.choose(None) is None
    assert model.find(Target.all_of(DeviceType.RGB_BULB)) is None
