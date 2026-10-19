# PyInstaller spec of dist\HomeDock.exe: one file, no console, the painted bulb as its icon
# and the version of the package in its properties. Build from the repository root:
#
#     uv run pyinstaller packaging/HomeDock.spec
#
# The exe bundles code and libraries only: devices.json, config.json and the logs stay in
# %APPDATA%\HomeDock, and the build stops if any local data file would be bundled.

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
    # Build tools nothing imports at run time (PyInstaller's setuptools hook pulls them in).
    excludes=["tkinter", "setuptools", "pkg_resources", "_distutils_hack", "distutils"],
)

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

# Qt's own texts in pt-BR (ui.strings.install_qt_translation): PyInstaller's Qt hooks
# collect the translations next to the Qt libraries, where QLibraryInfo looks for them.
QT_TRANSLATION = "qtbase_pt_BR.qm"
if not any(Path(name).name == QT_TRANSLATION for name, _source, _kind in a.datas + a.binaries):
    raise SystemExit(f"{QT_TRANSLATION} would not be bundled: Qt's texts would stay English")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    icon=str(ICON),
    version=VERSION,
    console=False,
    upx=False,
)
