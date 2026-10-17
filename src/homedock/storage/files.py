"""Where HomeDock keeps its data (%APPDATA%\\HomeDock) and how files are written safely."""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

APP_FOLDER = "HomeDock"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Every file the app reads or writes lives under ``root``."""

    root: Path

    @classmethod
    def default(cls) -> AppPaths:
        """``%APPDATA%\\HomeDock`` (the roaming profile folder when APPDATA is unset)."""
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return cls(base / APP_FOLDER)

    @property
    def devices_file(self) -> Path:
        return self.root / "devices.json"

    @property
    def config_file(self) -> Path:
        return self.root / "config.json"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` (UTF-8) to a temporary file next to ``path``, then rename it over.

    Readers see either the old or the new content, never a partial file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise
