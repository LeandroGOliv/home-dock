"""Every text shown to the user, in the display language of Windows: pt-BR or English.

UI code must not hold string literals of its own: it reads ``strings.QUIT``,
``strings.noun(...)``, … here, served from ``strings_pt_br`` or ``strings_en`` (same names)
by the language in use. The language is the system's when the app starts; it never changes
while it runs (tests pin one with :func:`use`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import StrEnum
from types import ModuleType
from typing import Any

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

from homedock.ui import strings_en, strings_pt_br
from homedock.ui.strings_common import APP_NAME as APP_NAME
from homedock.ui.strings_common import SEPARATOR as SEPARATOR
from homedock.ui.strings_common import Noun as Noun
from homedock.ui.strings_common import percent as percent

log = logging.getLogger(__name__)


class Language(StrEnum):
    PT_BR = "pt-BR"
    EN = "en"


_TEXTS = {Language.PT_BR: strings_pt_br, Language.EN: strings_en}
# Qt's own texts (context menus, standard buttons) are English unless translated.
_QT_TRANSLATIONS = {Language.PT_BR: "qtbase_pt_BR"}


def language_for(ui_languages: Sequence[str]) -> Language:
    """The language of the UI for the user's display languages, preferred first: any
    Portuguese is pt-BR, anything else English."""
    if not ui_languages:
        return Language.EN
    first = ui_languages[0].replace("_", "-").split("-")[0]
    return Language.PT_BR if first.lower() == "pt" else Language.EN


def system_language() -> Language:
    """The language of the UI for the display language of Windows — not its regional
    format: Windows in English with the region set to Brazil gets English."""
    return language_for(QLocale.system().uiLanguages())


language: Language
_texts: ModuleType


def use(chosen: Language) -> None:
    """Serve the texts of ``chosen`` (the widgets built before keep their texts)."""
    global language, _texts
    language, _texts = chosen, _TEXTS[chosen]


def install_qt_translation(app: QCoreApplication) -> QTranslator | None:
    """Translate Qt's own texts into the language in use; ``None`` when they stay English
    (or the translation is missing: only logged)."""
    name = _QT_TRANSLATIONS.get(language)
    if name is None:
        return None
    translator = QTranslator(app)
    if not translator.load(name, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        log.warning("Qt translation %s not found: Qt's own texts stay in English", name)
        return None
    app.installTranslator(translator)
    return translator


def temperature_label(temperature: int) -> str:
    """The kind of white of a colour temperature (0 = warmest, 100 = coldest)."""
    if temperature <= 33:
        return _texts.WARM
    return _texts.COLD if temperature >= 67 else _texts.NEUTRAL


def __getattr__(name: str) -> Any:
    """The text (or text function) ``name`` in the language in use."""
    return getattr(_texts, name)


use(system_language())
