"""What the texts of every language share: the app name, the separator and the device nouns."""

from __future__ import annotations

from dataclasses import dataclass

APP_NAME = "HomeDock"

SEPARATOR = " · "


def percent(value: int) -> str:
    return f"{value}%"


@dataclass(frozen=True, slots=True)
class Noun:
    """How a device type is called: one device, a section of them, all of them."""

    singular: str
    plural: str
    everything: str
