import logging
import uuid

import pytest


def pytest_configure(config):
    """The tests check pt-BR texts, also at collection: never the language of the machine."""
    from homedock.ui import strings

    strings.use(strings.Language.PT_BR)


@pytest.fixture(autouse=True)
def restore_language():
    """Undo a UI language chosen by a test."""
    from homedock.ui import strings

    language = strings.language
    yield
    strings.use(language)


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    """No test may touch the real %APPDATA%: point it at a temporary folder."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


@pytest.fixture(autouse=True)
def isolated_instance(monkeypatch):
    """Tests starting the app never collide with a HomeDock the developer is running."""
    monkeypatch.setattr("homedock.ui.app.INSTANCE_NAME", rf"Local\HomeDock.Test.{uuid.uuid4().hex}")


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Undo the log handlers installed by the app start-up."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


@pytest.fixture(autouse=True)
def restore_theme():
    """Undo a palette chosen by a test (or by the app following the Windows theme)."""
    from homedock.ui import theme

    colors = theme.colors
    yield
    theme.use(colors)


class MemoryRegistry:
    """An in-memory ``HKEY_CURRENT_USER``: ``values[key, name]``; ``fail`` makes writes fail."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], object] = {}
        self.fail = False

    def read(self, key: str, name: str) -> object | None:
        return self.values.get((key, name))

    def write(self, key: str, name: str, value: str) -> None:
        if self.fail:
            raise PermissionError("access denied")
        self.values[key, name] = value

    def delete(self, key: str, name: str) -> None:
        if self.fail:
            raise PermissionError("access denied")
        self.values.pop((key, name), None)


@pytest.fixture
def registry() -> MemoryRegistry:
    return MemoryRegistry()


@pytest.fixture(autouse=True)
def isolated_registry(registry, monkeypatch):
    """No test may touch the real ``Run`` key: the app's registry is an in-memory one."""
    monkeypatch.setattr("homedock.storage.autostart.default_registry", lambda: registry)
