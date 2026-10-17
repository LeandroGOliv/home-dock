import pytest

from homedock.devices import Capability, Color, DeviceState, WorkMode


def test_empty_state_has_no_capabilities():
    assert DeviceState().capabilities == frozenset()


def test_capabilities_are_the_fields_that_are_set():
    state = DeviceState(power=True, brightness=40, color_hsv=Color(120, 50))
    assert state.capabilities == {Capability.POWER, Capability.BRIGHTNESS, Capability.COLOR_HSV}


def test_get_reads_a_value_by_capability():
    state = DeviceState(work_mode=WorkMode.WHITE, color_temperature=30)
    assert state.get(Capability.WORK_MODE) is WorkMode.WHITE
    assert state.get(Capability.COLOR_TEMPERATURE) == 30
    assert state.get(Capability.POWER) is None


def test_restricted_to_drops_unsupported_capabilities():
    state = DeviceState(power=False, brightness=10, color_temperature=0)
    restricted = state.restricted_to({Capability.POWER, Capability.COLOR_HSV})
    assert restricted == DeviceState(power=False)


def test_merged_overrides_only_the_values_that_are_set():
    base = DeviceState(power=True, brightness=80, color_hsv=Color(0, 100))
    merged = base.merged(DeviceState(brightness=20, color_temperature=50))
    assert merged == DeviceState(
        power=True, brightness=20, color_hsv=Color(0, 100), color_temperature=50
    )


@pytest.mark.parametrize("value", [0, 100])
def test_percent_fields_accept_range_edges(value):
    DeviceState(brightness=value, color_temperature=value)


@pytest.mark.parametrize("field", ["brightness", "color_temperature"])
@pytest.mark.parametrize("value", [-1, 101])
def test_percent_fields_reject_out_of_range(field, value):
    with pytest.raises(ValueError):
        DeviceState(**{field: value})


@pytest.mark.parametrize(("hue", "saturation"), [(0, 0), (360, 100)])
def test_color_accepts_range_edges(hue, saturation):
    assert Color(hue, saturation) == Color(hue=hue, saturation=saturation)


@pytest.mark.parametrize(("hue", "saturation"), [(-1, 0), (361, 0), (0, -1), (0, 101)])
def test_color_rejects_out_of_range(hue, saturation):
    with pytest.raises(ValueError):
        Color(hue, saturation)


def test_capability_values_match_state_fields():
    # Generic code (scenes, groups) addresses state fields by capability name.
    for capability in Capability:
        assert DeviceState().get(capability) is None
