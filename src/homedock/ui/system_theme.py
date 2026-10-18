"""Following the Windows theme: the Windows mode (light / dark) and the accent colour.

The flyout sits by the taskbar, like the Windows flyouts, so it follows the *Windows* mode
(taskbar, Start), not the mode chosen for apps. Its accent is the shade those flyouts use:
a light one on dark, a dark one on light. Both are read from the registry; Qt is asked for
the same colour scheme, so its own widgets (the tray menu) match. When Windows changes its
colours, Qt sends the app a ``ThemeChange`` event and everything is read again.
"""

from __future__ import annotations

import winreg
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from homedock.ui import theme
from homedock.ui.widgets import restyle_all

PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ACCENT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
# AccentPalette: 8 colours of 4 bytes (R, G, B, unused), from Light3 down to Dark3.
_SHADES = 8
_LIGHT_2, _DARK_1 = 1, 4

type RegistryReader = Callable[[str, str], object | None]


@dataclass(frozen=True)
class WindowsTheme:
    light: bool
    accent: QColor | None  # None when Windows does not say


def read_registry(key: str, name: str) -> object | None:
    """A value under ``HKEY_CURRENT_USER``, or ``None`` when it is missing."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _type = winreg.QueryValueEx(handle, name)
    except OSError:
        return None
    return value


def accent_shade(palette: object, *, light: bool) -> QColor | None:
    """The accent shade of the Windows flyouts in ``AccentPalette``: Light2 on a dark
    theme, Dark1 on a light one; ``None`` when the value is not a palette."""
    if not isinstance(palette, bytes) or len(palette) != 4 * _SHADES:
        return None
    start = 4 * (_DARK_1 if light else _LIGHT_2)
    red, green, blue = palette[start : start + 3]
    return QColor(red, green, blue)


def read_windows_theme(read: RegistryReader = read_registry) -> WindowsTheme:
    """The Windows mode and accent; dark when the registry does not say."""
    light = read(PERSONALIZE_KEY, "SystemUsesLightTheme") == 1
    return WindowsTheme(light, accent_shade(read(ACCENT_KEY, "AccentPalette"), light=light))


class SystemTheme(QObject):
    """Keeps :data:`theme.colors` and Qt's colour scheme in step with Windows, from
    creation until :meth:`stop`. ``changed`` tells that the colours changed (the widgets
    are already restyled)."""

    changed = Signal()

    def __init__(
        self, app: QApplication, read: Callable[[], WindowsTheme] = read_windows_theme
    ) -> None:
        super().__init__(app)
        self._app = app
        self._read = read
        self._apply()
        app.installEventFilter(self)

    def stop(self) -> None:
        self._app.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._app and event.type() == QEvent.Type.ThemeChange:
            self._apply()
        return False

    def _apply(self) -> None:
        windows = self._read()
        scheme = Qt.ColorScheme.Light if windows.light else Qt.ColorScheme.Dark
        hints = self._app.styleHints()
        if hints.colorScheme() != scheme:  # asking sends another ThemeChange, at once
            hints.setColorScheme(scheme)
        accent = windows.accent
        if accent is None:
            accent = self._app.palette().color(QPalette.ColorRole.Accent)
        colors = (theme.LIGHT if windows.light else theme.DARK).with_accent(accent)
        if colors != theme.colors:
            theme.use(colors)
            restyle_all()
            self.changed.emit()
