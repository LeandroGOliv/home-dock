"""Scenes in the flyout: grid, apply, save, rename, overwrite, delete, with fake devices."""

from enum import StrEnum

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel

from executors import ManualExecutor
from homedock.core import ControlService, Group, GroupBook, Scene, Target
from homedock.devices import Capability, Color, DeviceState, DeviceType, WorkMode
from homedock.devices.fake import FakeDevice
from homedock.ui import strings, theme
from homedock.ui.bridge import ServiceBridge
from homedock.ui.scenes import COLUMNS, ScenesSection
from ui_helpers import settle

BULB = frozenset(Capability)
ALL_BULBS = Target.all_of(DeviceType.RGB_BULB)
READING = DeviceState(
    power=True, work_mode=WorkMode.WHITE, brightness=80, color_hsv=Color(0, 0), color_temperature=30
)
MOVIE = DeviceState(
    power=True,
    work_mode=WorkMode.COLOR,
    brightness=20,
    color_hsv=Color(240, 90),
    color_temperature=0,
)
OFF = DeviceState(
    power=False,
    work_mode=WorkMode.WHITE,
    brightness=50,
    color_hsv=Color(0, 0),
    color_temperature=50,
)


class OtherType(StrEnum):
    SENSOR = "test_sensor"


def bulb(device_id: str, state: DeviceState = OFF, **kwargs) -> FakeDevice:
    return FakeDevice(device_id, device_id, DeviceType.RGB_BULB, BULB, state=state, **kwargs)


def scene(scene_id: str, name: str, **devices: DeviceState) -> Scene:
    return Scene(scene_id, name, devices)


class SceneStore:
    """Stands in for the scenes of the config file."""

    def __init__(self, *scenes: Scene, fail: bool = False) -> None:
        self.scenes = tuple(scenes)
        self.fail = fail
        self.saves = 0

    def get(self) -> tuple[Scene, ...]:
        return self.scenes

    def set(self, scenes) -> None:
        if self.fail:
            raise PermissionError("read-only")
        self.scenes = tuple(scenes)
        self.saves += 1


class Harness:
    def __init__(self, section: ScenesSection, store: SceneStore, executor: ManualExecutor):
        self.section = section
        self.store = store
        self.executor = executor
        self.target: Target | None = ALL_BULBS

    @property
    def grid(self):
        return self.section.grid

    def names(self) -> list[str]:
        return [button.text() for button in self.grid.buttons]

    def button(self, name: str):
        return next(b for b in self.grid.buttons if b.text() == name)

    def click(self, qtbot, name: str) -> None:
        qtbot.mouseClick(self.button(name), Qt.MouseButton.LeftButton)

    def menu(self, name: str, reason=QContextMenuEvent.Reason.Mouse) -> dict:
        """Right-click ``name``: its menu items by text."""
        button = self.button(name)
        centre = button.rect().center()
        event = QContextMenuEvent(reason, centre, button.mapToGlobal(centre))
        QApplication.sendEvent(button, event)
        menu = self.section.menu
        assert menu is not None and menu.isVisible()
        return {item.text(): item for item in menu.actions()}

    def choose(self, name: str, item: str) -> None:
        self.menu(name)[item].trigger()
        self.section.menu.close()

    def type_name(self, qtbot, text: str) -> None:
        field = self.section.editor.field
        field.selectAll()
        qtbot.keyClicks(field, text)
        qtbot.keyClick(field, Qt.Key.Key_Return)

    def settle(self) -> None:
        settle(self.executor)

    def notice(self) -> str | None:
        notice = self.section.notice
        return None if notice.isHidden() else notice.text.text()


@pytest.fixture
def executor() -> ManualExecutor:
    return ManualExecutor()


@pytest.fixture
def make_section(qtbot, executor):
    created = []

    def make(*devices, scenes=(), groups=(), fail=False):
        service = ControlService(devices, GroupBook(groups), executor=executor, throttle=0)
        bridge = ServiceBridge(service)
        store = SceneStore(*scenes, fail=fail)
        harness = Harness(None, store, executor)
        section = ScenesSection(
            service,
            bridge,
            target=lambda: harness.target,
            scenes=store.get,
            save_scenes=store.set,
        )
        section.setFixedWidth(theme.WIDTH - 2 * theme.PADDING)
        qtbot.addWidget(section)
        section.show()
        section.reload()
        QApplication.processEvents()  # lay the new buttons out, as the event loop does
        harness.section = section
        created.append((bridge, service))
        return harness

    yield make
    for bridge, service in created:
        bridge.detach()
        service.shutdown()


