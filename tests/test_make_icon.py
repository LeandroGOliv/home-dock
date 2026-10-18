"""The icon of HomeDock.exe, written from the painted tray bulb."""

import struct

import pytest
from PySide6.QtGui import QImage

from make_icon import SIZES, bulb_pngs, ico_bytes, main

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def entries(ico: bytes) -> list[tuple[int, bytes]]:
    """Read an ICO back: ``(size, image data)`` per entry, checking the fixed fields."""
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    assert (reserved, kind) == (0, 1)
    found = []
    for index in range(count):
        width, height, colors, zero, planes, bits, size, offset = struct.unpack_from(
            "<BBBBHHII", ico, 6 + 16 * index
        )
        assert (width, colors, zero, planes, bits) == (height, 0, 0, 1, 32)
        found.append((width or 256, ico[offset : offset + size]))
    return found


def test_an_ico_lists_each_image_after_the_directory():
    images = [(16, b"sixteen"), (256, b"two-five-six")]
    ico = ico_bytes(images)

    assert entries(ico) == images
    assert len(ico) == 6 + 2 * 16 + len(b"sixteen") + len(b"two-five-six")


@pytest.mark.parametrize("size", [0, 257])
def test_an_ico_image_is_at_most_256_px(size):
    with pytest.raises(ValueError):
        ico_bytes([(size, b"png")])


def test_the_bulb_is_painted_at_every_size(qapp):
    images = bulb_pngs()

    assert [size for size, _png in images] == list(SIZES)
    for size, png in images:
        assert png.startswith(PNG_SIGNATURE)
        image = QImage.fromData(png, "PNG")
        assert (image.width(), image.height()) == (size, size)
        assert image.pixelColor(size // 2, size // 3).alpha() > 0  # the glass, not empty


def test_main_writes_the_ico_file(qapp, tmp_path, capsys):
    output = tmp_path / "build" / "HomeDock.ico"

    assert main([str(output)]) == 0

    assert [size for size, _png in entries(output.read_bytes())] == list(SIZES)
    assert "HomeDock.ico" in capsys.readouterr().out
