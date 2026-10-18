"""Manage pages of the flyout: groups, local names and "Procurar lâmpadas novas", with fake
devices and fake persistence (no network, no app data)."""

from concurrent.futures import Future

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from executors import ManualExecutor
from homedock.core import ControlService, Group, GroupBook, Target
from homedock.devices import Capability, DeviceError, DeviceState, DeviceType
from homedock.devices.fake import FakeDevice
from homedock.storage import DeviceImport, DeviceReload, ImportProblem
from homedock.ui import strings
from homedock.ui.flyout import Flyout
from homedock.ui.manage import GroupPage, ManagePage
from homedock.ui.panels import PanelRegistry
from ui_helpers import settle

BULB = frozenset(Capability)


def bulb(device_id: str, name: str, **kwargs) -> FakeDevice:
    return FakeDevice(device_id, name, DeviceType.RGB_BULB, BULB, **kwargs)


class Store:
    """Stands in for a persisted value (names, groups); ``fail`` makes saving raise."""

    def __init__(self, value) -> None:
        self.value = value
        self.fail = False
        self.saves = 0

    def get(self):
        return self.value

    def set(self, value) -> None:
        if self.fail:
            raise PermissionError("read-only")
        self.value = value
        self.saves += 1


class Reloads:
    """Stands in for "Procurar lâmpadas novas": each call returns a future the test completes."""

    def __init__(self) -> None:
        self.futures: list[Future] = []

    def __call__(self) -> Future:
        future: Future = Future()
        self.futures.append(future)
        return future


class Home:
    def __init__(self, flyout: Flyout, service: ControlService, devices, names, groups, reloads):
        self.flyout = flyout
        self.service = service
        self.devices = devices
        self.names = names
        self.groups = groups
        self.reloads = reloads

    def manage(self) -> ManagePage:
        page = self.flyout.pages.current()
        assert isinstance(page, ManagePage)
        return page

    def group_page(self) -> GroupPage:
        page = self.flyout.pages.current()
        assert isinstance(page, GroupPage)
        return page


@pytest.fixture
def executor() -> ManualExecutor:
    return ManualExecutor()


@pytest.fixture
def make_home(qtbot, executor):
    created = []

    def make(devices=None, groups=None, names=None) -> Home:
        if devices is None:  # the mockup: Sala (Lâmpada 1, 2), Quarto (Lâmpada 3, offline)
            devices = [
                bulb("b1", "Lâmpada 1", state=DeviceState(power=True)),
                bulb("b2", "Lâmpada 2", state=DeviceState(power=True)),
                bulb("b3", "Lâmpada 3", online=False),
            ]
        if groups is None:
            groups = [Group("g1", "Sala", ("b1", "b2")), Group("g2", "Quarto", ("b3",))]
        service = ControlService(devices, GroupBook(groups), executor=executor, throttle=0)
        names_store, groups_store, reloads = (
            Store(dict(names or {})),
            Store(list(groups)),
            Reloads(),
        )
        flyout = Flyout(
            service,
            names=names_store.get,
            last_target=lambda: None,
            set_last_target=lambda _target: None,
            scenes=lambda: (),
            save_scenes=lambda _scenes: None,
            save_names=names_store.set,
            save_groups=groups_store.set,
            reload_devices=reloads,
            panels=PanelRegistry(),
        )
        qtbot.addWidget(flyout)
        created.append((flyout, service))
        home = Home(flyout, service, devices, names_store, groups_store, reloads)
        flyout.open()
        settle(executor)
        click(qtbot, flyout.main.target_button)
        click(qtbot, flyout.main.target_list.manage_link)
        return home

    yield make
    for flyout, service in created:
        flyout.shutdown()
        service.shutdown()


def click(qtbot, widget) -> None:
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)


def card_titles(page: ManagePage) -> list[tuple[str, str]]:
    return [(card.text(), card.members) for card in page.cards]


def open_group(home: Home, qtbot, index: int | None) -> GroupPage:
    """Click a group card, or "+ Novo grupo" when ``index`` is None."""
    page = home.manage()
    click(qtbot, page.new_group_link if index is None else page.cards[index])
    return home.group_page()