# --- grid -------------------------------------------------------------------------------------


def test_the_saved_scenes_show_in_a_grid_of_three_columns(make_section):
    scenes = [scene(f"s{n}", f"Cena {n}") for n in range(1, 6)]
    harness = make_section(bulb("b1"), scenes=scenes)

    assert harness.names() == [s.name for s in scenes]
    assert COLUMNS == 3
    first, second, third, fourth = (harness.grid.buttons[i] for i in range(4))
    assert first.y() == second.y() == third.y() < fourth.y()
    assert first.x() == fourth.x() < second.x() < third.x()
    widths = [b.width() for b in (first, second, third)]
    assert max(widths) - min(widths) <= 1  # the row split in three


def test_one_row_shows_and_the_others_scroll(make_section):
    three = make_section(bulb("b1"), scenes=[scene(f"s{n}", f"C{n}") for n in range(3)])
    four = make_section(bulb("b1"), scenes=[scene(f"s{n}", f"C{n}") for n in range(4)])

    for harness in (three, four):
        assert harness.grid.height() == theme.SCENE_HEIGHT
    assert three.grid.verticalScrollBar().maximum() == 0
    assert four.grid.verticalScrollBar().maximum() > 0


def test_the_wheel_scrolls_a_whole_row_per_notch(make_section):
    harness = make_section(bulb("b1"), scenes=[scene(f"s{n}", f"C{n}") for n in range(9)])
    grid = harness.grid

    def wheel(delta: int) -> None:
        centre = QPointF(grid.viewport().rect().center())
        event = QWheelEvent(
            centre,
            QPointF(grid.viewport().mapToGlobal(centre.toPoint())),
            QPoint(0, 0),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(grid.viewport(), event)

    wheel(-120)
    assert grid.first_row() == 1
    assert grid.verticalScrollBar().value() == theme.SCENE_HEIGHT + theme.SCENE_GAP
    wheel(-60)  # half a notch (a touchpad) does not scroll yet...
    assert grid.first_row() == 1
    wheel(-60)  # ...the other half does
    assert grid.first_row() == 2
    wheel(240)
    assert grid.first_row() == 0


def test_tabbing_to_a_scene_scrolls_to_its_row(make_section, qtbot):
    harness = make_section(bulb("b1"), scenes=[scene(f"s{n}", f"C{n}") for n in range(6)])
    harness.grid.buttons[2].setFocus(Qt.FocusReason.TabFocusReason)

    qtbot.keyClick(harness.grid.buttons[2], Qt.Key.Key_Tab)

    assert harness.grid.buttons[3].hasFocus()
    assert harness.grid.buttons[3].focus_shown()
    assert harness.grid.first_row() == 1


def test_without_scenes_the_grid_says_so(make_section):
    harness = make_section(bulb("b1"))

    assert harness.grid.buttons == []
    labels = harness.grid.widget().findChildren(QLabel)
    assert [label.text() for label in labels if label.isVisible()] == [strings.NO_SCENES]


# --- apply ------------------------------------------------------------------------------------


def test_a_click_applies_the_scene_mode_colour_brightness_and_power(make_section, qtbot):
    b1, b2 = bulb("b1", READING), bulb("b2", OFF)
    harness = make_section(b1, b2, scenes=[scene("s1", "Filme", b1=MOVIE, b2=READING)])

    harness.click(qtbot, "Filme")
    assert b1.applied == []  # sent to the workers, not on the UI thread
    harness.settle()

    assert b1.state == MOVIE
    assert b2.state == READING
    assert harness.notice() is None


def test_offline_devices_are_skipped_with_a_discreet_notice(make_section, qtbot):
    b1, b2 = bulb("b1"), bulb("b2", online=False)
    harness = make_section(b1, b2, scenes=[scene("s1", "Filme", b1=MOVIE, b2=MOVIE)])

    harness.click(qtbot, "Filme")
    harness.settle()

    assert b1.state == MOVIE
    assert harness.notice() == strings.left_out("Filme", 1, strings.noun(DeviceType.RGB_BULB))
    assert harness.notice() == "Filme · 1 lâmpada offline ficou de fora"


def test_the_notice_hides_by_itself(make_section, qtbot):
    harness = make_section(bulb("b1", online=False), scenes=[scene("s1", "Filme", b1=MOVIE)])
    harness.click(qtbot, "Filme")
    harness.settle()
    assert harness.section.notice.timer.isActive()

    harness.section.notice.timer.timeout.emit()

    assert harness.notice() is None


# --- save -------------------------------------------------------------------------------------


def test_save_current_asks_for_a_name_with_a_suggestion(make_section, qtbot):
    harness = make_section(bulb("b1"), scenes=[scene("s1", "Cena 1")])

    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)

    field = harness.section.editor.field
    assert harness.section.editing()
    assert field.text() == "Cena 2"
    assert field.selectedText() == "Cena 2"  # typing replaces it
    assert field.hasFocus()


