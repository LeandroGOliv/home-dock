# PyInstaller spec of dist\HomeDock\HomeDock.exe: no console, the painted bulb as its icon
# and the version of the package in its properties. Build from the repository root:
#
#     uv run pyinstaller packaging/HomeDock.spec
#
# One folder, not one file: the exe loads its libraries from _internal\ next to it instead
# of unpacking them into a temporary folder at every start (about 4x faster, issue #35).
# The folder bundles code and libraries only: devices.json, config.json and the logs stay
# in %APPDATA%\HomeDock, and the build stops if any local data file would be bundled.

import os
import re
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "src"))
from homedock import __version__  # noqa: E402

NAME = "HomeDock"
ICON = Path(workpath) / f"{NAME}.ico"
subprocess.run([sys.executable, str(ROOT / "scripts" / "make_icon.py"), str(ICON)], check=True)

numbers = tuple(int(part) for part in __version__.split("."))
numbers = (numbers + (0, 0, 0, 0))[:4]
VERSION = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "041604B0",  # pt-BR, Unicode
                    [
                        StringStruct("CompanyName", "Leandro Golub de Oliveira"),
                        StringStruct("FileDescription", NAME),
                        StringStruct("FileVersion", __version__),
                        StringStruct("InternalName", NAME),
                        StringStruct("LegalCopyright", "© 2026 Leandro Golub de Oliveira · MIT"),
                        StringStruct("OriginalFilename", f"{NAME}.exe"),
                        StringStruct("ProductName", NAME),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "src" / "homedock" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    excludes=[
        "tkinter",
        # Build tools nothing imports at run time (PyInstaller's setuptools hook pulls them in).
        *("setuptools", "pkg_resources", "_distutils_hack", "distutils"),
        # A Qt module HomeDock never imports (PyInstaller's PySide6 analysis pulls it in, with
        # its TLS plugins and OpenSSL).
        "PySide6.QtNetwork",
        # tinytuya's cloud client: HomeDock never goes to the cloud. tinytuya imports it only
        # if present (it then warns on stdout, which a windowed exe does not have).
        "requests",
        # A dev dependency (scripts/perf_probe.py) tinytuya's scanner would use if present: the
        # exe keeps the scanner's code path of a plain install.
        "psutil",
    ],
)

# Leave out the Qt plugins and translations HomeDock never loads (it paints its widgets and
# icons: no image formats, no OpenGL) and keep only these: less to load and to copy.
QT_NEEDED = {
    "qwindows.dll",  # the Windows platform
    "qmodernwindowsstyle.dll",  # the Windows 11 style of the tray menu
    "qtbase_pt_BR.qm",  # Qt's own texts in pt-BR (ui.strings.install_qt_translation)
}
QT_UNUSED_LIBRARIES = {"opengl32sw.dll", "Qt6Svg.dll", "Qt6Network.dll"}


def unused_qt(name):
    path = Path(name)
    if path.parts[:1] != ("PySide6",):
        return False
    if path.parts[1:2] in (("plugins",), ("translations",)):
        return path.name not in QT_NEEDED
    return path.name in QT_UNUSED_LIBRARIES


a.binaries = [entry for entry in a.binaries if not unused_qt(entry[0])]
a.datas = [entry for entry in a.datas if not unused_qt(entry[0])]

# Never bundle local data: the wizard's files, HomeDock's own files, environment files,
# anything from the folders that hold them.
LOCAL_DATA = re.compile(
    r"(devices|config|tinytuya|tuya-raw|snapshot)(\.corrupt-.*)?\.json|.*\.log(\.\d+)?"
    r"|\.env(\..*)?|config\.local\..*",
    re.IGNORECASE,
)
LOCAL_FOLDERS = [
    Path(os.environ[variable]) / folder
    for variable, folder in (("APPDATA", "HomeDock"), ("USERPROFILE", "tuya-wizard"))
    if variable in os.environ
]
leaked = [
    name
    for name, source, _kind in a.datas + a.binaries
    if LOCAL_DATA.fullmatch(Path(name).name)
    or any(Path(source).is_relative_to(folder) for folder in LOCAL_FOLDERS)
]
if leaked:
    raise SystemExit(f"refusing to bundle local data files: {sorted(leaked)}")

# PyInstaller's Qt hooks collect the plugins and translations next to the Qt libraries,
# where Qt looks for them; without these the app would not start, or Qt's own texts would
# stay English.
bundled = {Path(name).name for name, _source, _kind in a.datas + a.binaries}
if QT_NEEDED - bundled:
    raise SystemExit(f"Qt files HomeDock needs would not be bundled: {sorted(QT_NEEDED - bundled)}")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    icon=str(ICON),
    version=VERSION,
    console=False,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
