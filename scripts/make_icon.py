"""Write the icon of ``HomeDock.exe`` from the bulb the app paints (the repo has no images).

The ``.ico`` holds one PNG per size, up to the 256 px Explorer uses for large icons.
``packaging/HomeDock.spec`` runs it into the build folder.

Usage::

    uv run python scripts/make_icon.py build\\HomeDock.ico
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from collections.abc import Sequence
from pathlib import Path

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def ico_bytes(images: Sequence[tuple[int, bytes]]) -> bytes:
    """An ICO file of square PNG ``images`` given as ``(size, png)``, at most 256 px."""
    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type 1 = icon, count
    offset = len(header) + 16 * len(images)
    entries = []
    for size, png in images:
        if not 1 <= size <= 256:
            raise ValueError(f"an icon is 1 to 256 px, not {size}")
        side = size % 256  # 0 means 256
        # width, height, palette size, reserved, colour planes, bits per pixel, size, offset
        entries.append(struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset))
        offset += len(png)
    return header + b"".join(entries) + b"".join(png for _size, png in images)


def bulb_pngs(sizes: Sequence[int] = SIZES) -> list[tuple[int, bytes]]:
    """The tray bulb as PNG files (needs a ``QGuiApplication``)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    from homedock.ui.icons import bulb_pixmap

    images = []
    for size in sizes:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not bulb_pixmap(size).save(buffer, "PNG"):
            raise RuntimeError(f"cannot encode the {size} px icon")
        images.append((size, data.data()))
    return images


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="the .ico file to write")
    args = parser.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window, also on a build server
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication.instance() or QGuiApplication([])  # painting needs one
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(ico_bytes(bulb_pngs()))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