def test_save_current_stores_the_state_of_the_target_devices(make_section, qtbot):
    b1, b2, b3 = bulb("b1", READING), bulb("b2", MOVIE), bulb("b3", OFF)
    sala = Group("g1", "Sala", ("b1", "b2"))
    harness = make_section(b1, b2, b3, groups=[sala])
    harness.target = Target.group("g1")

    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)
    harness.type_name(qtbot, "Leitura")
    assert not harness.section.editing()
    assert harness.store.scenes == ()  # saved once the devices answered
    harness.settle()

    [saved] = harness.store.scenes
    assert saved.name == "Leitura"
    assert dict(saved.devices) == {"b1": READING, "b2": MOVIE}
    assert harness.names() == ["Leitura"]
    assert harness.notice() is None


def test_a_new_scene_scrolls_into_view(make_section, qtbot):
    harness = make_section(bulb("b1"), scenes=[scene(f"s{n}", f"C{n}") for n in range(6)])

    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)
    harness.type_name(qtbot, "Nova")
    harness.settle()

    assert harness.names()[-1] == "Nova"
    assert harness.grid.first_row() == 2


def test_save_current_leaves_offline_devices_out_and_says_so(make_section, qtbot):
    b1, b2 = bulb("b1", READING), bulb("b2", online=False)
    harness = make_section(b1, b2)

    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)
    harness.type_name(qtbot, "Leitura")
    harness.settle()

    [saved] = harness.store.scenes
    assert dict(saved.devices) == {"b1": READING}
    assert harness.notice() == "Leitura · 1 lâmpada offline ficou de fora"


def test_nothing_is_saved_when_no_device_answers(make_section, qtbot):
    harness = make_section(bulb("b1", online=False), bulb("b2", online=False))

    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)
    harness.type_name(qtbot, "Leitura")
    harness.settle()

    assert harness.store.scenes == ()
    assert harness.notice() == "Lâmpadas offline · nada foi salvo"


def test_escape_and_the_cancel_button_close_the_name_field(make_section, qtbot):
    harness = make_section(bulb("b1"))
    editor = harness.section.editor

    for close in (
        lambda: qtbot.keyClick(editor.field, Qt.Key.Key_Escape),
        lambda: qtbot.mouseClick(editor.cancel_button, Qt.MouseButton.LeftButton),
    ):
        qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)
        close()
        assert not harness.section.editing()

    harness.settle()
    assert harness.store.scenes == ()


def test_a_blank_name_cannot_be_saved(make_section, qtbot):
    harness = make_section(bulb("b1"))
    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)

    harness.type_name(qtbot, "   ")

    assert harness.section.editing()
    assert not harness.section.editor.save_button.isEnabled()


def test_the_save_button_saves_the_typed_name(make_section, qtbot):
    harness = make_section(bulb("b1"))
    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(harness.section.editor.field, " Leitura ")  # replaces the suggestion

    qtbot.mouseClick(harness.section.editor.save_button, Qt.MouseButton.LeftButton)
    harness.settle()

    assert [s.name for s in harness.store.scenes] == ["Leitura"]


def test_save_current_is_disabled_for_a_target_without_devices(make_section):
    harness = make_section(bulb("b1"), groups=[Group("g1", "Vazio")])
    assert harness.section.save_link.isEnabled()

    harness.target = Target.group("g1")
    harness.section.update_actions()

    assert not harness.section.save_link.isEnabled()


def test_a_scene_saved_for_one_type_works_in_mixed_setups(make_section, qtbot):
    sensor = FakeDevice("x1", "x1", OtherType.SENSOR, frozenset({Capability.POWER}), online=False)
    harness = make_section(bulb("b1", online=False), sensor, scenes=[scene("s1", "Tudo")])
    harness.target = None
    harness.section.update_actions()
    assert not harness.section.save_link.isEnabled()

    harness.store.scenes = (scene("s1", "Tudo", b1=MOVIE, x1=DeviceState(power=True)),)
    harness.section.reload()
    harness.click(qtbot, "Tudo")
    harness.settle()

    assert harness.notice() == "Tudo · 2 dispositivos offline ficaram de fora"


