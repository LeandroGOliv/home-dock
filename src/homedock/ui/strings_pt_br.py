"""The texts of the UI in pt-BR. Same names as ``strings_en``; UI code reads them through
``homedock.ui.strings``."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from homedock.devices import DeviceType
from homedock.ui.strings_common import SEPARATOR, Noun

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

# Flyout: manage pages (groups and devices)
MANAGE_TITLE = "Grupos e lâmpadas"
BACK = "Voltar"
USER_GROUPS = "Grupos (cômodos)"
NEW_GROUP = "+ Novo grupo"
NO_GROUPS = "Nenhum grupo criado"
AUTOMATIC_GROUP_HINT = '"Todas as lâmpadas" é automático e sempre inclui todas.'
DEVICE_NAME = "Novo nome"
FIND_DEVICES = "Procurar lâmpadas novas"
FINDING_DEVICES = "Procurando lâmpadas na rede…"
NAME_SAVE_FAILED = "Não foi possível salvar o nome"
EDIT_GROUP = "Editar grupo"
NEW_GROUP_TITLE = "Novo grupo"
GROUP_NAME = "Nome do grupo"
MANY_GROUPS_HINT = "Uma lâmpada pode estar em mais de um grupo."
DELETE_GROUP = "Excluir grupo"
GROUPS_SAVE_FAILED = "Não foi possível salvar os grupos"
DEVICES_MISSING = "devices.json não encontrado · veja a configuração do HomeDock"
DEVICES_UNREADABLE = "Não foi possível ler o devices.json"
SCAN_FAILED = "Não foi possível procurar na rede"
IPS_NOT_SAVED = "não foi possível salvar os IPs novos"

# Flyout: scenes
SAVE_CURRENT = "+ Salvar atual"
SCENE_NAME = "Nome da cena"
SAVE = "Salvar"
CANCEL = "Cancelar"
RENAME = "Renomear"
OVERWRITE = "Sobrescrever com o estado atual"
DELETE = "Excluir"
UNDO = "Desfazer"
SAVE_FAILED = "Não foi possível salvar as cenas"

# Control panels: the bulb panel, hue ring and temperature arc
WHITE_MODE = "Branco"
COLOR_MODE = "Cor"
BRIGHTNESS = "Brilho"
SATURATION = "Saturação"
HUE = "Cor"
TEMPERATURE = "Temperatura do branco"
WARM = "Quente"
NEUTRAL = "Neutro"
COLD = "Frio"


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


def also_in(groups: Sequence[str]) -> str:
    """The other groups of a device, e.g. "também em Quarto"."""
    return f"também em {', '.join(groups)}" if groups else ""


def members_heading(words: Noun) -> str:
    """E.g. "Lâmpadas neste grupo"."""
    return f"{words.plural} neste grupo"


def group_deleted(group: str) -> str:
    """E.g. "“Sala” excluído"."""
    return f"“{group}” excluído"


def devices_reloaded(count: int, updated_ips: int, words: Noun) -> str:
    """E.g. "2 lâmpadas · 1 IP atualizado", or "2 lâmpadas · IPs em dia"."""
    amount = f"{count} {(words.singular if count == 1 else words.plural).lower()}"
    if updated_ips == 0:
        return f"{amount}{SEPARATOR}IPs em dia"
    ips = "1 IP atualizado" if updated_ips == 1 else f"{updated_ips} IPs atualizados"
    return f"{amount}{SEPARATOR}{ips}"


def not_imported(count: int) -> str:
    """Tuya devices on the network that devices.json does not list."""
    if count == 1:
        return "1 dispositivo Tuya na rede não está no devices.json: rode o wizard de novo."
    return f"{count} dispositivos Tuya na rede não estão no devices.json: rode o wizard de novo."


def new_scene_name(taken: Iterable[str]) -> str:
    """The suggested name of a new scene: "Cena 1", or the next number not taken."""
    names = set(taken)
    number = 1
    while f"Cena {number}" in names:
        number += 1
    return f"Cena {number}"


def left_out(scene: str, count: int, words: Noun) -> str:
    """E.g. "Leitura · 1 lâmpada offline ficou de fora"."""
    if count == 1:
        return f"{scene}{SEPARATOR}1 {words.singular.lower()} {OFFLINE} ficou de fora"
    return f"{scene}{SEPARATOR}{count} {words.plural.lower()} {OFFLINE} ficaram de fora"


def nothing_saved(count: int, words: Noun) -> str:
    """No device answered, e.g. "Lâmpadas offline · nada foi salvo"."""
    return f"{words.singular if count == 1 else words.plural} {OFFLINE}{SEPARATOR}nada foi salvo"


def scene_deleted(scene: str) -> str:
    """E.g. "“Cena 1” excluída" (quoted: default names already start with "Cena")."""
    return f"“{scene}” excluída"
