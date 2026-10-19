"""LAN discovery: tinytuya's scanner is replaced by a fake (no network)."""

import pytest

from homedock.devices import DeviceError, FoundDevice, scan_lan

# Fictitious values (documentation range 192.0.2.0/24).
REPLY = {
    "fakedevice00000001": {"gwId": "fakedevice00000001", "ip": "192.0.2.10", "version": "3.4"},
    "fakedevice00000002": {"gwId": "fakedevice00000002", "ip": "192.0.2.11", "version": ""},
}


class FakeScanner:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, **options):
        self.calls.append(options)
        if self.error is not None:
            raise self.error
        return self.reply


def test_the_found_devices_are_returned_with_their_ip_and_version():
    found = scan_lan(scanner=FakeScanner(REPLY))
    assert found == [
        FoundDevice("fakedevice00000001", "192.0.2.10", "3.4"),
        FoundDevice("fakedevice00000002", "192.0.2.11", ""),
    ]


def test_the_scan_only_listens_and_never_reads_a_devices_file():
    scanner = FakeScanner({})
    scan_lan(scan_time=7, scanner=scanner)
    [options] = scanner.calls
    assert options["poll"] is False  # polling would connect to the devices
    assert options["verbose"] is False
    assert options["forcescan"] is False
    assert options["byID"] is True
    assert options["scantime"] == 7
    # tinytuya loads devices.json from the working directory when given no devices.
    assert options["tuyadevices"]


def test_entries_without_an_ip_are_skipped():
    reply = {"fakedevice00000003": {"ip": ""}, "": {"ip": "192.0.2.12"}, "x": "garbage"}
    assert scan_lan(scanner=FakeScanner(reply)) == []


@pytest.mark.parametrize("ip", ["192.0.2.300", "evil.example", "192.0.2.1:6668", None, 42])
def test_entries_with_an_invalid_ip_are_skipped(ip):
    # The IPs come from unauthenticated broadcasts: they end up in devices.json.
    assert scan_lan(scanner=FakeScanner({"fakedevice00000004": {"ip": ip}})) == []


@pytest.mark.parametrize("ip", ["8.8.8.8", "127.0.0.1", "0.0.0.0", "255.255.255.255"])
def test_entries_outside_the_lan_are_skipped(ip):
    # A forged broadcast must not send the device's connection (and handshake) off the LAN.
    assert scan_lan(scanner=FakeScanner({"fakedevice00000005": {"ip": ip}})) == []


def test_no_reply_means_no_devices():
    assert scan_lan(scanner=FakeScanner(None)) == []


def test_a_failing_scan_raises_device_error_without_the_library_message():
    error = OSError("[WinError 10048] address 192.0.2.1:6667 already in use")
    with pytest.raises(DeviceError) as caught:
        scan_lan(scanner=FakeScanner(error=error))
    assert "192.0.2.1" not in str(caught.value)
    assert "OSError" in str(caught.value)


def test_the_repr_hides_the_id_and_the_ip():
    text = repr(FoundDevice("fakedevice00000001", "192.0.2.10", "3.4"))
    assert "fakedevice00000001" not in text
    assert "192.0.2.10" not in text
