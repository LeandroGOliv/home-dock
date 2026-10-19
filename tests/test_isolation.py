"""Guards of the suite itself: no test may reach the LAN or read the real secret sources."""

from pathlib import Path

import pytest
import tinytuya

import check_tuya_secrets
from homedock.devices import DeviceError, scan_lan


def test_tests_never_build_a_tinytuya_device(network_attempts):
    with pytest.raises(OSError):
        tinytuya.Device("bf1a2b3c4d5e6f7a8b9c", "192.0.2.10", "0123456789abcdef", version=3.4)
    assert network_attempts == ["tinytuya.Device"]
    network_attempts.clear()  # expected here: do not fail the test at teardown


def test_tests_never_scan_the_lan(network_attempts):
    with pytest.raises(DeviceError):
        scan_lan(scan_time=0.1)
    assert network_attempts == ["tinytuya.scanner.devices"]
    network_attempts.clear()


def test_the_real_secret_sources_are_never_read():
    sources = check_tuya_secrets.default_sources()
    assert Path.home() / "tuya-wizard" not in sources
    assert all("pytest" in str(source) for source in sources)
