import itertools

import pytest

from homedock.core.scenes import Scene, SceneBook
from homedock.devices import Color, DeviceState, WorkMode

READING = {"dev-a": DeviceState(power=True, work_mode=WorkMode.WHITE, brightness=80)}
PARTY = {"dev-a": DeviceState(power=True, color_hsv=Color(300, 100)), "dev-b": DeviceState()}


def make_book(*scenes: Scene) -> SceneBook:
    ids = (f"scene-{n}" for n in itertools.count(1))
    return SceneBook(scenes, new_id=lambda: next(ids))


def test_create_stores_the_snapshot_under_a_new_id():
    book = make_book()
    scene = book.create(" Leitura ", READING)
    assert scene == Scene(id="scene-1", name="Leitura", devices=READING)
    assert book.all() == [scene]
    assert book.get("scene-1") == scene


def test_the_scene_does_not_follow_later_changes_to_the_snapshot():
    snapshot = dict(READING)
    scene = make_book().create("Leitura", snapshot)
    snapshot["dev-b"] = DeviceState(power=False)
    assert scene.devices == READING


def test_blank_names_are_rejected():
    book = make_book()
    with pytest.raises(ValueError):
        book.create("", READING)
    book.create("Leitura", READING)
    with pytest.raises(ValueError):
        book.rename("scene-1", "  ")


def test_rename_keeps_the_devices():
    book = make_book()
    book.create("Leitura", READING)
    assert book.rename("scene-1", "Ler") == Scene("scene-1", "Ler", READING)


def test_overwrite_replaces_the_devices_and_keeps_id_and_name():
    book = make_book()
    book.create("Leitura", READING)
    assert book.overwrite("scene-1", PARTY) == Scene("scene-1", "Leitura", PARTY)
    assert book.get("scene-1").devices == PARTY


def test_delete_and_unknown_scenes():
    book = make_book()
    book.create("Leitura", READING)
    book.delete("scene-1")
    assert book.all() == []
    for action in (
        lambda: book.get("scene-1"),
        lambda: book.rename("scene-1", "X"),
        lambda: book.overwrite("scene-1", READING),
        lambda: book.delete("scene-1"),
    ):
        with pytest.raises(KeyError):
            action()


def test_the_book_starts_from_existing_scenes_in_order():
    saved = [Scene("s-1", "Leitura", READING), Scene("s-2", "Festa", PARTY)]
    assert make_book(*saved).all() == saved
