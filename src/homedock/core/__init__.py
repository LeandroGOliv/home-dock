"""Control service, groups, targets and scenes. Works with generic devices only."""

from homedock.core.control import CommandResult, ControlService, ServiceClosedError
from homedock.core.events import Event
from homedock.core.groups import Group, GroupBook
from homedock.core.recovery import Recovery
from homedock.core.scenes import Scene, SceneBook
from homedock.core.targets import Target, TargetKind, available_targets, resolve

__all__ = [
    "CommandResult",
    "ControlService",
    "Event",
    "Group",
    "GroupBook",
    "Recovery",
    "Scene",
    "SceneBook",
    "ServiceClosedError",
    "Target",
    "TargetKind",
    "available_targets",
    "resolve",
]
