"""Every text shown to the user, in pt-BR. UI code must not hold string literals of its own."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from homedock.devices import DeviceType

APP_NAME = "HomeDock"

# Tray menu
OPEN_PANEL = "Abrir painel"
TURN_ALL_ON = "Ligar todos"
TURN_ALL_OFF = "Desligar todos"
NO_DEVICES = "Nenhuma lâmpada configurada"
SCENES = "Cenas"
NO_SCENES = "Nenhuma cena salva"
START_WITH_WINDOWS = "Iniciar com o Windows"
QUIT = "Sair"
OFFLINE = "offline"
ONLINE = "online"

# Flyout: target selector
GROUPS = "Grupos"
GROUP = "Grupo"
EMPTY_GROUP = "Vazio"
CHOOSE_TARGET = "Escolher o que controlar"
POWER = "Ligar ou desligar"
MANAGE = "Gerenciar grupos e lâmpadas"

# Flyout: manage page (filled in by the groups issue)
MANAGE_TITLE = "Grupos e lâmpadas"
MANAGE_SOON = "Em breve: criar grupos, renomear lâmpadas e procurar lâmpadas novas."
BACK = "Voltar"

SEPARATOR = " · "

# Control panels: hue ring and temperature arc
HUE = "Cor"
TEMPERATURE = "Temperatura do branco"
WARM = "Quente"
NEUTRAL = "Neutro"
COLD = "Frio"


def percent(value: int) -> str:
    return f"{value}%"


def temperature_label(temperature: int) -> str:
    """The kind of white of a colour temperature (0 = warmest, 100 = coldest)."""
    if temperature <= 33:
        return WARM
    return COLD if temperature >= 67 else NEUTRAL


@dataclass(frozen=True, slots=True)
class Noun:
    """How a device type is called: one device, a section of them, all of them."""

    singular: str
    plural: str
    everything: str


_NOUNS = {DeviceType.RGB_BULB: Noun("Lâmpada", "Lâmpadas", "Todas as lâmpadas")}
_GENERIC = Noun("Dispositivo", "Dispositivos", "Todos os dispositivos")


def noun(device_type: str | None) -> Noun:
    """The words for ``device_type``; generic ones for a type without its own (or None)."""
    return _NOUNS.get(device_type, _GENERIC) if device_type is not None else _GENERIC


def device_label(name: str, online: bool | None) -> str:
    """A device's name, flagged when its last command or read failed."""
    return f"{name}{SEPARATOR}{OFFLINE}" if online is False else name


def group_summary(count: int, online: int | None, words: Noun) -> str:
    """E.g. "Grupo · 2 de 3 online", or "Grupo · 3 lâmpadas" before any member answered."""
    if online is None:
        amount = words.singular if count == 1 else words.plural
        return f"{GROUP}{SEPARATOR}{count} {amount.lower()}"
    return f"{GROUP}{SEPARATOR}{online} de {count} {ONLINE}"


def device_summary(words: Noun, online: bool | None) -> str:
    """E.g. "Lâmpada · online"; just the kind before the first answer."""
    if online is None:
        return words.singular
    return f"{words.singular}{SEPARATOR}{ONLINE if online else OFFLINE}"


def device_detail(groups: Sequence[str], online: bool | None) -> str:
    """The device's groups, e.g. "Sala, Quarto", flagged when it is offline."""
    parts = [", ".join(groups)] if groups else []
    if online is False:
        parts.append(OFFLINE)
    return SEPARATOR.join(parts)
