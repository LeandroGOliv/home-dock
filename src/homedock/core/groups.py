"""User-defined device groups (e.g. Sala, Quarto). Mixed device types are allowed."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from homedock.core.naming import clean_name, new_uuid


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    name: str
    members: tuple[str, ...] = ()


class GroupBook:
    """The user's groups, in creation order. A device may belong to many groups."""

    def __init__(self, groups: Iterable[Group] = (), new_id: Callable[[], str] = new_uuid) -> None:
        self._groups = {group.id: group for group in groups}
        self._new_id = new_id

    def all(self) -> list[Group]:
        return list(self._groups.values())

    def get(self, group_id: str) -> Group:
        return self._groups[group_id]

    def groups_of(self, device_id: str) -> list[Group]:
        return [group for group in self._groups.values() if device_id in group.members]

    def create(self, name: str, members: Iterable[str] = ()) -> Group:
        name = clean_name(name)
        return self._store(Group(self._new_id(), name, _unique(members)))

    def rename(self, group_id: str, name: str) -> Group:
        return self._store(replace(self.get(group_id), name=clean_name(name)))

    def set_members(self, group_id: str, members: Iterable[str]) -> Group:
        return self._store(replace(self.get(group_id), members=_unique(members)))

    def delete(self, group_id: str) -> None:
        del self._groups[group_id]

    def restore(self, group: Group, index: int) -> Group:
        """Put a deleted ``group`` back at ``index`` (undo); raises if it is still here."""
        if group.id in self._groups:
            raise ValueError("group is already in the book")
        groups = self.all()
        groups.insert(index, group)
        self._groups = {g.id: g for g in groups}
        return group

    def _store(self, group: Group) -> Group:
        self._groups[group.id] = group
        return group


def _unique(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))
