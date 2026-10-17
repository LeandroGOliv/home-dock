"""Target selector widgets: the row text split, the list rows and the buttons."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from homedock.core import Target
from homedock.devices import DeviceType
from homedock.ui import theme
from homedock.ui.selector import TEXT_GAP, PowerButton, TargetButton, TargetList, split_row
from homedock.ui.target_model import Section, TargetEntry, TargetModel

ALL = Target.all_of(DeviceType.RGB_BULB)


def entry(target: Target, title: str, detail: str = "", **kwargs) -> TargetEntry:
    values = {"subtitle": "", "on": False, "can_power": True, "online": None} | kwargs
    return TargetEntry(target, title, detail=detail, **values)


def model(*devices: TargetEntry) -> TargetModel:
    groups = Section("Grupos", (entry(ALL, "Todas as lâmpadas", str(len(devices))),))
    return TargetModel((groups, Section("Lâmpadas", devices)))


# --- text split -------------------------------------------------------------------------------


def test_title_and_detail_are_whole_when_they_fit():
    assert split_row(300, 100, 80) == (100, 80)


def test_the_detail_is_elided_first():
    title, detail = split_row(300, 150, 200)

    assert title == 150
    assert detail == 300 - TEXT_GAP - 150


def test_the_title_keeps_at_least_half_of_the_row():
    title, detail = split_row(300, 400, 400)

    assert title == 150
    assert detail == 150 - TEXT_GAP


def test_a_short_title_never_gets_more_than_it_needs():
    assert split_row(300, 40, 1000)[0] == 40


# --- list -------------------------------------------------------------------------------------


@pytest.fixture
def target_list(qtbot) -> TargetList:
    widget = TargetList()
    qtbot.addWidget(widget)
    return widget


def test_the_list_has_a_row_per_target_and_marks_the_selected_one(target_list):
    lamp = Target.device("b1")
    target_list.set_model(model(entry(lamp, "Lâmpada 1")), lamp)

    assert list(target_list.rows) == [ALL, lamp]
    assert target_list.rows[lamp].is_selected()
    assert not target_list.rows[ALL].is_selected()


def test_state_updates_keep_the_rows_and_change_their_text(target_list):
    lamp = Target.device("b1")
    target_list.set_model(model(entry(lamp, "Lâmpada 1")), ALL)
    row = target_list.rows[lamp]

    target_list.set_model(model(entry(lamp, "Lâmpada 1", "offline", online=False)), ALL)

    assert target_list.rows[lamp] is row
    assert row.entry.detail == "offline"


def test_a_new_target_rebuilds_the_rows(target_list):
    first, second = Target.device("b1"), Target.device("b2")
    target_list.set_model(model(entry(first, "Lâmpada 1")), ALL)

    target_list.set_model(model(entry(first, "Lâmpada 1"), entry(second, "Lâmpada 2")), ALL)

    assert list(target_list.rows) == [ALL, first, second]


def test_a_long_list_scrolls_within_its_maximum_height(target_list):
    lamps = [entry(Target.device(f"b{n}"), f"Lâmpada {n}") for n in range(30)]
    target_list.set_model(model(*lamps), ALL)
    assert target_list.sizeHint().height() <= theme.LIST_MAX_HEIGHT

    target_list.set_max_height(300)

    assert target_list.sizeHint().height() <= 300


def test_clicking_a_row_chooses_its_target(target_list, qtbot):
    lamp = Target.device("b1")
    target_list.set_model(model(entry(lamp, "Lâmpada 1")), ALL)
    target_list.show()

    with qtbot.waitSignal(target_list.chosen) as chosen:
        qtbot.mouseClick(target_list.rows[lamp], Qt.MouseButton.LeftButton)

    assert chosen.args == [lamp]


def test_the_manage_link_asks_for_the_manage_page(target_list, qtbot):
    target_list.show()

    with qtbot.waitSignal(target_list.manage_requested):
        qtbot.mouseClick(target_list.manage_link, Qt.MouseButton.LeftButton)


# --- buttons ----------------------------------------------------------------------------------


def test_the_target_button_shows_title_and_subtitle(qtbot):
    button = TargetButton()
    qtbot.addWidget(button)

    button.set_target("Sala", "Grupo · 2 de 2 online")

    assert button.text() == "Sala"
    assert button.subtitle() == "Grupo · 2 de 2 online"
    assert button.isCheckable()


@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_the_buttons_paint_in_every_state(qtbot, checked, enabled):
    for button in (TargetButton(), PowerButton()):
        qtbot.addWidget(button)
        button.resize(button.sizeHint().expandedTo(button.minimumSize()))
        button.setChecked(checked)
        button.setEnabled(enabled)
        image = QImage(button.size(), QImage.Format.Format_ARGB32)
        button.render(image)  # must not raise
