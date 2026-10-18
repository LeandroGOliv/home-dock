"""Starting with Windows: the HomeDock entry under the user's ``Run`` registry key."""

import contextlib
import uuid
import winreg

import pytest

from homedock.storage import autostart
from homedock.storage.autostart import (
    APPROVED_KEY,
    ENTRY,
    RUN_KEY,
    StartWithWindows,
    UserRegistry,
    launch_command,
)

COMMAND = r'"C:\Apps\HomeDock\HomeDock.exe"'
# StartupApproved\Run: Task Manager's switch, 12 bytes; an odd first byte means disabled.
APPROVED = bytes.fromhex("020000000000000000000000")
DISABLED = bytes.fromhex("030000000000000000000000")


@pytest.fixture
def start(registry) -> StartWithWindows:
    return StartWithWindows(COMMAND, registry)


# --- the command Windows runs ---------------------------------------------------------------


def test_the_built_exe_starts_itself():
    exe = r"C:\Apps\HomeDock\HomeDock.exe"
    assert launch_command(exe, frozen=True) == f'"{exe}"'


def test_from_the_sources_it_starts_the_module_without_a_console(tmp_path):
    python = tmp_path / "python.exe"
    (tmp_path / "pythonw.exe").touch()

    assert launch_command(str(python), frozen=False) == f'"{tmp_path / "pythonw.exe"}" -m homedock'


def test_from_the_sources_without_pythonw_it_uses_the_same_python(tmp_path):
    python = tmp_path / "python.exe"
    assert launch_command(str(python), frozen=False) == f'"{python}" -m homedock'


def test_the_default_command_is_the_running_python(monkeypatch, tmp_path):
    python = tmp_path / "python.exe"
    monkeypatch.setattr(autostart.sys, "executable", str(python))
    monkeypatch.delattr(autostart.sys, "frozen", raising=False)

    assert StartWithWindows(registry=None).command == f'"{python}" -m homedock'


# --- reading the real state -----------------------------------------------------------------


def test_off_when_there_is_no_entry(start):
    assert not start.is_enabled()


def test_on_when_the_entry_runs_this_homedock(start, registry):
    registry.values[RUN_KEY, ENTRY] = COMMAND
    assert start.is_enabled()


def test_the_comparison_ignores_letter_case(start, registry):
    registry.values[RUN_KEY, ENTRY] = COMMAND.upper()
    assert start.is_enabled()


@pytest.mark.parametrize("value", [r'"D:\Old\HomeDock.exe"', 1, b"\x00"])
def test_off_when_the_entry_runs_something_else(start, registry, value):
    # E.g. the exe was moved: Windows would run a file that is not there.
    registry.values[RUN_KEY, ENTRY] = value
    assert not start.is_enabled()


def test_off_when_task_manager_disabled_it(start, registry):
    registry.values[RUN_KEY, ENTRY] = COMMAND
    registry.values[APPROVED_KEY, ENTRY] = DISABLED
    assert not start.is_enabled()


def test_on_when_task_manager_approved_it(start, registry):
    registry.values[RUN_KEY, ENTRY] = COMMAND
    registry.values[APPROVED_KEY, ENTRY] = APPROVED
    assert start.is_enabled()


# --- changing it ----------------------------------------------------------------------------


def test_enabling_writes_the_entry(start, registry):
    start.set_enabled(True)

    assert registry.values == {(RUN_KEY, ENTRY): COMMAND}
    assert start.is_enabled()


def test_enabling_overrides_task_manager(start, registry):
    registry.values[APPROVED_KEY, ENTRY] = DISABLED
    start.set_enabled(True)

    assert (APPROVED_KEY, ENTRY) not in registry.values
    assert start.is_enabled()


def test_enabling_replaces_an_entry_for_another_path(start, registry):
    registry.values[RUN_KEY, ENTRY] = r'"D:\Old\HomeDock.exe"'
    start.set_enabled(True)
    assert registry.values[RUN_KEY, ENTRY] == COMMAND


def test_disabling_removes_the_entry_and_the_task_manager_switch(start, registry):
    registry.values[RUN_KEY, ENTRY] = COMMAND
    registry.values[APPROVED_KEY, ENTRY] = APPROVED
    registry.values[RUN_KEY, "Other app"] = r'"C:\Other.exe"'

    start.set_enabled(False)

    assert registry.values == {(RUN_KEY, "Other app"): r'"C:\Other.exe"'}
    assert not start.is_enabled()


def test_disabling_without_an_entry_changes_nothing(start, registry):
    start.set_enabled(False)
    assert registry.values == {}


def test_a_failed_write_raises_os_error(start, registry):
    registry.fail = True
    with pytest.raises(OSError):
        start.set_enabled(True)
    assert not start.is_enabled()


# --- the real registry (a scratch key, never Run) -------------------------------------------


@pytest.fixture
def scratch_key():
    key = rf"Software\HomeDock.Test.{uuid.uuid4().hex}"
    yield key
    for path in (rf"{key}\Child", key):
        with contextlib.suppress(FileNotFoundError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def test_user_registry_writes_reads_and_deletes_values(scratch_key):
    real = UserRegistry()
    key = rf"{scratch_key}\Child"  # created on the first write, parents too

    real.write(key, "Name", r'"C:\Path With Spaces\App.exe"')
    assert real.read(key, "Name") == r'"C:\Path With Spaces\App.exe"'

    real.delete(key, "Name")
    assert real.read(key, "Name") is None


def test_user_registry_reads_and_deletes_missing_values_quietly(scratch_key):
    real = UserRegistry()
    assert real.read(scratch_key, "Missing") is None
    real.delete(scratch_key, "Missing")  # no key at all
    real.write(scratch_key, "Other", "x")
    real.delete(scratch_key, "Missing")  # key without that value
    assert real.read(scratch_key, "Other") == "x"


def test_user_registry_reads_binary_values(scratch_key):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, scratch_key) as handle:
        winreg.SetValueEx(handle, "Flags", 0, winreg.REG_BINARY, DISABLED)
    assert UserRegistry().read(scratch_key, "Flags") == DISABLED


def test_the_test_suite_never_uses_the_real_registry():
    assert not isinstance(autostart.default_registry(), UserRegistry)