# --- right-click menu -------------------------------------------------------------------------


def test_the_menu_offers_rename_overwrite_and_delete(make_section):
    harness = make_section(bulb("b1"), scenes=[scene("s1", "Leitura")])

    items = harness.menu("Leitura")

    assert list(items) == [strings.RENAME, strings.OVERWRITE, strings.DELETE]
    assert all(item.isEnabled() for item in items.values())
    harness.section.menu.close()


def test_the_menu_key_opens_the_menu_too(make_section):
    harness = make_section(bulb("b1"), scenes=[scene("s1", "Leitura")])

    items = harness.menu("Leitura", QContextMenuEvent.Reason.Keyboard)

    assert strings.RENAME in items
    harness.section.menu.close()


def test_rename_edits_the_name_in_place(make_section, qtbot):
    harness = make_section(bulb("b1"), scenes=[scene("s1", "Leitura", b1=READING)])

    harness.choose("Leitura", strings.RENAME)
    assert harness.section.editor.field.text() == "Leitura"
    harness.type_name(qtbot, "Ler")

    assert harness.store.scenes == (scene("s1", "Ler", b1=READING),)
    assert harness.names() == ["Ler"]


def test_overwrite_saves_the_current_state_under_the_same_scene(make_section):
    b1 = bulb("b1", MOVIE)
    harness = make_section(b1, scenes=[scene("s1", "Leitura", b1=READING), scene("s2", "X")])

    harness.choose("Leitura", strings.OVERWRITE)
    harness.settle()

    assert harness.store.scenes[0] == scene("s1", "Leitura", b1=MOVIE)
    assert harness.names() == ["Leitura", "X"]


def test_overwrite_is_disabled_for_a_target_without_devices(make_section):
    harness = make_section(bulb("b1"), scenes=[scene("s1", "Leitura")])
    harness.target = None

    assert not harness.menu("Leitura")[strings.OVERWRITE].isEnabled()
    harness.section.menu.close()


def test_delete_removes_the_scene_and_offers_to_undo(make_section, qtbot):
    scenes = [scene("s1", "Leitura"), scene("s2", "Filme"), scene("s3", "Relaxar")]
    harness = make_section(bulb("b1"), scenes=scenes)

    harness.choose("Filme", strings.DELETE)

    assert harness.names() == ["Leitura", "Relaxar"]
    assert [s.id for s in harness.store.scenes] == ["s1", "s3"]
    assert harness.notice() == "Cena Filme excluída"
    undo = harness.section.notice.action
    assert undo.isVisible() and undo.text() == strings.UNDO

    qtbot.mouseClick(undo, Qt.MouseButton.LeftButton)

    assert list(harness.store.scenes) == scenes
    assert harness.names() == ["Leitura", "Filme", "Relaxar"]
    assert harness.notice() is None


def test_a_failed_save_says_so_and_shows_the_saved_scenes(make_section, caplog):
    harness = make_section(bulb("b1"), scenes=[scene("s1", "Leitura")], fail=True)

    harness.choose("Leitura", strings.DELETE)

    assert harness.names() == ["Leitura"]
    assert harness.notice() == strings.SAVE_FAILED
    assert not harness.section.notice.action.isVisible()  # nothing to undo
    assert "PermissionError" in caplog.text


def test_reload_shows_the_latest_scenes_and_closes_the_name_field(make_section, qtbot):
    harness = make_section(bulb("b1"))
    qtbot.mouseClick(harness.section.save_link, Qt.MouseButton.LeftButton)
    harness.store.scenes = (scene("s1", "Leitura"),)

    harness.section.reload()

    assert not harness.section.editing()
    assert harness.names() == ["Leitura"]


# --- texts ------------------------------------------------------------------------------------


def test_the_suggested_name_is_the_first_free_number():
    assert strings.new_scene_name([]) == "Cena 1"
    assert strings.new_scene_name(["Cena 1", "Cena 3", "Leitura"]) == "Cena 2"


def test_notices_agree_with_the_number_of_devices():
    bulbs = strings.noun(DeviceType.RGB_BULB)
    assert strings.left_out("Filme", 2, bulbs) == "Filme · 2 lâmpadas offline ficaram de fora"
    assert strings.nothing_saved(1, bulbs) == "Lâmpada offline · nada foi salvo"
    assert strings.nothing_saved(3, strings.noun(None)) == "Dispositivos offline · nada foi salvo"
