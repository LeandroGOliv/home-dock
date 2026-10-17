"""User-defined device groups (e.g. Sala, Quarto). Mixed device types are allowed."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace


def clean_name(name: str) -> str:
    """The trimmed name; raises ``ValueError`` when it is blank."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("name must not be blank")
    return cleaned


def new_uuid() -> str:
    return uuid.uuid4().hex


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
        group = Group(self._new_id(), clean_name(name), _unique(members))
        self._groups[group.id] = group
        return group

    def rename(self, group_id: str, name: str) -> Group:
        return self._store(replace(self.get(group_id), name=clean_name(name)))

    def set_members(self, group_id: str, members: Iterable[str]) -> Group:
        return self._store(replace(self.get(group_id), members=_unique(members)))

    def delete(self, group_id: str) -> None:
        del self._groups[group_id]

    def _store(self, group: Group) -> Group:
        self._groups[group.id] = group
        return group


def _unique(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))