def check(page: GroupPage, *device_ids: str) -> None:
    for row in page.member_rows:
        row.setChecked(row.device.id in device_ids)


def rename(home: Home, qtbot, device_id: str, name: str) -> None:
    row = home.manage().device_rows[device_id]
    click(qtbot, row.rename_button)
    row.editor.field.setText(name)
    qtbot.keyClick(row.editor.field, Qt.Key.Key_Return)


# --- the manage page ---------------------------------------------------------------------------


def test_the_page_lists_the_groups_with_their_members(make_home):
    home = make_home(names={"b1": "Abajur"})
    assert card_titles(home.manage()) == [("Sala", "Abajur, Lâmpada 2"), ("Quarto", "Lâmpada 3")]


def test_the_page_lists_the_devices_with_their_status(make_home):
    page = make_home().manage()
    status = {i: (row.status.name, row.status.online) for i, row in page.device_rows.items()}
    assert status == {
        "b1": ("Lâmpada 1", True),
        "b2": ("Lâmpada 2", True),
        "b3": ("Lâmpada 3", False),
    }
    assert page.device_rows["b3"].status.accessibleName() == "Lâmpada 3 · offline"


def test_the_status_follows_the_devices_live(make_home, executor):
    home = make_home()
    home.devices[0].online = False
    home.service.refresh(Target.device("b1"))
    settle(executor)
    assert home.manage().device_rows["b1"].status.online is False


def test_without_groups_the_page_says_so(make_home):
    page = make_home(groups=[]).manage()
    assert page.cards == []
    assert strings.NO_GROUPS in label_texts(page)


