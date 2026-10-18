"""Starting HomeDock with Windows: its entry under the user's ``Run`` registry key.

The registry is the only record of the choice, so the tray check mark always shows what
Windows will do at the next sign-in. It is on when the ``HomeDock`` entry runs *this*
HomeDock (an entry left by an exe that was moved does not count) and Task Manager has not
disabled it (``StartupApproved\\Run``, an odd first byte). Turning it on writes the entry
and clears Task Manager's switch; turning it off removes both. Nothing else is written:
the app's own files stay under ``%APPDATA%\\HomeDock``.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import winreg
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
ENTRY = "HomeDock"


class Registry(Protocol):
    """Values under ``HKEY_CURRENT_USER``."""

    def read(self, key: str, name: str) -> object | None:
        """The value, or ``None`` when it (or its key) is missing or unreadable."""
        ...

    def write(self, key: str, name: str, value: str) -> None:
        """Store a string value, creating the key if needed. Raises ``OSError``."""
        ...

    def delete(self, key: str, name: str) -> None:
        """Remove the value; a missing one is fine. Raises ``OSError``."""
        ...


class UserRegistry:
    """The real ``HKEY_CURRENT_USER`` (no admin rights needed)."""

    def read(self, key: str, name: str) -> object | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value, _type = winreg.QueryValueEx(handle, name)
        except OSError:
            return None
        return value

    def write(self, key: str, name: str, value: str) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)

    def delete(self, key: str, name: str) -> None:
        access = winreg.KEY_SET_VALUE
        with (
            contextlib.suppress(FileNotFoundError),
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, access) as handle,
        ):
            winreg.DeleteValue(handle, name)


def default_registry() -> Registry:
    return UserRegistry()


def launch_command(executable: str | None = None, frozen: bool | None = None) -> str:
    """The command line Windows runs at sign-in for the running HomeDock.

    The built ``HomeDock.exe`` runs itself; from the sources it is ``pythonw -m homedock``
    with the running environment's Python (``pythonw``: no console window).
    """
    path = Path(executable if executable is not None else sys.executable)
    if frozen if frozen is not None else getattr(sys, "frozen", False):
        return f'"{path}"'
    windowless = path.with_name("pythonw.exe")
    if windowless.exists():
        path = windowless
    return f'"{path}" -m homedock'


class StartWithWindows:
    """Reads and changes whether ``command`` (the running HomeDock by default) starts with
    Windows."""

    def __init__(self, command: str | None = None, registry: Registry | None = None) -> None:
        self.command = command if command is not None else launch_command()
        self._registry = registry if registry is not None else default_registry()

    def is_enabled(self) -> bool:
        """Whether Windows will start this HomeDock at sign-in. Never raises."""
        entry = self._registry.read(RUN_KEY, ENTRY)
        if not isinstance(entry, str) or entry.casefold() != self.command.casefold():
            return False
        approved = self._registry.read(APPROVED_KEY, ENTRY)
        return not (isinstance(approved, bytes) and approved and approved[0] & 1)

    def set_enabled(self, enabled: bool) -> None:
        """Write or remove the entry. Raises ``OSError``."""
        if enabled:
            self._registry.write(RUN_KEY, ENTRY, self.command)
        else:
            self._registry.delete(RUN_KEY, ENTRY)
        self._registry.delete(APPROVED_KEY, ENTRY)
        log.info("start with Windows turned %s", "on" if enabled else "off")
