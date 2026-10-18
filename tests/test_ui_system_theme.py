"""Following the Windows mode (light / dark) and accent colour, live."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from homedock.ui import theme
from homedock.ui.system_theme import (
    ACCENT_KEY,
    PERSONALIZE_KEY,
    SystemTheme,
    WindowsTheme,
    accent_shade,
    read_registry,
    read_windows_theme,
)
from homedock.ui.widgets import label

# Windows' default blue, as AccentPalette stores it: Light3, Light2, Light1, the accent,
# Dark1, Dark2, Dark3 and one unused entry, 4 bytes (R, G, B, unused) each.
DEFAULT_PALETTE = bytes.fromhex(
    "9CEBFF00 40BDFF00 007FDC00 0063B100 0055A100 00337C00 00145A00 00CC6A00"
)
BLUE_ON_DARK, BLUE_ON_LIGHT = QColor("#40BDFF"), QColor("#0055A1")


def registry(**values: object):
    """A fake registry reader over ``{name: value}`` (the key is checked too)."""
    keys = {
        "SystemUsesLightTheme": PERSONALIZE_KEY,
        "AppsUseLightTheme": PERSONALIZE_KEY,
        "AccentPalette": ACCENT_KEY,
    }

    def read(key: str, name: str) -> object | None:
        assert keys[name] == key
        return values.get(name)

    return read


# --- the registry -------------------------------------------------------------------------


def test_the_flyouts_use_the_second_lightest_shade_on_dark():
    assert accent_shade(DEFAULT_PALETTE, light=False) == BLUE_ON_DARK


def test_the_flyouts_use_the_first_dark_shade_on_light():
    assert accent_shade(DEFAULT_PALETTE, light=True) == BLUE_ON_LIGHT


@pytest.mark.parametrize("value", [None, b"", DEFAULT_PALETTE[:16], 7, "0063B1"])
def test_a_missing_or_odd_palette_gives_no_accent(value):
    assert accent_shade(value, light=False) is None


def test_the_windows_mode_decides_light_or_dark():
    light = read_windows_theme(registry(SystemUsesLightTheme=1, AccentPalette=DEFAULT_PALETTE))
    assert light == WindowsTheme(light=True, accent=BLUE_ON_LIGHT)
    dark = read_windows_theme(registry(SystemUsesLightTheme=0, AccentPalette=DEFAULT_PALETTE))
    assert dark == WindowsTheme(light=False, accent=BLUE_ON_DARK)


def test_the_app_mode_is_ignored():
    """The flyout sits by the taskbar, like the Windows flyouts: it follows the Windows
    mode, not the mode chosen for apps."""
    windows = read_windows_theme(registry(SystemUsesLightTheme=0, AppsUseLightTheme=1))
    assert not windows.light


def test_without_registry_values_the_theme_is_dark_and_the_accent_unknown():
    assert read_windows_theme(registry()) == WindowsTheme(light=False, accent=None)


def test_reading_a_missing_registry_value_gives_none():
    assert read_registry(r"Software\HomeDock\Test\Missing", "Missing") is None


# --- following the theme ------------------------------------------------------------------


class FakeWindows:
    def __init__(self, light: bool = False, accent: str | None = "#40BDFF") -> None:
        self.theme = WindowsTheme(light, QColor(accent) if accent else None)

    def set(self, light: bool, accent: str | None) -> None:
        self.theme = WindowsTheme(light, QColor(accent) if accent else None)

    def read(self) -> WindowsTheme:
        return self.theme


@pytest.fixture
def follow(qapp):
    created: list[SystemTheme] = []

    def make(windows: FakeWindows) -> SystemTheme:
        system_theme = SystemTheme(qapp, read=windows.read)
        created.append(system_theme)
        return system_theme

    yield make
    for system_theme in created:
        system_theme.stop()
    qapp.styleHints().unsetColorScheme()


def windows_changed_theme() -> None:
    QApplication.sendEvent(QApplication.instance(), QEvent(QEvent.Type.ThemeChange))


def test_the_windows_theme_is_used_from_the_start(follow):
    follow(FakeWindows(light=True, accent="#0055A1"))
    assert theme.colors == theme.LIGHT.with_accent(QColor("#0055A1"))


def test_qt_is_asked_for_the_same_colour_scheme(follow, qapp):
    """Qt's own widgets (the tray menu) then match the flyout."""
    if qapp.platformName() == "offscreen":
        pytest.skip("the offscreen platform ignores colour scheme requests")
    windows = FakeWindows(light=True)
    follow(windows)
    assert qapp.styleHints().colorScheme() == Qt.ColorScheme.Light
    windows.set(light=False, accent="#40BDFF")
    windows_changed_theme()
    assert qapp.styleHints().colorScheme() == Qt.ColorScheme.Dark


def test_a_new_windows_theme_restyles_the_widgets(follow, qtbot):
    windows = FakeWindows(light=False, accent="#40BDFF")
    system_theme = follow(windows)
    title = label("Cenas", theme.font())
    qtbot.addWidget(title)

    windows.set(light=True, accent="#0055A1")
    with qtbot.waitSignal(system_theme.changed, timeout=1000):
        windows_changed_theme()

    assert theme.colors == theme.LIGHT.with_accent(QColor("#0055A1"))
    assert title.palette().color(title.foregroundRole()) == theme.LIGHT.text


def test_a_new_accent_alone_is_followed(follow, qtbot):
    windows = FakeWindows(light=False, accent="#40BDFF")
    system_theme = follow(windows)

    windows.set(light=False, accent="#FFB900")
    with qtbot.waitSignal(system_theme.changed, timeout=1000):
        windows_changed_theme()

    assert theme.colors.accent == QColor("#FFB900")
    assert theme.colors.window == theme.DARK.window


def test_nothing_is_restyled_when_the_colours_stay_the_same(follow, qtbot):
    system_theme = follow(FakeWindows(light=False, accent="#40BDFF"))
    with qtbot.assertNotEmitted(system_theme.changed):
        windows_changed_theme()


def test_without_an_accent_from_windows_qt_s_is_used(follow, qapp):
    follow(FakeWindows(light=False, accent=None))
    assert theme.colors.accent == qapp.palette().color(QPalette.ColorRole.Accent)


def test_after_stop_windows_changes_are_ignored(follow):
    windows = FakeWindows(light=False)
    follow(windows).stop()

    windows.set(light=True, accent="#0055A1")
    windows_changed_theme()

    assert theme.colors == theme.DARK.with_accent(QColor("#40BDFF"))
