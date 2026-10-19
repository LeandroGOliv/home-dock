import inspect
from types import FunctionType, ModuleType

import pytest
from PySide6.QtCore import QCoreApplication

from homedock.devices import DeviceType
from homedock.ui import strings, strings_common, strings_en, strings_pt_br
from homedock.ui.strings import Language

LANGUAGES = {Language.PT_BR: strings_pt_br, Language.EN: strings_en}


def texts(module: ModuleType) -> dict[str, object]:
    """The texts and functions a language module defines (not what it imports)."""
    return {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("_")
        and name not in vars(strings_common)
        and (
            isinstance(value, str)
            or (isinstance(value, FunctionType) and value.__module__ == module.__name__)
        )
    }


@pytest.mark.parametrize(
    ("ui_languages", "language"),
    [
        (["pt-BR"], Language.PT_BR),
        (["pt-Latn-BR", "pt-BR", "pt"], Language.PT_BR),
        (["pt-PT"], Language.PT_BR),
        (["pt"], Language.PT_BR),
        (["PT_br"], Language.PT_BR),
        (["en-US"], Language.EN),
        (["en-Latn-US", "en-US", "pt-Latn-BR", "pt-BR"], Language.EN),  # Windows in English
        (["de-DE"], Language.EN),
        (["ptx"], Language.EN),
        ([], Language.EN),
    ],
)
def test_language_follows_the_first_display_language(ui_languages, language):
    assert strings.language_for(ui_languages) is language


def test_system_language_reads_the_display_language_not_the_region(monkeypatch):
    class Locale:
        @staticmethod
        def system():
            return Locale()

        def uiLanguages(self):  # noqa: N802 (Qt API)
            return ["en-US", "pt-BR"]

    monkeypatch.setattr(strings, "QLocale", Locale)
    assert strings.system_language() is Language.EN


def test_both_languages_have_the_same_texts_and_signatures():
    portuguese, english = texts(strings_pt_br), texts(strings_en)
    assert portuguese.keys() == english.keys()
    for name, value in portuguese.items():
        if isinstance(value, str):
            assert isinstance(english[name], str), name
        else:
            assert inspect.signature(value) == inspect.signature(english[name]), name


@pytest.mark.parametrize("module", LANGUAGES.values(), ids=lambda m: m.__name__)
def test_no_text_is_empty_nor_shadowed_by_the_facade(module):
    for name, value in texts(module).items():
        assert value != "", name
        assert name not in vars(strings), name


def test_the_facade_serves_the_language_in_use():
    strings.use(Language.EN)
    assert strings.language is Language.EN
    assert strings.QUIT == "Quit"
    assert strings.noun(DeviceType.RGB_BULB).everything == "All bulbs"
    assert strings.temperature_label(100) == "Cool"

    strings.use(Language.PT_BR)
    assert strings.language is Language.PT_BR
    assert strings.QUIT == "Sair"
    assert strings.noun(DeviceType.RGB_BULB).everything == "Todas as lâmpadas"
    assert strings.temperature_label(100) == "Frio"


def test_an_unknown_text_is_an_attribute_error():
    with pytest.raises(AttributeError):
        _ = strings.NOT_A_TEXT


def test_english_plurals():
    bulbs = strings_en.noun(DeviceType.RGB_BULB)
    assert strings_en.group_summary(1, None, bulbs) == "Group · 1 bulb"
    assert strings_en.group_summary(3, None, bulbs) == "Group · 3 bulbs"
    assert strings_en.group_summary(3, 2, bulbs) == "Group · 2 of 3 online"
    assert strings_en.device_summary(bulbs, online=False) == "Bulb · offline"
    assert strings_en.device_detail(["Living room"], online=False) == "Living room · offline"
    assert strings_en.also_in(["Bedroom", "Office"]) == "also in Bedroom, Office"
    assert strings_en.members_heading(bulbs) == "Bulbs in this group"
    assert strings_en.devices_reloaded(1, 0, bulbs) == "1 bulb · IPs up to date"
    assert strings_en.devices_reloaded(3, 1, bulbs) == "3 bulbs · 1 IP updated"
    assert strings_en.devices_reloaded(3, 2, bulbs) == "3 bulbs · 2 IPs updated"
    assert strings_en.not_imported(1).startswith("1 Tuya device on the network isn't")
    assert strings_en.not_imported(2).startswith("2 Tuya devices on the network aren't")
    assert strings_en.left_out("Movie", 1, bulbs) == "Movie · 1 offline bulb was left out"
    assert strings_en.left_out("Movie", 2, bulbs) == "Movie · 2 offline bulbs were left out"
    assert strings_en.nothing_saved(2, bulbs) == "Bulbs offline · nothing was saved"
    assert strings_en.new_scene_name(["Scene 1", "Scene 3"]) == "Scene 2"
    assert strings_en.scene_deleted("Scene 1") == "“Scene 1” deleted"
    assert strings_en.group_deleted("Office") == "“Office” deleted"
    assert strings_en.noun(None).everything == "All devices"


@pytest.fixture
def translated(qapp):
    """Installs Qt's own translation for a language; removed again after the test."""
    installed = []

    def install(language: Language):
        strings.use(language)
        translator = strings.install_qt_translation(qapp)
        if translator is not None:
            installed.append(translator)
        return translator

    yield install
    for translator in installed:
        qapp.removeTranslator(translator)


def test_qt_texts_follow_portuguese(translated):
    assert translated(Language.PT_BR) is not None
    assert QCoreApplication.translate("QLineEdit", "Select All") == "Selecionar tudo"


def test_qt_texts_stay_in_english(translated):
    assert translated(Language.EN) is None
    assert QCoreApplication.translate("QLineEdit", "Select All") == "Select All"
