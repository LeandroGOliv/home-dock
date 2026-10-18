import itertools

import pytest

from homedock.core.groups import Group, GroupBook


def make_book(*groups: Group) -> GroupBook:
    ids = (f"group-{n}" for n in itertools.count(1))
    return GroupBook(groups, new_id=lambda: next(ids))


def test_create_assigns_an_id_and_keeps_the_members_in_order():
    book = make_book()
    group = book.create("Sala", ["dev-b", "dev-a"])
    assert group == Group(id="group-1", name="Sala", members=("dev-b", "dev-a"))
    assert book.all() == [group]
    assert book.get("group-1") == group


def test_default_ids_are_unique():
    book = GroupBook()
    assert book.create("Sala").id != book.create("Quarto").id


def test_names_are_trimmed_and_must_not_be_blank():
    book = make_book()
    assert book.create("  Sala  ").name == "Sala"
    with pytest.raises(ValueError):
        book.create("   ")
    assert book.create("Quarto").id == "group-2"  # a rejected name does not use up an id


def test_duplicate_members_are_dropped():
    group = make_book().create("Sala", ["dev-a", "dev-b", "dev-a"])
    assert group.members == ("dev-a", "dev-b")


def test_rename_keeps_id_and_members():
    book = make_book()
    book.create("Sala", ["dev-a"])
    renamed = book.rename("group-1", "Sala de estar")
    assert renamed == Group("group-1", "Sala de estar", ("dev-a",))
    assert book.get("group-1") == renamed
    with pytest.raises(ValueError):
        book.rename("group-1", "")


def test_set_members_replaces_the_members():
    book = make_book()
    book.create("Sala", ["dev-a"])
    assert book.set_members("group-1", ["dev-b", "dev-c"]).members == ("dev-b", "dev-c")
    assert book.get("group-1").members == ("dev-b", "dev-c")


def test_delete_removes_the_group():
    book = make_book()
    book.create("Sala")
    book.create("Quarto")
    book.delete("group-1")
    assert [g.name for g in book.all()] == ["Quarto"]
    with pytest.raises(KeyError):
        book.get("group-1")


def test_unknown_group_raises_key_error():
    book = make_book()
    for action in (
        lambda: book.get("nope"),
        lambda: book.rename("nope", "X"),
        lambda: book.set_members("nope", []),
        lambda: book.delete("nope"),
    ):
        with pytest.raises(KeyError):
            action()


def test_a_device_may_belong_to_many_groups():
    book = make_book()
    sala = book.create("Sala", ["dev-a", "dev-b"])
    casa = book.create("Casa", ["dev-a"])
    book.create("Quarto", ["dev-c"])
    assert book.groups_of("dev-a") == [sala, casa]


def test_the_book_starts_from_existing_groups():
    existing = Group("saved-1", "Sala", ("dev-a",))
    book = make_book(existing)
    assert book.all() == [existing]
    assert book.create("Quarto").id == "group-1"


def test_restore_puts_a_deleted_group_back_at_its_position():
    saved = [Group("g-1", "Sala", ("dev-a",)), Group("g-2", "Quarto", ("dev-b",))]
    book = make_book(*saved, Group("g-3", "Casa"))
    book.delete("g-2")
    assert book.restore(saved[1], 1) == saved[1]
    assert [g.id for g in book.all()] == ["g-1", "g-2", "g-3"]


def test_restore_clamps_the_position_to_the_end():
    book = make_book(Group("g-1", "Sala"))
    book.restore(Group("g-2", "Quarto"), 5)
    assert [g.id for g in book.all()] == ["g-1", "g-2"]


def test_restore_refuses_a_group_that_is_still_in_the_book():
    book = make_book(Group("g-1", "Sala"))
    with pytest.raises(ValueError):
        book.restore(Group("g-1", "Sala"), 0)
    assert len(book.all()) == 1
