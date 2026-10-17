import logging
import uuid

import pytest


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
