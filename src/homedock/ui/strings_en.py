"""The texts of the UI in English. Same names as ``strings_pt_br``; UI code reads them through
``homedock.ui.strings``."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from homedock.devices import DeviceType
from homedock.ui.strings_common import SEPARATOR, Noun

# Tray menu
OPEN_PANEL = "Open panel"
TURN_ALL_ON = "Turn all on"
TURN_ALL_OFF = "Turn all off"
NO_DEVICES = "No bulbs set up"
SCENES = "Scenes"
NO_SCENES = "No saved scenes"
START_WITH_WINDOWS = "Start with Windows"
QUIT = "Quit"
OFFLINE = "offline"
ONLINE = "online"

# Flyout: target selector
GROUPS = "Groups"
GROUP = "Group"
EMPTY_GROUP = "Empty"
CHOOSE_TARGET = "Choose what to control"
POWER = "Turn on or off"
MANAGE = "Manage groups and bulbs"

# Flyout: manage pages (groups and devices)
MANAGE_TITLE = "Groups and bulbs"
BACK = "Back"
USER_GROUPS = "Groups (rooms)"
NEW_GROUP = "+ New group"
NO_GROUPS = "No groups yet"
AUTOMATIC_GROUP_HINT = '"All bulbs" is automatic and always includes every bulb.'
DEVICE_NAME = "New name"
FIND_DEVICES = "Find new bulbs"
FINDING_DEVICES = "Looking for bulbs on the network…"
NAME_SAVE_FAILED = "Couldn't save the name"
EDIT_GROUP = "Edit group"
NEW_GROUP_TITLE = "New group"
GROUP_NAME = "Group name"
MANY_GROUPS_HINT = "A bulb can be in more than one group."
DELETE_GROUP = "Delete group"
GROUPS_SAVE_FAILED = "Couldn't save the groups"
DEVICES_MISSING = "devices.json not found · see the HomeDock setup"
DEVICES_UNREADABLE = "Couldn't read devices.json"
SCAN_FAILED = "Couldn't search the network"
IPS_NOT_SAVED = "couldn't save the new IPs"

# Flyout: scenes
SAVE_CURRENT = "+ Save current"
SCENE_NAME = "Scene name"
SAVE = "Save"
CANCEL = "Cancel"
RENAME = "Rename"
OVERWRITE = "Overwrite with the current state"
DELETE = "Delete"
UNDO = "Undo"
SAVE_FAILED = "Couldn't save the scenes"

# Control panels: the bulb panel, hue ring and temperature arc
WHITE_MODE = "White"
COLOR_MODE = "Color"
BRIGHTNESS = "Brightness"
SATURATION = "Saturation"
HUE = "Color"
TEMPERATURE = "White temperature"
WARM = "Warm"
NEUTRAL = "Neutral"
COLD = "Cool"


_NOUNS = {DeviceType.RGB_BULB: Noun("Bulb", "Bulbs", "All bulbs")}
_GENERIC = Noun("Device", "Devices", "All devices")


def noun(device_type: str | None) -> Noun:
    """The words for ``device_type``; generic ones for a type without its own (or None)."""
    return _NOUNS.get(device_type, _GENERIC) if device_type is not None else _GENERIC


def device_label(name: str, online: bool | None) -> str:
    """A device's name, flagged when its last command or read failed."""
    return f"{name}{SEPARATOR}{OFFLINE}" if online is False else name


def group_summary(count: int, online: int | None, words: Noun) -> str:
    """E.g. "Group · 2 of 3 online", or "Group · 3 bulbs" before any member answered."""
    if online is None:
        amount = words.singular if count == 1 else words.plural
        return f"{GROUP}{SEPARATOR}{count} {amount.lower()}"
    return f"{GROUP}{SEPARATOR}{online} of {count} {ONLINE}"


def device_summary(words: Noun, online: bool | None) -> str:
    """E.g. "Bulb · online"; just the kind before the first answer."""
    if online is None:
        return words.singular
    return f"{words.singular}{SEPARATOR}{ONLINE if online else OFFLINE}"


def device_detail(groups: Sequence[str], online: bool | None) -> str:
    """The device's groups, e.g. "Living room, Bedroom", flagged when it is offline."""
    parts = [", ".join(groups)] if groups else []
    if online is False:
        parts.append(OFFLINE)
    return SEPARATOR.join(parts)


def also_in(groups: Sequence[str]) -> str:
    """The other groups of a device, e.g. "also in Bedroom"."""
    return f"also in {', '.join(groups)}" if groups else ""


def members_heading(words: Noun) -> str:
    """E.g. "Bulbs in this group"."""
    return f"{words.plural} in this group"


def group_deleted(group: str) -> str:
    """E.g. "“Living room” deleted"."""
    return f"“{group}” deleted"


def devices_reloaded(count: int, updated_ips: int, words: Noun) -> str:
    """E.g. "2 bulbs · 1 IP updated", or "2 bulbs · IPs up to date"."""
    amount = f"{count} {(words.singular if count == 1 else words.plural).lower()}"
    if updated_ips == 0:
        return f"{amount}{SEPARATOR}IPs up to date"
    ips = "1 IP updated" if updated_ips == 1 else f"{updated_ips} IPs updated"
    return f"{amount}{SEPARATOR}{ips}"


def not_imported(count: int) -> str:
    """Tuya devices on the network that devices.json does not list."""
    if count == 1:
        return "1 Tuya device on the network isn't in devices.json: run the wizard again."
    return f"{count} Tuya devices on the network aren't in devices.json: run the wizard again."


def new_scene_name(taken: Iterable[str]) -> str:
    """The suggested name of a new scene: "Scene 1", or the next number not taken."""
    names = set(taken)
    number = 1
    while f"Scene {number}" in names:
        number += 1
    return f"Scene {number}"


def left_out(scene: str, count: int, words: Noun) -> str:
    """E.g. "Reading · 1 offline bulb was left out"."""
    if count == 1:
        return f"{scene}{SEPARATOR}1 {OFFLINE} {words.singular.lower()} was left out"
    return f"{scene}{SEPARATOR}{count} {OFFLINE} {words.plural.lower()} were left out"


def nothing_saved(count: int, words: Noun) -> str:
    """No device answered, e.g. "Bulbs offline · nothing was saved"."""
    return f"{words.singular if count == 1 else words.plural} {OFFLINE}{SEPARATOR}nothing was saved"


def scene_deleted(scene: str) -> str:
    """E.g. "“Scene 1” deleted" (quoted: default names already start with "Scene")."""
    return f"“{scene}” deleted"
