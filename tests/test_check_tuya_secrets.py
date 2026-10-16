import json

import pytest

import check_tuya_secrets as hook

FAKE_KEY = "fakeLocalKey1234"
FAKE_ID = "fakedeviceid00000001"
FAKE_IP = "192.0.2.55"
FAKE_SECRET = "fakeCloudSecret0000"


@pytest.fixture
def secret_source(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    devices = [{"name": "Lamp", "id": FAKE_ID, "key": FAKE_KEY, "ip": FAKE_IP}]
    (source / "devices.json").write_text(json.dumps(devices), encoding="utf-8")
    (source / "tinytuya.json").write_text(json.dumps({"apiSecret": FAKE_SECRET}), encoding="utf-8")
    monkeypatch.setenv("HOMEDOCK_SECRET_SOURCES", str(source))
    return source


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    return repo


def test_clean_file_passes(secret_source, repo):
    (repo / "clean.py").write_text("print('hello')\n", encoding="utf-8")
    assert hook.main(["clean.py"]) == 0


@pytest.mark.parametrize("value", [FAKE_KEY, FAKE_ID, FAKE_IP, FAKE_SECRET])
def test_file_with_real_secret_is_blocked(secret_source, repo, value):
    (repo / "leak.py").write_text(f"VALUE = '{value}'\n", encoding="utf-8")
    assert hook.main(["leak.py"]) == 1


@pytest.mark.parametrize("name", sorted(hook.FORBIDDEN_FILENAMES))
def test_wizard_outputs_are_blocked_by_name(secret_source, repo, name):
    (repo / name).write_text("{}", encoding="utf-8")
    assert hook.main([name]) == 1


def test_example_file_is_allowed(secret_source, repo):
    (repo / "devices.example.json").write_text("[]", encoding="utf-8")
    assert hook.main(["devices.example.json"]) == 0


def test_secret_values_are_never_printed(secret_source, repo, capsys):
    (repo / "leak.py").write_text(f"KEY = '{FAKE_KEY}'\n", encoding="utf-8")
    hook.main(["leak.py"])
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out + captured.err
    assert "key" in captured.err


def test_missing_sources_still_block_by_name(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("HOMEDOCK_SECRET_SOURCES", str(tmp_path / "missing"))
    (repo / "devices.json").write_text("[]", encoding="utf-8")
    assert hook.main(["devices.json"]) == 1
