"""Scenes: named snapshots of device states, generic per capability."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

from homedock.core.naming import clean_name, new_uuid
from homedock.devices import DeviceState


@dataclass(frozen=True, slots=True)
class Scene:
    """``devices`` maps a device id to the state to restore (only captured values set)."""

    id: str
    name: str
    devices: Mapping[str, DeviceState] = field(default_factory=dict)


class SceneBook:
    """The user's scenes, in creation order."""

    def __init__(self, scenes: Iterable[Scene] = (), new_id: Callable[[], str] = new_uuid) -> None:
        self._scenes = {scene.id: scene for scene in scenes}
        self._new_id = new_id

    def all(self) -> list[Scene]:
        return list(self._scenes.values())

    def get(self, scene_id: str) -> Scene:
        return self._scenes[scene_id]

    def create(self, name: str, snapshot: Mapping[str, DeviceState]) -> Scene:
        name = clean_name(name)
        return self._store(Scene(self._new_id(), name, dict(snapshot)))

    def rename(self, scene_id: str, name: str) -> Scene:
        return self._store(replace(self.get(scene_id), name=clean_name(name)))

    def overwrite(self, scene_id: str, snapshot: Mapping[str, DeviceState]) -> Scene:
        return self._store(replace(self.get(scene_id), devices=dict(snapshot)))

    def delete(self, scene_id: str) -> None:
        del self._scenes[scene_id]

    def _store(self, scene: Scene) -> Scene:
        self._scenes[scene.id] = scene
        return scene
