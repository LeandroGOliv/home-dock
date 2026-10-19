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


@pytest.mark.parametrize(
    "name", ["config.json", "config.corrupt-20261018-120000.json", "homedock.log", "homedock.log.1"]
)
def test_app_data_files_are_blocked_by_name(secret_source, repo, name):
    (repo / name).write_text("{}", encoding="utf-8")
    assert hook.main([name]) == 1


def test_source_with_bom_is_read(secret_source, repo):
    devices = [{"id": FAKE_ID, "key": FAKE_KEY}]
    (secret_source / "devices.json").write_text(json.dumps(devices), encoding="utf-8-sig")
    (repo / "leak.py").write_text(f"KEY = '{FAKE_KEY}'\n", encoding="utf-8")
    assert hook.main(["leak.py"]) == 1


def test_unreadable_source_fails_closed(secret_source, repo, capsys):
    (secret_source / "devices.json").write_text(f'[{{"key": "{FAKE_KEY}"', encoding="utf-8")
    (repo / "clean.py").write_text("print('hello')\n", encoding="utf-8")
    assert hook.main(["clean.py"]) == 1
    captured = capsys.readouterr()
    assert "devices.json" in captured.err
    assert FAKE_KEY not in captured.out + captured.err


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_utf16_file_with_secret_is_blocked(secret_source, repo, encoding):
    (repo / "scan.txt").write_text(f"key: {FAKE_KEY}\n", encoding=encoding)
    assert hook.main(["scan.txt"]) == 1


def test_binary_file_with_secret_is_blocked(secret_source, repo):
    (repo / "dump.bin").write_bytes(b"\x89PNG\x00\xff" + FAKE_ID.encode() + b"\x00\x01")
    assert hook.main(["dump.bin"]) == 1


def test_secret_is_matched_whatever_its_case(secret_source, repo):
    (repo / "leak.py").write_text(f"ID = '{FAKE_ID.upper()}'\n", encoding="utf-8")
    assert hook.main(["leak.py"]) == 1


@pytest.mark.parametrize("written", ["0a:1b:2c:3d:4e:5f", "0A-1B-2C-3D-4E-5F", "0a1b2c3d4e5f"])
def test_mac_is_matched_in_any_notation(secret_source, repo, written):
    devices = [{"id": FAKE_ID, "mac": "0a:1b:2c:3d:4e:5f"}]
    (secret_source / "devices.json").write_text(json.dumps(devices), encoding="utf-8")
    (repo / "leak.py").write_text(f"MAC = '{written}'\n", encoding="utf-8")
    assert hook.main(["leak.py"]) == 1


@pytest.mark.parametrize(
    ("dump", "content", "leaked"),
    [
        ("devices.json", [{"id": FAKE_ID, "last_ip": "203.0.113.70"}], "203.0.113.70"),
        ("tuya-raw.json", {"result": [{"local_key": "rawLocalKey00001"}]}, "rawLocalKey00001"),
        ("tuya-raw.json", {"result": [{"uid": "az0000000000000fake1"}]}, "az0000000000000fake1"),
        ("tuya-raw.json", {"result": [{"owner_id": "100000001"}]}, "100000001"),
        ("tuya-raw.json", {"result": [{"lat": "-12.3456", "lon": "-45.6789"}]}, "-45.6789"),
        ("snapshot.json", {"devices": [{"id": "fakesnapshotid000001"}]}, "fakesnapshotid000001"),
    ],
)
def test_every_wizard_output_is_a_source(secret_source, repo, dump, content, leaked):
    (secret_source / dump).write_text(json.dumps(content), encoding="utf-8")
    (repo / "leak.py").write_text(f"VALUE = '{leaked}'\n", encoding="utf-8")
    assert hook.main(["leak.py"]) == 1


def test_file_named_after_a_secret_is_blocked(secret_source, repo):
    (repo / f"{FAKE_ID}.txt").write_text("notes\n", encoding="utf-8")
    assert hook.main([f"{FAKE_ID}.txt"]) == 1


def test_unreadable_staged_file_is_not_passed_unchecked(secret_source, repo, capsys):
    (repo / "unreadable").mkdir()  # reading it fails like a locked file would
    assert hook.main(["unreadable"]) == 1
    assert "not checked" in capsys.readouterr().err


def test_numeric_location_is_loaded(secret_source, repo):
    raw = {"result": [{"lat": -12.3456, "lon": -45.6789}]}
    (secret_source / "tuya-raw.json").write_text(json.dumps(raw), encoding="utf-8")
    (repo / "leak.py").write_text("WHERE = -45.6789\n", encoding="utf-8")
    assert hook.main(["leak.py"]) == 1


def test_secret_escaped_inside_json_is_blocked(secret_source, repo):
    key = 'fake"Key\12345'
    (secret_source / "devices.json").write_text(json.dumps([{"key": key}]), encoding="utf-8")
    (repo / "dump.json").write_text(json.dumps({"key": key}), encoding="utf-8")
    assert hook.main(["dump.json"]) == 1


@pytest.mark.parametrize(
    "name",
    [
        "devices (1).json",
        "devices.json.bak",
        "tinytuya (1).json",
        "tinytuya.json.bak",
        "tuya-raw (1).json",
        "snapshot (1).json",
        ".env",
        ".env.local",
    ],
)
def test_copies_of_wizard_files_and_env_files_are_blocked_by_name(secret_source, repo, name):
    (repo / name).write_text("{}", encoding="utf-8")
    assert hook.main([name]) == 1


def test_unreadable_source_error_leaves_out_the_home_path(secret_source, repo, capsys):
    (secret_source / "devices.json").write_text("[", encoding="utf-8")
    assert hook.main([]) == 1
    err = capsys.readouterr().err
    assert "devices.json" in err
    assert str(secret_source) not in err  # the full path holds the Windows user name