def label_texts(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [w.text() for w in widget.findChildren(QLabel) if not w.isHidden()]


def test_back_shows_the_main_page_with_the_latest_groups_and_names(make_home, qtbot):
    home = make_home()
    rename(home, qtbot, "b1", "Abajur")
    page = open_group(home, qtbot, None)
    page.name_field.setText("Casa")
    check(page, "b1")
    click(qtbot, page.save_button)

    click(qtbot, home.manage().header.back_button)

    main = home.flyout.main
    assert home.flyout.pages.current() is main
    rows = main.target_list.rows
    assert rows[Target.device("b1")].entry.title == "Abajur"
    assert any(row.entry.title == "Casa" for row in rows.values())


# --- groups ------------------------------------------------------------------------------------


def test_a_group_opens_its_page_and_the_flyout_stays_open(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, 0)
    QApplication.processEvents()
    assert home.flyout.isVisible()
    assert page.isVisible()
    assert page.header.title.text() == strings.EDIT_GROUP
    assert page.name_field.text() == "Sala"
    assert [(r.text(), r.isChecked(), r.others) for r in page.member_rows] == [
        ("Lâmpada 1", True, ""),
        ("Lâmpada 2", True, ""),
        ("Lâmpada 3", False, "também em Quarto"),
    ]
    assert page.delete_button.isVisible()


def test_new_group_starts_empty_with_the_focus_on_its_name(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, None)
    QApplication.processEvents()
    assert home.flyout.isVisible()
    assert page.header.title.text() == strings.NEW_GROUP_TITLE
    assert page.name_field.text() == ""
    assert page.name_field.hasFocus()
    assert not any(r.isChecked() for r in page.member_rows)
    assert [r.others for r in page.member_rows] == [
        "também em Sala",
        "também em Sala",
        "também em Quarto",
    ]
    assert page.delete_button.isHidden()
    assert not page.save_button.isEnabled()  # no name yet


def test_saving_a_new_group_persists_it_and_controls_it(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, None)
    page.name_field.setText("  Escritório ")
    check(page, "b3")
    click(qtbot, page.save_button)

    assert home.flyout.pages.current() is home.manage()
    [*_, created] = home.groups.value
    assert (created.name, created.members) == ("Escritório", ("b3",))
    assert [g.name for g in home.service.groups.all()] == ["Sala", "Quarto", "Escritório"]
    assert card_titles(home.manage())[-1] == ("Escritório", "Lâmpada 3")


def test_a_device_may_be_in_many_groups(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, None)
    page.name_field.setText("Casa")
    check(page, "b1", "b3")
    click(qtbot, page.save_button)

    assert [g.name for g in home.service.groups.groups_of("b1")] == ["Sala", "Casa"]
    assert [g.name for g in home.service.groups.groups_of("b3")] == ["Quarto", "Casa"]


def test_enter_in_the_name_saves(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, None)
    qtbot.keyClicks(page.name_field, "Varanda")
    qtbot.keyClick(page.name_field, Qt.Key.Key_Return)
    assert home.groups.value[-1].name == "Varanda"


def test_a_blank_name_cannot_be_saved(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, 0)
    page.name_field.setText("   ")
    assert not page.save_button.isEnabled()
    qtbot.keyClick(page.name_field, Qt.Key.Key_Return)
    assert home.groups.saves == 0
    assert home.flyout.pages.current() is page


def test_editing_renames_and_changes_the_members_keeping_their_order(make_home, qtbot):
    home = make_home(groups=[Group("g1", "Sala", ("b2", "b1"))])
    page = open_group(home, qtbot, 0)
    page.name_field.setText("Sala de estar")
    check(page, "b1", "b2", "b3")
    click(qtbot, page.save_button)

    [group] = home.service.groups.all()
    assert group == Group("g1", "Sala de estar", ("b2", "b1", "b3"))
    assert home.groups.value == [group]


def test_members_no_longer_known_are_kept(make_home, qtbot):
    home = make_home(groups=[Group("g1", "Sala", ("gone", "b1"))])
    page = open_group(home, qtbot, 0)
    check(page, "b2")
    click(qtbot, page.save_button)
    assert home.service.groups.get("g1").members == ("gone", "b2")


def test_back_discards_the_changes(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, 0)
    page.name_field.setText("Outro nome")
    check(page)
    click(qtbot, page.header.back_button)

    assert home.flyout.pages.current() is home.manage()
    assert home.groups.saves == 0
    assert home.service.groups.get("g1").name == "Sala"


def test_a_failed_save_says_so_and_changes_nothing(make_home, qtbot):
    home = make_home()
    home.groups.fail = True
    page = open_group(home, qtbot, 0)
    page.name_field.setText("Outro nome")
    click(qtbot, page.save_button)

    assert home.flyout.pages.current() is page
    assert not page.notice.isHidden()
    assert page.notice.text.text() == strings.GROUPS_SAVE_FAILED
    assert home.service.groups.get("g1").name == "Sala"


def test_deleting_a_group_returns_with_an_undo(make_home, qtbot):
    home = make_home()
    page = open_group(home, qtbot, 0)
    click(qtbot, page.delete_button)

    manage = home.manage()
    assert card_titles(manage) == [("Quarto", "Lâmpada 3")]
    assert [g.name for g in home.groups.value] == ["Quarto"]
    assert [g.name for g in home.service.groups.all()] == ["Quarto"]
    assert manage.notice.text.text() == "“Sala” excluído"

    click(qtbot, manage.notice.action)

    assert card_titles(manage) == [("Sala", "Lâmpada 1, Lâmpada 2"), ("Quarto", "Lâmpada 3")]
    assert [g.name for g in home.service.groups.all()] == ["Sala", "Quarto"]
    assert [g.name for g in home.groups.value] == ["Sala", "Quarto"]
    assert manage.notice.isHidden()


def test_a_failed_delete_keeps_the_group(make_home, qtbot):
    home = make_home()
    home.groups.fail = True
    page = open_group(home, qtbot, 0)
    click(qtbot, page.delete_button)
    assert home.flyout.pages.current() is page
    assert [g.name for g in home.service.groups.all()] == ["Sala", "Quarto"]


# --- local names -------------------------------------------------------------------------------


def test_renaming_saves_a_local_name_only(make_home, qtbot):
    home = make_home()
    rename(home, qtbot, "b1", "Abajur")

    assert home.names.value == {"b1": "Abajur"}
    assert home.devices[0].name == "Lâmpada 1"  # the device (and devices.json) keep theirs
    page = home.manage()
    assert page.device_rows["b1"].status.name == "Abajur"
    assert not page.device_rows["b1"].editing()
    assert card_titles(page)[0] == ("Sala", "Abajur, Lâmpada 2")


def test_the_rename_field_starts_with_the_current_name(make_home, qtbot):
    home = make_home(names={"b2": "Luminária"})
    row = home.manage().device_rows["b2"]
    click(qtbot, row.rename_button)
    assert row.editing()
    assert row.editor.field.text() == "Luminária"
    assert row.editor.field.hasFocus()


def test_renaming_back_to_the_wizard_name_drops_the_local_one(make_home, qtbot):
    home = make_home(names={"b1": "Abajur", "b2": "Luminária"})
    rename(home, qtbot, "b1", "Lâmpada 1")
    assert home.names.value == {"b2": "Luminária"}


def test_escape_cancels_the_rename_and_keeps_the_flyout_open(make_home, qtbot):
    home = make_home()
    row = home.manage().device_rows["b1"]
    click(qtbot, row.rename_button)
    row.editor.field.setText("Abajur")
    qtbot.keyClick(row.editor.field, Qt.Key.Key_Escape)

    assert home.flyout.isVisible()
    assert not row.editing()
    assert home.names.saves == 0
    assert row.rename_button.hasFocus()


def test_one_rename_at_a_time(make_home, qtbot):
    page = make_home().manage()
    click(qtbot, page.device_rows["b1"].rename_button)
    click(qtbot, page.device_rows["b2"].rename_button)
    assert not page.device_rows["b1"].editing()
    assert page.device_rows["b2"].editing()


def test_a_failed_rename_says_so_and_keeps_the_old_name(make_home, qtbot):
    home = make_home()
    home.names.fail = True
    rename(home, qtbot, "b1", "Abajur")
    page = home.manage()
    assert page.notice.text.text() == strings.NAME_SAVE_FAILED
    assert page.device_rows["b1"].status.name == "Lâmpada 1"


# --- "Procurar lâmpadas novas" -----------------------------------------------------------------


def reload_result(service: ControlService, **fields) -> DeviceReload:
    return DeviceReload(DeviceImport(), **fields)


def test_finding_devices_runs_once_without_blocking_the_page(make_home, qtbot):
    home = make_home()
    button = home.manage().find_button
    click(qtbot, button)

    assert len(home.reloads.futures) == 1  # started; the page keeps working meanwhile
    assert button.text() == strings.FINDING_DEVICES
    assert not button.isEnabled()
    home.flyout.reloader.start()  # a second request while it runs is ignored
    assert len(home.reloads.futures) == 1


def test_the_page_shows_the_devices_found_and_what_changed(make_home, qtbot):
    home = make_home()
    click(qtbot, home.manage().find_button)
    new = bulb("b4", "Lâmpada 4")
    home.service.replace_devices([*home.devices, new])  # what the app does on the worker
    home.reloads.futures[0].set_result(reload_result(home.service, updated_ips=1))
    QApplication.processEvents()

    page = home.manage()
    assert list(page.device_rows) == ["b1", "b2", "b3", "b4"]
    assert page.notice.text.text() == "4 lâmpadas · 1 IP atualizado"
    assert page.find_button.isEnabled()
    assert page.find_button.text() == strings.FIND_DEVICES


@pytest.mark.parametrize(
    ("fields", "text"),
    [
        ({}, "3 lâmpadas · IPs em dia"),
        (
            {"not_imported": 1},
            "3 lâmpadas · IPs em dia. 1 dispositivo Tuya na rede não está no devices.json: "
            "rode o wizard de novo.",
        ),
        ({"scan_failed": True}, strings.SCAN_FAILED),
        (
            {"updated_ips": 2, "write_failed": True},
            f"3 lâmpadas · 2 IPs atualizados · {strings.IPS_NOT_SAVED}",
        ),
    ],
)
def test_the_reload_notice(make_home, qtbot, fields, text):
    home = make_home()
    click(qtbot, home.manage().find_button)
    home.reloads.futures[0].set_result(reload_result(home.service, **fields))
    QApplication.processEvents()
    assert home.manage().notice.text.text() == text


@pytest.mark.parametrize(
    ("problem", "text"),
    [
        (ImportProblem.MISSING, strings.DEVICES_MISSING),
        (ImportProblem.UNREADABLE, strings.DEVICES_UNREADABLE),
        (ImportProblem.INVALID, strings.DEVICES_UNREADABLE),
    ],
)
def test_a_devices_file_that_cannot_be_read_is_reported(make_home, qtbot, problem, text):
    home = make_home()
    click(qtbot, home.manage().find_button)
    home.reloads.futures[0].set_result(DeviceReload(DeviceImport(problem=problem)))
    QApplication.processEvents()
    assert home.manage().notice.text.text() == text
    assert list(home.manage().device_rows) == ["b1", "b2", "b3"]


def test_a_failed_reload_is_reported_and_can_be_tried_again(make_home, qtbot):
    home = make_home()
    click(qtbot, home.manage().find_button)
    home.reloads.futures[0].set_exception(DeviceError("boom"))
    QApplication.processEvents()
    page = home.manage()
    assert page.notice.text.text() == strings.SCAN_FAILED
    click(qtbot, page.find_button)
    assert len(home.reloads.futures) == 2


def test_a_reload_ending_after_the_page_was_left_updates_the_main_page(make_home, qtbot):
    home = make_home()
    click(qtbot, home.manage().find_button)
    click(qtbot, home.manage().header.back_button)
    home.service.replace_devices([*home.devices, bulb("b4", "Lâmpada 4")])
    home.reloads.futures[0].set_result(reload_result(home.service))
    QApplication.processEvents()

    assert Target.device("b4") in home.flyout.main.target_list.rows


def test_a_running_reload_shows_on_a_page_opened_meanwhile(make_home, qtbot):
    home = make_home()
    click(qtbot, home.manage().find_button)
    click(qtbot, home.manage().header.back_button)
    click(qtbot, home.flyout.main.target_button)
    click(qtbot, home.flyout.main.target_list.manage_link)
    assert not home.manage().find_button.isEnabled()


# --- size --------------------------------------------------------------------------------------


def test_returning_from_a_group_takes_the_height_of_the_manage_page(make_home, qtbot):
    home = make_home()
    height = home.flyout.height()
    click(qtbot, open_group(home, qtbot, 0).header.back_button)
    assert home.flyout.height() == height
    assert home.manage().body.height() == home.manage().body.sizeHint().height()


def test_a_notice_grows_the_flyout_upwards(make_home, qtbot):
    home = make_home()
    before = home.flyout.frameGeometry()
    home.manage().show_reload(None)
    after = home.flyout.frameGeometry()
    assert after.height() > before.height()
    assert after.bottom() == before.bottom()


def test_many_devices_scroll_within_the_screen(make_home):
    devices = [bulb(f"b{n}", f"Lâmpada {n}") for n in range(40)]
    home = make_home(devices=devices, groups=[])
    area = home.flyout.screen().availableGeometry()
    assert home.flyout.height() <= area.height()
    assert home.manage().body.height() < home.manage().body.sizeHint().height()


def test_reopening_after_closing_on_a_manage_page_takes_the_main_page_height(make_home, qtbot):
    home = make_home(devices=[bulb(f"b{n}", f"Lâmpada {n}") for n in range(6)])
    click(qtbot, home.manage().header.back_button)
    main_height = home.flyout.height()
    click(qtbot, home.flyout.main.target_button)
    click(qtbot, home.flyout.main.target_list.manage_link)
    assert home.flyout.height() != main_height

    home.flyout.hide()  # e.g. it lost the focus
    home.flyout.open()

    assert home.flyout.pages.current() is home.flyout.main
    assert home.flyout.height() == main_height
