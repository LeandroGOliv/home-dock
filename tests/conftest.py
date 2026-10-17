import pytest


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    """No test may touch the real %APPDATA%: point it at a temporary folder."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
