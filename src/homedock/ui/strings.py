"""Every text shown to the user, in pt-BR. UI code must not hold string literals of its own."""

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

# Flyout (placeholder until the flyout issue)
FLYOUT_PLACEHOLDER = "O painel de controle chega em breve.\nUse o menu do ícone por enquanto."


def device_label(name: str, online: bool | None) -> str:
    """A device's name, flagged when its last command or read failed."""
    return f"{name} · {OFFLINE}" if online is False else name
